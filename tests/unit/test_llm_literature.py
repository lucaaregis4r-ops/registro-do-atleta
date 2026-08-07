from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.llm.pipeline import build_llm_literature
from registro_atleta.llm.provider import DisabledLlmProvider
from registro_atleta.llm.research_report import approve_research_report_articles


def test_disabled_llm_provider_returns_deterministic_summary() -> None:
    result = DisabledLlmProvider().generate({"summary": {"alerts_total": 2, "quality_total": 1}, "topics": []})

    assert result.status == "disabled"
    assert "LLM desabilitado" in result.output_text


def test_build_llm_literature_creates_topics_and_generation(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('OLY-ATH-000001', 'Ana Silva', 'ANA SILVA', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO alerts
            (alert_id, athlete_id, alert_type, reference_date, severity, status,
             rule_version, evidence_json, human_summary, created_at)
            VALUES ('alert-1', 'OLY-ATH-000001', 'psr_high_pain', '2026-07-01',
                    'high', 'open', 'test', '{}', 'Dor alta', 'now')
            """
        )
    connection.close()

    result = build_llm_literature(tmp_path, database_path=db_path)

    assert result.topics_created == 1
    assert result.generation_status == "disabled"
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM literature_search_topics").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM llm_generations").fetchone()[0] == 1


def test_approve_research_report_articles_imports_approved_links(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    connection.close()
    report_path = tmp_path / "llm-research-report.md"
    report_path.write_text(
        "\n".join(
            [
                "# Relatorio",
                "",
                "## Artigos Candidatos Lidos",
                "",
                "| Query | Ano | Titulo | DOI | Base usada |",
                "|---|---:|---|---|---|",
                "| fatigue monitoring athletes | 2024 | Fatigue Monitoring In Athletes | 10.123/test | abstract |",
                "",
                "## Nota",
            ]
        ),
        encoding="utf-8",
    )

    result = approve_research_report_articles(report_path, db_path, reviewed_by="Lucas")

    assert result.approved_articles == 1
    assert result.approved_links == 1
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
    assert connection.execute("SELECT human_status FROM paper_topics").fetchone()[0] == "approved"
    assert connection.execute("SELECT decision, reviewed_by FROM paper_topic_reviews").fetchone() == ("approved", "Lucas")
    connection.close()
