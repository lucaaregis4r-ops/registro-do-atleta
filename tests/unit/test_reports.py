from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.reports.enriched import build_approved_literature_report
from registro_atleta.reports.status import build_status_panel
from registro_atleta.reports.weekly import build_weekly_report


def test_weekly_report_and_status_panel_are_created(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
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
            VALUES ('alert-1', 'OLY-ATH-000001', 'fixture', '2026-07-01', 'low',
                    'open', 'test', '{}', 'Fixture', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, finished_at, status, code_version)
            VALUES ('run', 'start', 'finish', 'success', 'test')
            """
        )

    weekly = build_weekly_report(tmp_path, database_path=db_path)
    status = build_status_panel(tmp_path, database_path=db_path)

    assert weekly.report_path.exists()
    assert weekly.alerts_count == 1
    assert status.exists()
    assert "Registro do Atleta" in status.read_text(encoding="utf-8")


def test_approved_literature_report_uses_only_approved_links(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO papers (paper_id, title, publication_year, journal, doi, abstract, source_provider)
            VALUES ('paper-1', 'Artigo aprovado', 2025, 'Journal A', '10.1/ok', 'Resumo', 'crossref')
            """
        )
        connection.execute(
            """
            INSERT INTO papers (paper_id, title, publication_year, journal, doi, source_provider)
            VALUES ('paper-2', 'Artigo pendente', 2024, 'Journal B', '10.1/no', 'crossref')
            """
        )
        connection.execute(
            """
            INSERT INTO paper_topics
            (paper_topic_id, paper_id, topic, reason_selected, human_status, created_at)
            VALUES ('pt-1', 'paper-1', 'fadiga', 'Aprovado pela equipe.', 'approved', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO paper_topics
            (paper_topic_id, paper_id, topic, reason_selected, human_status, created_at)
            VALUES ('pt-2', 'paper-2', 'fadiga', 'Ainda nao revisado.', 'pending_review', 'now')
            """
        )
    connection.close()

    result = build_approved_literature_report(tmp_path, database_path=db_path)
    text = result.report_path.read_text(encoding="utf-8")

    assert result.approved_links == 1
    assert result.approved_papers == 1
    assert "Artigo aprovado" in text
    assert "Artigo pendente" not in text
    assert "Base textual usada: `abstract`" in text
