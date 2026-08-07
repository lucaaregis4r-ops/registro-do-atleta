from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.quality.duplicates import build_duplicate_alerts


def test_duplicate_alerts_create_quality_findings_and_review_csv(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES
            ('athlete-1', 'Ana Silva', 'ANA SILVA', 'now', 'now'),
            ('athlete-2', 'Ana S.', 'ANA S', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO athlete_aliases
            (alias_id, athlete_id, alias_raw, alias_normalized, is_confirmed)
            VALUES
            ('alias-1', 'athlete-1', 'Ana Silva', 'ANA SILVA', 1),
            ('alias-2', 'athlete-2', 'Ana Silva', 'ANA SILVA', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO source_systems (source_id, source_type, name, domain, created_at)
            VALUES ('source-1', 'fixture', 'Fixture', 'test', 'now')
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
             raw_payload_json, first_seen_at, last_seen_at, is_current)
            VALUES
            ('record-1', 'source-1', 'snapshot-1', 'row-1', 'same-hash', '{}', 'now', 'now', 1),
            ('record-2', 'source-1', 'snapshot-1', 'row-2', 'same-hash', '{}', 'now', 'now', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO identity_candidates
            (candidate_id, source_record_id, name_raw, name_normalized, confidence, evidence_json, decision_status, created_at)
            VALUES
            ('candidate-1', 'record-1', 'Joao Teste', 'JOAO TESTE', 0, '{}', 'pending_review', 'now'),
            ('candidate-2', 'record-2', 'Joao Teste', 'JOAO TESTE', 0, '{}', 'pending_review', 'now')
            """
        )
    connection.close()

    result = build_duplicate_alerts(tmp_path, database_path=db_path)

    assert result.findings_created == 3
    assert result.alias_conflicts == 1
    assert result.pending_name_duplicates == 1
    assert result.source_record_duplicates == 1
    assert result.report_path.exists()
    assert result.review_path.exists()
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM data_quality_findings WHERE finding_type LIKE 'duplicate_%' AND status = 'open'").fetchone()[0] == 3


def test_duplicate_alerts_supersede_previous_duplicate_findings(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO data_quality_findings
            (finding_id, finding_type, entity_type, entity_id, severity, status,
             evidence_json, human_summary, created_at)
            VALUES ('finding-old', 'duplicate_alias_conflict', 'athlete_aliases', 'ANA',
                    'high', 'open', '{}', 'Duplicado antigo.', 'now')
            """
        )
    connection.close()

    result = build_duplicate_alerts(tmp_path, database_path=db_path)

    assert result.findings_created == 0
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT status FROM data_quality_findings WHERE finding_id = 'finding-old'").fetchone()[0] == "superseded"
