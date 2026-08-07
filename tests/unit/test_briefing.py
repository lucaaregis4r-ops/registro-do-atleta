from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.reports.briefing import build_nightly_briefing


def test_briefing_keeps_same_alert_episode_and_report_items_idempotent(tmp_path: Path) -> None:
    db_path = _database_with_athlete(tmp_path)
    _insert_alert(db_path, "alert-1", "psr_high_pain", "medium")

    first = build_nightly_briefing(tmp_path, database_path=db_path, main_limit=5, reference_date="2026-07-15")
    second = build_nightly_briefing(tmp_path, database_path=db_path, main_limit=5, reference_date="2026-07-15")

    connection = sqlite3.connect(db_path)
    assert first.report_run_id == second.report_run_id
    assert connection.execute("SELECT COUNT(*) FROM alert_episodes").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM report_runs").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM report_items").fetchone()[0] == 1
    row = connection.execute("SELECT novelty_status, occurrence_count FROM alert_episodes").fetchone()
    assert row == ("ongoing", 1)


def test_briefing_marks_episode_as_escalated(tmp_path: Path) -> None:
    db_path = _database_with_athlete(tmp_path)
    _insert_alert(db_path, "alert-1", "psr_high_pain", "medium")
    build_nightly_briefing(tmp_path, database_path=db_path, reference_date="2026-07-15")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM alerts")
    _insert_alert(db_path, "alert-2", "psr_high_pain", "high")

    build_nightly_briefing(tmp_path, database_path=db_path, reference_date="2026-07-16")

    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT novelty_status FROM alert_episodes").fetchone()[0] == "escalated"


def test_briefing_marks_episode_as_resolved_when_signal_disappears(tmp_path: Path) -> None:
    db_path = _database_with_athlete(tmp_path)
    _insert_alert(db_path, "alert-1", "psr_high_pain", "medium")
    build_nightly_briefing(tmp_path, database_path=db_path, reference_date="2026-07-15")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM alerts")

    result = build_nightly_briefing(tmp_path, database_path=db_path, reference_date="2026-07-16")

    connection = sqlite3.connect(db_path)
    row = connection.execute("SELECT episode_status, novelty_status FROM alert_episodes").fetchone()
    assert row == ("resolved", "resolved")
    assert result.main_items == 1


def test_briefing_sends_items_outside_main_limit_to_appendix(tmp_path: Path) -> None:
    db_path = _database_with_athlete(tmp_path)
    _insert_alert(db_path, "alert-1", "psr_high_pain", "medium")
    _insert_alert(db_path, "alert-2", "psr_multi_wellness_flag", "medium")

    result = build_nightly_briefing(tmp_path, database_path=db_path, main_limit=1, reference_date="2026-07-15")
    text = result.markdown_path.read_text(encoding="utf-8")

    assert result.main_items == 1
    assert result.appendix_items == 1
    assert "## Apendice" in text


def test_briefing_without_changes_is_short(tmp_path: Path) -> None:
    db_path = _database_with_athlete(tmp_path)

    result = build_nightly_briefing(tmp_path, database_path=db_path, reference_date="2026-07-15")
    text = result.markdown_path.read_text(encoding="utf-8")

    assert result.main_items == 0
    assert "Nenhuma mudanca prioritaria" in text


def _database_with_athlete(tmp_path: Path) -> Path:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('athlete-1', 'Ana Silva', 'ANA SILVA', 'now', 'now')
            """
        )
    connection.close()
    return db_path


def _insert_alert(db_path: Path, alert_id: str, alert_type: str, severity: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO alerts
            (alert_id, athlete_id, alert_type, reference_date, severity, status, rule_version,
             evidence_json, human_summary, created_at)
            VALUES (?, 'athlete-1', ?, '2026-07-15', ?, 'open', 'test', '{}', 'Fixture', 'now')
            """,
            (alert_id, alert_type, severity),
        )
