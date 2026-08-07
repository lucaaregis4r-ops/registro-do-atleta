from pathlib import Path

from registro_atleta.analytics.phase9 import assess_phase9_readiness, build_phase9_exploratory_report
from registro_atleta.database.schema import connect_database, initialize_database


def test_phase9_readiness_blocks_when_plan_prerequisites_are_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO data_quality_findings
            (finding_id, finding_type, entity_type, entity_id, severity, status,
             evidence_json, human_summary, created_at)
            VALUES ('q-1', 'invalid_date', 'psr_response', 'psr-1', 'high', 'open',
                    '{}', 'Data invalida.', 'now')
            """
        )
    connection.close()

    result = assess_phase9_readiness(tmp_path, database_path=db_path)
    statuses = {check.name: check.status for check in result.checks}

    assert result.overall_status == "blocked"
    assert result.models_allowed is False
    assert statuses["date_reliability"] == "blocked"
    assert statuses["methodological_validation"] == "blocked"
    assert result.report_path.exists()
    assert result.json_path.exists()


def test_phase9_exploratory_report_is_descriptive_when_gate_blocks(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    connection.close()

    result = build_phase9_exploratory_report(tmp_path, database_path=db_path)
    text = result.report_path.read_text(encoding="utf-8")

    assert result.status == "advanced_models_blocked"
    assert result.models_allowed is False
    assert result.report_path.exists()
    assert "descriptive only" in text
    assert "Methodological lock" in text


def test_phase9_date_reliability_uses_reviewed_date_overrides(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO source_systems (source_id, source_type, name, domain, created_at)
            VALUES ('source-1', 'fixture', 'Fixture', 'psr', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, status, code_version)
            VALUES ('run-1', 'now', 'success', 'test')
            """
        )
        connection.execute(
            """
            INSERT INTO source_snapshots
            (snapshot_id, run_id, source_id, collected_at, local_path, file_hash, status)
            VALUES ('snapshot-1', 'run-1', 'source-1', 'now', 'fixture.csv', 'hash', 'success')
            """
        )
        connection.execute(
            """
            INSERT INTO source_records
            (source_record_id, source_id, snapshot_id, source_row_key, record_hash,
             raw_payload_json, first_seen_at, last_seen_at)
            VALUES ('record-1', 'source-1', 'snapshot-1', 'row-1', 'hash', '{}', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('athlete-1', 'Ana Silva', 'ANA SILVA', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO psr_responses
            (psr_id, athlete_id, source_record_id, response_date, raw_values_json, created_at)
            VALUES ('psr-1', 'athlete-1', 'record-1', '2099-01-01', '{}', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO data_quality_findings
            (finding_id, finding_type, entity_type, entity_id, severity, status,
             evidence_json, human_summary, created_at)
            VALUES ('finding-1', 'psr_invalid_or_future_date', 'psr_responses', 'psr-1',
                    'high', 'reviewed', '{"response_date":"2099-01-01"}',
                    'PSR com data ausente, invalida ou futura.', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO date_overrides
            (override_id, entity_type, entity_id, source_record_id, field_name, original_value,
             corrected_value, override_status, reason, reviewed_by, reviewed_at, finding_id)
            VALUES ('override-1', 'psr_responses', 'psr-1', 'record-1', 'response_date',
                    '2099-01-01', '2026-01-01', 'active', 'reviewed', 'Lucas', 'now', 'finding-1')
            """
        )
    connection.close()

    result = assess_phase9_readiness(tmp_path, database_path=db_path)
    checks = {check.name: check for check in result.checks}

    assert checks["date_reliability"].status == "ready"
    assert result.metrics["psr_responses_with_effective_date"] == 1
    assert result.metrics["active_date_overrides"] == 1
