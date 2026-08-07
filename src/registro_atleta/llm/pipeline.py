from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now
from registro_atleta.literature.topics import LiteratureTopic, generate_literature_topics
from registro_atleta.llm.provider import provider_from_env


@dataclass
class LlmLiteratureResult:
    topics_created: int = 0
    generation_status: str = "not_started"
    generation_provider: str = "unknown"
    generation_model: str | None = None
    output_text: str = ""
    report_path: Path | None = None


def build_llm_literature(root: Path, database_path: Path | None = None) -> LlmLiteratureResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    result = LlmLiteratureResult()
    with connection:
        connection.execute("DELETE FROM literature_search_topics")
        connection.execute("DELETE FROM paper_topics WHERE paper_id IS NULL AND human_status = 'pending_search'")
        topics = generate_literature_topics(connection)
        result.topics_created = _store_topics(connection, topics)
        prompt = _build_prompt(connection, topics)
        provider = provider_from_env()
        llm_result = provider.generate(prompt)
        result.generation_status = llm_result.status
        result.generation_provider = llm_result.provider
        result.generation_model = llm_result.model
        result.output_text = llm_result.output_text
        _store_generation(connection, provider=llm_result.provider, model=llm_result.model, prompt=prompt, output_text=llm_result.output_text, status=llm_result.status)
    result.report_path = _write_report(root, result, topics)
    connection.close()
    return result


def _store_topics(connection: sqlite3.Connection, topics: list[LiteratureTopic]) -> int:
    now = utc_now()
    for topic in topics:
        connection.execute(
            """
            INSERT INTO literature_search_topics
            (topic_id, topic, source_alert_type, source_count, priority, reason_selected, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid4().hex, topic.topic, topic.source_alert_type, topic.source_count, topic.priority, topic.reason_selected, "pending_search", now),
        )
        connection.execute(
            """
            INSERT INTO paper_topics
            (paper_topic_id, paper_id, topic, sport, body_region, relevance_score, reason_selected, human_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid4().hex, None, topic.topic, None, None, None, topic.reason_selected, "pending_search", now),
        )
    return len(topics)


def _build_prompt(connection: sqlite3.Connection, topics: list[LiteratureTopic]) -> dict:
    alerts_total = connection.execute("SELECT COUNT(*) FROM alerts WHERE status = 'open'").fetchone()[0]
    quality_total = connection.execute("SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open'").fetchone()[0]
    alert_rows = connection.execute(
        "SELECT alert_type, severity, COUNT(*) count FROM alerts WHERE status = 'open' GROUP BY alert_type, severity ORDER BY count DESC"
    ).fetchall()
    return {
        "task": "summarize_alerts_and_literature_topics",
        "language": "pt-BR",
        "output_requirements": [
            "Responder em portugues do Brasil.",
            "Ser curto, operacional e objetivo.",
            "Nao terminar com perguntas ao usuario.",
            "Separar fatos internos, pontos de atencao e proximas acoes.",
            "Nao diagnosticar atletas.",
        ],
        "constraints": [
            "Nao diagnosticar.",
            "Nao afirmar causalidade.",
            "Nao modificar banco principal.",
            "Separar achados internos de evidencia cientifica.",
        ],
        "summary": {"alerts_total": alerts_total, "quality_total": quality_total},
        "alert_distribution": [dict(row) for row in alert_rows],
        "topics": [topic.__dict__ for topic in topics],
    }


def _store_generation(connection: sqlite3.Connection, provider: str, model: str | None, prompt: dict, output_text: str, status: str) -> None:
    connection.execute(
        """
        INSERT INTO llm_generations
        (generation_id, generation_type, provider, model, prompt_json, output_text, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            "weekly_alert_summary",
            provider,
            model,
            json.dumps(prompt, ensure_ascii=False, sort_keys=True),
            output_text,
            status,
            utc_now(),
        ),
    )


def _write_report(root: Path, result: LlmLiteratureResult, topics: list[LiteratureTopic]) -> Path:
    report_dir = root / "data" / "reports" / "llm"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"llm-literature-{utc_now().replace(':', '').replace('+', 'Z')}.md"
    lines = [
        "# Relatorio LLM E Literatura",
        "",
        f"- topicos_criados: `{result.topics_created}`",
        f"- status_geracao: `{result.generation_status}`",
        f"- provedor: `{result.generation_provider}`",
        f"- modelo: `{result.generation_model or ''}`",
        "",
        "## Texto Gerado",
        "",
        result.output_text or "Nenhum texto gerado.",
        "",
        "## Temas Para Busca Cientifica",
        "",
        "| Prioridade | Tema | Origem | Quantidade | Motivo |",
        "|---:|---|---|---:|---|",
    ]
    for topic in topics:
        lines.append(f"| {topic.priority} | {topic.topic} | {topic.source_alert_type or ''} | {topic.source_count} | {topic.reason_selected} |")
    lines.extend(
        [
            "",
            "## Observacao",
            "",
            "A busca de artigos e downloads de modelos nao sao automaticos. O LLM e controlado por variaveis de ambiente e pelo executavel noturno.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
