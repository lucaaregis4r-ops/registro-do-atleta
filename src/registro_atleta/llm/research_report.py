from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import sqlite3
from typing import Any
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now
from registro_atleta.literature.search import _crossref_candidates, _crossref_url, _headers, fetch_crossref_json
from registro_atleta.llm.provider import LlmResult, provider_from_env


@dataclass
class LlmResearchReportResult:
    report_path: Path
    search_queries: list[str]
    articles_found: int
    key_generation_status: str
    report_generation_status: str
    model: str | None


@dataclass
class ApprovedResearchArticlesResult:
    approved_articles: int = 0
    duplicate_articles: int = 0
    approved_links: int = 0
    invalid_rows: int = 0


def build_llm_research_report(
    root: Path,
    database_path: Path | None = None,
    max_queries: int = 5,
    results_per_query: int = 3,
    fetcher=fetch_crossref_json,
) -> LlmResearchReportResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    internal_context = _internal_context(connection, root)
    provider = provider_from_env()

    key_prompt = _search_key_prompt(internal_context, max_queries=max_queries)
    key_result = provider.generate(key_prompt)
    search_queries = _parse_search_queries(key_result.output_text, max_queries=max_queries)
    if not search_queries:
        search_queries = _fallback_queries(internal_context, max_queries=max_queries)

    articles: list[dict[str, str]] = []
    search_errors: list[str] = []
    for query in search_queries:
        try:
            payload = fetcher(_crossref_url(query, results_per_query, None), _headers(None))
            articles.extend(_crossref_candidates(payload, topic=query))
        except Exception as exc:  # noqa: BLE001 - external literature search must be recorded, not crash summaries.
            search_errors.append(f"{query}: {type(exc).__name__}: {exc}")

    articles = _dedupe_articles(articles)
    report_prompt = _research_report_prompt(internal_context, search_queries, articles, search_errors)
    report_result = provider.generate(report_prompt)

    with connection:
        _store_generation(connection, "literature_search_keys", key_prompt, key_result)
        _store_generation(connection, "literature_research_report", report_prompt, report_result)

    report_path = _write_report(root, internal_context, search_queries, articles, search_errors, key_result, report_result)
    connection.close()
    return LlmResearchReportResult(
        report_path=report_path,
        search_queries=search_queries,
        articles_found=len(articles),
        key_generation_status=key_result.status,
        report_generation_status=report_result.status,
        model=report_result.model or key_result.model,
    )


