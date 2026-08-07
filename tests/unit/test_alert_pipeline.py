from pathlib import Path
import sqlite3

from registro_atleta.alerts.pipeline import build_alerts
from registro_atleta.database.schema import connect_database, initialize_database


def test_build_alerts_creates_high_pain_alert(tmp_path: Path) -> None:
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
            INSERT INTO source_systems (source_id, source_type, name, domain, enabled, created_at)
            VALUES ('test-source', 'fixture', 'fixture', 'test', 1, 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, status, code_version)
            VALUES ('run', 'now', 'success', 'test')
            """
        )
        connection.execute(
            """
            INSERT INTO source_snapshots
            (snapshot_id, run_id, source_id, collected_at, local_path, file_hash, row_count, status)
            VALUES ('snap', 'run', 'test-source', 'now', 'x', 'h', 1, 'ok')
            """
        )
        connection.execute(
            """
            INSERT INTO source_records
            (source_record_id, source_id, snapshot_id, source_row_key, record_hash, raw_payload_json,
             first_seen_at, last_seen_at, is_current)
            VALUES ('source-1', 'test-source', 'snap', 'row-1', 'hash', '{}', 'now', 'now', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO psr_responses
            (psr_id, athlete_id, source_record_id, response_date, pain_intensity,
             fatigue_score, sleep_score, muscle_soreness_score, stress_score, mood_score,
             raw_values_json, created_at)
            VALUES ('psr-1', 'OLY-ATH-000001', 'source-1', '2026-07-01', 8, 4, 4, 4, 2, 2, '{}', 'now')
            """
        )

    result = build_alerts(tmp_path, database_path=db_path)

    assert result.alerts_created >= 1
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM alerts WHERE alert_type = 'psr_high_pain'").fetchone()[0] == 1


def test_build_alerts_uses_date_overrides_for_psr_windows_and_quality(tmp_path: Path) -> None:
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
            INSERT INTO source_systems (source_id, source_type, name, domain, enabled, created_at)
            VALUES ('test-source', 'fixture', 'fixture', 'test', 1, 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, status, code_version)
            VALUES ('run', 'now', 'success', 'test')
            """
        )
        connection.execute(
            """
            INSERT INTO source_snapshots
            (snapshot_id, run_id, source_id, collected_at, local_path, file_hash, row_count, status)
            VALUES ('snap', 'run', 'test-source', 'now', 'x', 'h', 1, 'ok')
            """
        )
        connection.execute(
            """
            INSERT INTO source_records
            (source_record_id, source_id, snapshot_id, source_row_key, record_hash, raw_payload_json,
             first_seen_at, last_seen_at, is_current)
            VALUES ('source-1', 'test-source', 'snap', 'row-1', 'hash', '{}', 'now', 'now', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO psr_responses
            (psr_id, athlete_id, source_record_id, response_date, pain_intensity,
             raw_values_json, created_at)
            VALUES ('psr-1', 'OLY-ATH-000001', 'source-1', '2099-01-01', 8, '{}', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO date_overrides
            (override_id, entity_type, entity_id, source_record_id, field_name, original_value,
             corrected_value, override_status, reason, reviewed_by, reviewed_at, finding_id)
            VALUES ('override-1', 'psr_responses', 'psr-1', 'source-1', 'response_date',
                    '2099-01-01', '2026-07-01', 'active', 'reviewed', 'Lucas', 'now', NULL)
            """
        )
    connection.close()

    result = build_alerts(tmp_path, database_path=db_path)

    assert result.alerts_created == 1
    connection = sqlite3.connect(db_path)
    alert = connection.execute("SELECT reference_date, evidence_json FROM alerts WHERE alert_type = 'psr_high_pain'").fetchone()
    assert alert[0] == "2026-07-01"
    assert "2099-01-01" in alert[1]
    assert connection.execute("SELECT COUNT(*) FROM data_quality_findings WHERE finding_type = 'psr_invalid_or_future_date'").fetchone()[0] == 0


def test_build_alerts_supersedes_referenced_previous_alerts(tmp_path: Path) -> None:
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
            VALUES ('alert-old', 'OLY-ATH-000001', 'fixture', '2026-07-01', 'low',
                    'open', 'test', '{}', 'Fixture', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO report_runs
            (report_run_id, report_type, reference_date, status, generated_at, payload_json)
            VALUES ('report-1', 'nightly_briefing', '2026-07-15', 'success', 'now', '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO report_items
            (report_item_id, report_run_id, item_type, alert_id, priority_bucket,
             priority_score, headline, evidence_json, display_order, included_in_main_brief, created_at)
            VALUES ('item-1', 'report-1', 'alert_episode', 'alert-old', 'new',
                    1, 'Item antigo', '{}', 1, 1, 'now')
            """
        )
    connection.close()

    build_alerts(tmp_path, database_path=db_path)

    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT status FROM alerts WHERE alert_id = 'alert-old'").fetchone()[0] == "superseded"
    assert connection.execute("SELECT COUNT(*) FROM report_items WHERE alert_id = 'alert-old'").fetchone()[0] == 1
