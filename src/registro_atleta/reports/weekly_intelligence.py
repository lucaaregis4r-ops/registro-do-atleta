from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import re
import sqlite3
from typing import Any
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now
from registro_atleta.llm.provider import provider_from_env


@dataclass(frozen=True)
class WeeklyIntelligenceResult:
    report_path: Path
    json_path: Path
    period_start: str
    period_end: str
    llm_status: str
    articles_included: int


def build_weekly_intelligence_report(
    root: Path,
    database_path: Path | None = None,
    days: int = 7,
    reference_date: str | None = None,
    provider=None,
) -> WeeklyIntelligenceResult:
    if not 1 <= days <= 31:
        raise ValueError("days deve estar entre 1 e 31")
    period_end = _parse_reference_date(reference_date)
    period_start = period_end - timedelta(days=days - 1)
    start_at = f"{period_start.isoformat()}T00:00:00"
    end_exclusive = f"{(period_end + timedelta(days=1)).isoformat()}T00:00:00"
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"

    connection = connect_database(database_path)
    initialize_database(connection)
    deterministic = _deterministic_changes(connection, start_at, end_exclusive)
    articles = _approved_articles(connection, limit=20)
    prompt = _structured_prompt(period_start, period_end, deterministic, articles)
    llm_provider = provider or provider_from_env()
    llm_result = llm_provider.generate(prompt)
    structured, output_status = _structured_output(llm_result.output_text, llm_result.status, articles)

    payload = {
        "generated_at": utc_now(),
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat(), "days": days},
        "deterministic_changes": deterministic,
        "literature": {
            "selection_rule": "somente vinculos tema-artigo com revisao humana approved",
            "articles": articles,
            "structured_analysis": structured,
        },
        "llm": {
            "provider": llm_result.provider,
            "model": llm_result.model,
            "provider_status": llm_result.status,
            "output_status": output_status,
        },
        "governance": [
            "Numeros, titulos, DOI e status vem do banco e nao do LLM.",
            "Interpretacoes nao sao diagnostico, causalidade ou conduta clinica.",
            "Artigos sem abstract sao analisados apenas por metadados.",
        ],
    }
    generation_id = uuid4().hex
    with connection:
        connection.execute(
            """
            INSERT INTO llm_generations
            (generation_id, generation_type, provider, model, prompt_json, output_text, status, created_at)
            VALUES (?, 'weekly_intelligence_report', ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                llm_result.provider,
                llm_result.model,
                json.dumps(prompt, ensure_ascii=False, sort_keys=True),
                llm_result.output_text,
                output_status,
                utc_now(),
            ),
        )
    connection.close()

    report_dir = root / "data" / "reports" / "weekly-intelligence"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("+", "Z")
    report_path = report_dir / f"weekly-intelligence-{stamp}.md"
    json_path = report_dir / f"weekly-intelligence-{stamp}.json"
    report_path.write_text(_render_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return WeeklyIntelligenceResult(
        report_path=report_path,
        json_path=json_path,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        llm_status=output_status,
        articles_included=len(articles),
    )


def _deterministic_changes(connection: sqlite3.Connection, start_at: str, end_exclusive: str) -> dict[str, Any]:
    run = connection.execute(
        """
        SELECT COUNT(*) runs, COALESCE(SUM(records_created), 0) records_created,
               COALESCE(SUM(records_updated), 0) records_updated,
               COALESCE(SUM(errors), 0) errors
        FROM pipeline_runs
        WHERE started_at >= ? AND started_at < ?
        """,
        (start_at, end_exclusive),
    ).fetchone()
    sources = [
        dict(row)
        for row in connection.execute(
            """
            SELECT source_id, COUNT(*) new_versions
            FROM source_records
            WHERE first_seen_at >= ? AND first_seen_at < ?
            GROUP BY source_id
            ORDER BY new_versions DESC, source_id
            """,
            (start_at, end_exclusive),
        ).fetchall()
    ]
    episodes = [
        dict(row)
        for row in connection.execute(
            """
            SELECT novelty_status, current_severity, COUNT(*) count
            FROM alert_episodes
            WHERE updated_at >= ? AND updated_at < ?
            GROUP BY novelty_status, current_severity
            ORDER BY count DESC, novelty_status, current_severity
            """,
            (start_at, end_exclusive),
        ).fetchall()
    ]
    reviews = {
        "identity": _period_count(connection, "identity_reviews", "reviewed_at", start_at, end_exclusive),
        "dates": _period_count(connection, "date_quality_reviews", "reviewed_at", start_at, end_exclusive),
        "duplicates": _period_count(connection, "duplicate_quality_reviews", "reviewed_at", start_at, end_exclusive),
        "alerts": _period_count(connection, "alert_reviews", "reviewed_at", start_at, end_exclusive),
        "literature": _period_count(connection, "paper_topic_reviews", "reviewed_at", start_at, end_exclusive),
    }
    return {
        "pipeline": {
            "runs": run["runs"],
            "records_created": run["records_created"],
            "records_updated": run["records_updated"],
            "errors": run["errors"],
        },
        "source_versions": sources,
        "episode_changes": episodes,
        "human_reviews": reviews,
        "current_state": {
            "athletes": _scalar(connection, "SELECT COUNT(*) FROM athletes WHERE merged_into_athlete_id IS NULL"),
            "psr_responses": _scalar(connection, "SELECT COUNT(*) FROM psr_responses"),
            "physio_cases": _scalar(connection, "SELECT COUNT(*) FROM physio_cases"),
            "assessments": _scalar(connection, "SELECT COUNT(*) FROM physical_assessments"),
            "open_alerts": _scalar(connection, "SELECT COUNT(*) FROM alerts WHERE status = 'open'"),
            "active_episodes": _scalar(connection, "SELECT COUNT(*) FROM alert_episodes WHERE episode_status = 'active'"),
            "open_quality_findings": _scalar(connection, "SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open'"),
            "pending_identity": _scalar(connection, "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'"),
        },
    }


def _approved_articles(connection: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT p.paper_id, p.title, p.authors_json, p.publication_year, p.journal,
               p.doi, p.url, p.abstract, p.source_provider,
               GROUP_CONCAT(DISTINCT pt.topic) topics
        FROM papers p
        JOIN paper_topics pt ON pt.paper_id = p.paper_id
        WHERE pt.human_status = 'approved'
        GROUP BY p.paper_id
        ORDER BY COALESCE(p.publication_year, 0) DESC, p.title
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    articles = []
    for row in rows:
        article = dict(row)
        article["evidence_base"] = "abstract" if row["abstract"] else "metadata_only"
        article["analysis_readiness"] = "abstract_available" if row["abstract"] else "needs_revalidation"
        article["review_warning"] = (
            "Resumo disponivel para analise assistida; confirmar o texto integral antes de aplicar conclusoes."
            if row["abstract"]
            else "Somente metadados disponiveis; titulo e aprovacao humana nao bastam para inferir resultados."
        )
        article["abstract"] = (row["abstract"] or "")[:1800]
        articles.append(article)
    return articles


def _structured_prompt(period_start: date, period_end: date, deterministic: dict, articles: list[dict]) -> dict:
    return {
        "task": "weekly_club_changes_and_structured_literature_analysis",
        "language": "pt-BR",
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "deterministic_changes": deterministic,
        "approved_articles": articles,
        "output_schema": {
            "executive_summary": ["string"],
            "article_assessments": [
                {
                    "paper_id": "must match an input paper_id",
                    "main_message": "string",
                    "relation_to_weekly_changes": "string",
                    "limitations": "string",
                    "practical_consideration": "string",
                    "confidence": "low|medium|high",
                }
            ],
            "cross_article_synthesis": ["string"],
            "limitations": ["string"],
        },
        "instructions": [
            "Responda somente JSON valido, sem markdown.",
            "Analise apenas os artigos fornecidos e preserve paper_id.",
            "Nao invente resultados ausentes no abstract ou metadados.",
            "Quando evidence_base for metadata_only, limite confidence a low.",
            "Quando analysis_readiness for needs_revalidation, nao infira mensagem cientifica nem aplicacao pratica.",
            "Nao cite nomes ou IDs de atletas.",
            "Nao diagnostique, nao afirme causalidade e nao prescreva conduta.",
            "Separe fato deterministico, interpretacao e limitacao.",
        ],
    }


def _structured_output(output_text: str, provider_status: str, articles: list[dict]) -> tuple[dict, str]:
    parsed = _parse_json_object(output_text) if provider_status == "success" else None
    valid_ids = {article["paper_id"] for article in articles}
    articles_by_id = {article["paper_id"]: article for article in articles}
    if not isinstance(parsed, dict):
        return _fallback_analysis(articles), "deterministic_fallback"
    assessments = []
    for item in parsed.get("article_assessments", []):
        if not isinstance(item, dict) or item.get("paper_id") not in valid_ids:
            continue
        article = articles_by_id[item["paper_id"]]
        confidence = item.get("confidence") if item.get("confidence") in {"low", "medium", "high"} else "low"
        if article["analysis_readiness"] == "needs_revalidation":
            confidence = "low"
        assessments.append(
            {
                "paper_id": item["paper_id"],
                "main_message": str(item.get("main_message", "")).strip(),
                "relation_to_weekly_changes": str(item.get("relation_to_weekly_changes", "")).strip(),
                "limitations": str(item.get("limitations", "")).strip(),
                "practical_consideration": str(item.get("practical_consideration", "")).strip(),
                "confidence": confidence,
            }
        )
    if articles and not assessments:
        return _fallback_analysis(articles), "deterministic_fallback"
    return {
        "executive_summary": _string_list(parsed.get("executive_summary")),
        "article_assessments": assessments,
        "cross_article_synthesis": _string_list(parsed.get("cross_article_synthesis")),
        "limitations": _string_list(parsed.get("limitations")),
    }, "success"


def _fallback_analysis(articles: list[dict]) -> dict:
    return {
        "executive_summary": [
            "Analise do LLM indisponivel ou invalida; os fatos deterministicos permanecem utilizaveis."
        ],
        "article_assessments": [
            {
                "paper_id": article["paper_id"],
                "main_message": "Nao inferido automaticamente.",
                "relation_to_weekly_changes": "Requer leitura humana do artigo e comparacao com os fatos da semana.",
                "limitations": "Base disponivel: " + article["evidence_base"],
                "practical_consideration": (
                    "Revalidar a pertinencia e obter o resumo ou texto integral antes de usar."
                    if article["analysis_readiness"] == "needs_revalidation"
                    else "Manter como referencia aprovada, sem transformar em conduta automatica."
                ),
                "confidence": "low",
            }
            for article in articles
        ],
        "cross_article_synthesis": [],
        "limitations": ["Fallback deterministico: nenhuma conclusao cientifica foi gerada pelo LLM."],
    }


def _render_markdown(payload: dict) -> str:
    changes = payload["deterministic_changes"]
    analysis = payload["literature"]["structured_analysis"]
    articles = {article["paper_id"]: article for article in payload["literature"]["articles"]}
    lines = [
        "# Relatorio Semanal Integrado - Dados E Literatura",
        "",
        f"- periodo: `{payload['period']['start']}` a `{payload['period']['end']}`",
        f"- gerado_em_utc: `{payload['generated_at']}`",
        f"- status_llm: `{payload['llm']['output_status']}`",
        f"- modelo: `{payload['llm']['model'] or ''}`",
        "",
        "## Mudancas Deterministicas Da Semana",
        "",
        f"- Execucoes de sincronizacao: `{changes['pipeline']['runs']}`",
        f"- Registros novos: `{changes['pipeline']['records_created']}`",
        f"- Registros alterados: `{changes['pipeline']['records_updated']}`",
        f"- Erros de coleta: `{changes['pipeline']['errors']}`",
        f"- Revisoes humanas: `{sum(changes['human_reviews'].values())}`",
        "",
        "### Estado Atual",
        "",
    ]
    lines.extend(f"- {key}: `{value}`" for key, value in changes["current_state"].items())
    lines.extend(["", "### Fontes Com Novas Versoes", "", "| Fonte | Novas versoes |", "|---|---:|"])
    lines.extend(f"| {row['source_id']} | {row['new_versions']} |" for row in changes["source_versions"])
    if not changes["source_versions"]:
        lines.append("| nenhuma | 0 |")
    lines.extend(["", "### Mudancas Em Episodios", "", "| Estado | Severidade | Quantidade |", "|---|---|---:|"])
    lines.extend(f"| {row['novelty_status']} | {row['current_severity']} | {row['count']} |" for row in changes["episode_changes"])
    if not changes["episode_changes"]:
        lines.append("| nenhuma | - | 0 |")
    lines.extend(["", "## Sintese Estruturada Do LLM", ""])
    lines.extend(f"- {item}" for item in analysis["executive_summary"])
    if not analysis["executive_summary"]:
        lines.append("- Sem sintese gerada.")
    needs_revalidation = sum(
        article["analysis_readiness"] == "needs_revalidation" for article in articles.values()
    )
    lines.extend(
        [
            "",
            "### Prontidao Dos Artigos",
            "",
            f"- Artigos incluidos: `{len(articles)}`",
            f"- Precisam de revalidacao antes de inferencia cientifica: `{needs_revalidation}`",
        ]
    )
    lines.extend(["", "## Artigos Aprovados - Analise Estruturada", ""])
    for assessment in analysis["article_assessments"]:
        article = articles.get(assessment["paper_id"])
        if not article:
            continue
        lines.extend(
            [
                f"### {article['title']}",
                "",
                f"- Ano/periodico: `{article['publication_year'] or ''}` / {article['journal'] or 'nao informado'}",
                f"- DOI/URL: {article['doi'] or article['url'] or 'nao informado'}",
                f"- Temas: {article['topics'] or ''}",
                f"- Base usada: `{article['evidence_base']}`",
                f"- Prontidao para analise: `{article['analysis_readiness']}`",
                f"- Aviso de revisao: {article['review_warning']}",
                f"- Mensagem principal: {assessment['main_message']}",
                f"- Relacao com a semana: {assessment['relation_to_weekly_changes']}",
                f"- Limitacoes: {assessment['limitations']}",
                f"- Consideracao pratica: {assessment['practical_consideration']}",
                f"- Confianca da interpretacao: `{assessment['confidence']}`",
                "",
            ]
        )
    lines.extend(["## Sintese Entre Artigos", ""])
    lines.extend(f"- {item}" for item in analysis["cross_article_synthesis"])
    if not analysis["cross_article_synthesis"]:
        lines.append("- Sem sintese cruzada disponivel.")
    lines.extend(["", "## Limitacoes E Governanca", ""])
    lines.extend(f"- {item}" for item in analysis["limitations"])
    lines.extend(f"- {item}" for item in payload["governance"])
    return "\n".join(lines) + "\n"


def _parse_json_object(text: str) -> dict | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def _parse_reference_date(value: str | None) -> date:
    if not value:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("reference_date deve estar em YYYY-MM-DD") from exc


def _period_count(connection: sqlite3.Connection, table: str, field: str, start_at: str, end_exclusive: str) -> int:
    return connection.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {field} >= ? AND {field} < ?",
        (start_at, end_exclusive),
    ).fetchone()[0]


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    return connection.execute(query).fetchone()[0]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