def approve_research_report_articles(
    report_path: Path,
    database_path: Path,
    reviewed_by: str,
    notes: str | None = None,
) -> ApprovedResearchArticlesResult:
    reviewed_by = reviewed_by.strip()
    if not reviewed_by:
        raise ValueError("reviewed_by e obrigatorio")
    if not report_path.exists():
        raise FileNotFoundError(report_path)

    rows = _parse_candidate_table(report_path.read_text(encoding="utf-8"))
    result = ApprovedResearchArticlesResult()
    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        for row in rows:
            if not row.get("title"):
                result.invalid_rows += 1
                continue
            paper_id = _find_existing_paper(connection, row)
            if paper_id:
                result.duplicate_articles += 1
            else:
                paper_id = uuid4().hex
                connection.execute(
                    """
                    INSERT INTO papers
                    (paper_id, title, publication_year, doi, url, source_provider)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        row["title"],
                        _optional_int(row.get("year")),
                        _blank_to_none(row.get("doi")),
                        _doi_url(row.get("doi")),
                        "crossref",
                    ),
                )
                result.approved_articles += 1

            existing_topic = connection.execute(
                "SELECT paper_topic_id, human_status FROM paper_topics WHERE paper_id = ? AND topic = ?",
                (paper_id, row["query"]),
            ).fetchone()
            previous_status = existing_topic["human_status"] if existing_topic else "not_linked"
            if existing_topic:
                paper_topic_id = existing_topic["paper_topic_id"]
                connection.execute(
                    "UPDATE paper_topics SET human_status = 'approved' WHERE paper_topic_id = ?",
                    (paper_topic_id,),
                )
            else:
                paper_topic_id = uuid4().hex
                connection.execute(
                    """
                    INSERT INTO paper_topics
                    (paper_topic_id, paper_id, topic, reason_selected, human_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper_topic_id,
                        paper_id,
                        row["query"],
                        "Aprovado a partir do relatorio cientifico noturno com LLM e Crossref.",
                        "approved",
                        utc_now(),
                    ),
                )
            connection.execute(
                """
                INSERT INTO paper_topic_reviews
                (review_id, paper_topic_id, decision, previous_status, new_status,
                 reviewed_by, reviewed_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    paper_topic_id,
                    "approved",
                    previous_status,
                    "approved",
                    reviewed_by,
                    utc_now(),
                    notes or f"Aprovado em lote a partir de {report_path.name}.",
                ),
            )
            result.approved_links += 1
    connection.close()
    return result


def _internal_context(connection: sqlite3.Connection, root: Path) -> dict[str, Any]:
    alert_distribution = [
        dict(row)
        for row in connection.execute(
            """
            SELECT alert_type, severity, COUNT(*) count
            FROM alerts
            WHERE status = 'open'
            GROUP BY alert_type, severity
            ORDER BY count DESC
            LIMIT 20
            """
        ).fetchall()
    ]
    topics = [
        dict(row)
        for row in connection.execute(
            """
            SELECT topic, source_alert_type, source_count, priority, reason_selected
            FROM literature_search_topics
            ORDER BY priority ASC
            LIMIT 10
            """
        ).fetchall()
    ]
    latest_weekly = _latest_file(root / "data" / "reports" / "weekly")
    return {
        "generated_at": utc_now(),
        "latest_weekly_report": str(latest_weekly) if latest_weekly else None,
        "summary": {
            "alerts_open": connection.execute("SELECT COUNT(*) FROM alerts WHERE status = 'open'").fetchone()[0],
            "quality_open": connection.execute("SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open'").fetchone()[0],
            "pending_identity": connection.execute("SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'").fetchone()[0],
            "psr_responses": connection.execute("SELECT COUNT(*) FROM psr_responses").fetchone()[0],
            "physio_cases": connection.execute("SELECT COUNT(*) FROM physio_cases").fetchone()[0],
        },
        "alert_distribution": alert_distribution,
        "current_literature_topics": topics,
    }


def _search_key_prompt(internal_context: dict[str, Any], max_queries: int) -> dict:
    return {
        "task": "gerar_chaves_de_pesquisa_crossref",
        "language": "pt-BR",
        "instructions": [
            "Leia o contexto interno do clube.",
            "Escolha temas relevantes para buscar literatura cientifica no Crossref.",
            "Gere chaves de busca em ingles, pois o Crossref responde melhor.",
            "Nao use nomes de atletas.",
            "Responda somente JSON valido no formato {\"queries\": [\"...\"]}.",
            f"Gere no maximo {max_queries} queries.",
        ],
        "internal_context": internal_context,
    }


def _research_report_prompt(internal_context: dict[str, Any], search_queries: list[str], articles: list[dict[str, str]], search_errors: list[str]) -> dict:
    compact_articles = []
    for article in articles[:15]:
        compact_articles.append(
            {
                "topic": article.get("topic", ""),
                "title": article.get("title", ""),
                "authors": article.get("authors", ""),
                "year": article.get("publication_year", ""),
                "journal": article.get("journal", ""),
                "doi": article.get("doi", ""),
                "url": article.get("url", ""),
                "abstract_or_metadata": (article.get("abstract") or "Sem abstract no Crossref; usar apenas metadados.")[:1800],
                "score": article.get("relevance_score", ""),
            }
        )
    return {
        "task": "relatorio_cientifico_noturno_clube",
        "language": "pt-BR",
        "instructions": [
            "Use os dados internos como ponto de partida.",
            "Use os artigos encontrados no Crossref como literatura candidata ainda nao revisada por humano.",
            "Relacione cada tema com os dados do clube sem diagnosticar atletas.",
            "Nao reproduza tabelas do relatorio interno.",
            "Nao cite IDs de atletas nem nomes de atletas.",
            "Nao transforme metadados em conclusao cientifica.",
            "Diferencie achado interno, evidencia candidata e acao recomendada.",
            "Cite DOI ou URL quando disponivel.",
            "Se houver apenas metadados sem abstract, diga isso.",
            "Nao invente artigo, DOI, resultado ou conclusao.",
            "Nao termine fazendo perguntas.",
            "Estruture com secoes: Sintese executiva, Relacao com dados do clube, Artigos candidatos, Limitacoes, Proximas acoes.",
        ],
        "internal_context": internal_context,
        "search_queries": search_queries,
        "crossref_search_errors": search_errors,
        "candidate_articles": compact_articles,
    }


def _parse_search_queries(output_text: str, max_queries: int) -> list[str]:
    text = output_text.strip()
    candidates = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            candidates = parsed.get("queries", [])
        elif isinstance(parsed, list):
            candidates = parsed
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                candidates = parsed.get("queries", []) if isinstance(parsed, dict) else []
            except json.JSONDecodeError:
                candidates = []
    clean = []
    for item in candidates:
        query = str(item).strip()
        if query and query not in clean:
            clean.append(query)
    return clean[:max_queries]


def _fallback_queries(internal_context: dict[str, Any], max_queries: int) -> list[str]:
    mapping = {
        "psr_multi_wellness_flag": "wellness questionnaire internal load youth athletes",
        "psr_high_pain": "self reported pain injury risk youth athletes",
        "psr_no_recent_response": "wellness questionnaire adherence team sports athletes",
        "psr_fatigue_above_individual_baseline": "fatigue baseline monitoring training load athletes",
        "physio_training_restriction": "return to sport rehabilitation training restriction athletes",
    }
    queries = []
    for row in internal_context.get("alert_distribution", []):
        query = mapping.get(row.get("alert_type"))
        if query and query not in queries:
            queries.append(query)
    return queries[:max_queries]


def _dedupe_articles(articles: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    unique = []
    for article in articles:
        key = (article.get("doi") or article.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(article)
    return unique


def _write_report(
    root: Path,
    internal_context: dict[str, Any],
    search_queries: list[str],
    articles: list[dict[str, str]],
    search_errors: list[str],
    key_result: LlmResult,
    report_result: LlmResult,
) -> Path:
    report_dir = root / "data" / "reports" / "llm"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"llm-research-report-{utc_now().replace(':', '').replace('+', 'Z')}.md"
    lines = [
        "# Relatorio Cientifico Noturno Com LLM",
        "",
        f"- gerado_em_utc: `{utc_now()}`",
        f"- provedor: `{report_result.provider}`",
        f"- modelo: `{report_result.model or key_result.model or ''}`",
        f"- status_chaves_pesquisa: `{key_result.status}`",
        f"- status_relatorio: `{report_result.status}`",
        f"- artigos_candidatos_lidos: `{len(articles)}`",
        "",
        "## Dados Internos Usados",
        "",
        f"- Relatorio semanal: `{internal_context.get('latest_weekly_report') or ''}`",
        f"- Alertas abertos: `{internal_context['summary']['alerts_open']}`",
        f"- Achados de qualidade: `{internal_context['summary']['quality_open']}`",
        f"- Identidades pendentes: `{internal_context['summary']['pending_identity']}`",
        "",
        "## Chaves De Pesquisa Geradas Pelo LLM",
        "",
    ]
    lines.extend(f"- `{query}`" for query in search_queries)
    if search_errors:
        lines.extend(["", "## Erros De Busca Crossref", ""])
        lines.extend(f"- {error}" for error in search_errors)
    lines.extend(["", "## Relatorio Gerado Pelo LLM", "", report_result.output_text or "Nenhum texto gerado.", "", "## Artigos Candidatos Lidos", ""])
    if not articles:
        lines.append("Nenhum artigo retornado pelo Crossref.")
    else:
        lines.extend(["| Query | Ano | Titulo | DOI | Base usada |", "|---|---:|---|---|---|"])
        for article in articles:
            base = "abstract" if article.get("abstract") else "metadados"
            lines.append(
                f"| {article.get('topic', '')} | {article.get('publication_year', '')} | {article.get('title', '')} | {article.get('doi', '') or article.get('url', '')} | {base} |"
            )
    lines.extend(
        [
            "",
            "## Nota De Governanca",
            "",
            "Os artigos acima sao candidatos retornados pelo Crossref e ainda precisam de revisao humana antes de virarem evidencia aprovada do clube.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _store_generation(connection: sqlite3.Connection, generation_type: str, prompt: dict, result: LlmResult) -> None:
    connection.execute(
        """
        INSERT INTO llm_generations
        (generation_id, generation_type, provider, model, prompt_json, output_text, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            generation_type,
            result.provider,
            result.model,
            json.dumps(prompt, ensure_ascii=False, sort_keys=True),
            result.output_text,
            result.status,
            utc_now(),
        ),
    )


def _latest_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    files = sorted(path.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _parse_candidate_table(text: str) -> list[dict[str, str]]:
    in_table = False
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| Query | Ano | Titulo | DOI | Base usada |"):
            in_table = True
            continue
        if not in_table:
            continue
        if stripped.startswith("|---"):
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        parts = [part.strip() for part in stripped.strip("|").split("|")]
        if len(parts) < 5:
            continue
        rows.append(
            {
                "query": parts[0],
                "year": parts[1],
                "title": parts[2],
                "doi": parts[3],
                "base": parts[4],
            }
        )
    return rows


def _find_existing_paper(connection: sqlite3.Connection, row: dict[str, str]) -> str | None:
    doi = _blank_to_none(row.get("doi"))
    if doi:
        existing = connection.execute("SELECT paper_id FROM papers WHERE LOWER(doi) = LOWER(?)", (doi,)).fetchone()
        if existing:
            return existing["paper_id"]
    title = row.get("title", "").strip()
    existing = connection.execute("SELECT paper_id FROM papers WHERE LOWER(title) = LOWER(?)", (title,)).fetchone()
    return existing["paper_id"] if existing else None


def _optional_int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _doi_url(value: str | None) -> str | None:
    doi = _blank_to_none(value)
    if not doi:
        return None
    if doi.startswith("http://") or doi.startswith("https://"):
        return doi
    return f"https://doi.org/{doi}"
