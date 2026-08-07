from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.identity.pipeline import build_identity


def test_build_identity_creates_seed_athlete_and_auto_candidate(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO source_systems (source_id, source_type, name, domain, enabled, created_at)
            VALUES ('historical_registro_atletas_demo', 'local_xlsx', 'seed', 'seed', 1, 'now')
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
            VALUES ('snap', 'run', 'historical_registro_atletas_demo', 'now', 'x', 'h', 1, 'ok')
            """
        )
        connection.execute(
            """
            INSERT INTO source_records
            (source_record_id, source_id, snapshot_id, source_row_key, record_hash, raw_payload_json,
             first_seen_at, last_seen_at, is_current)
            VALUES
            ('seed-record', 'historical_registro_atletas_demo', 'snap', 'xlsx:Registro_Unificado:row:2',
             'h1', '{"sheet":"Registro_Unificado","values":["ATH-0001","Ana Silva","ANA SILVA","Basquete","SUB 15"]}',
             'now', 'now', 1),
            ('psr-header', 'historical_registro_atletas_demo', 'snap', 'xlsx:Respostas:row:1',
             'h0', '{"sheet":"Respostas","values":["NOME","CATEGORIA"]}',
             'now', 'now', 1),
            ('psr-record', 'historical_registro_atletas_demo', 'snap', 'xlsx:Respostas:row:2',
             'h2', '{"sheet":"Respostas","values":["Ana Silva","SUB 15"]}',
             'now', 'now', 1)
            """
        )
    connection.close()

    result = build_identity(tmp_path, database_path=db_path)

    assert result.athletes_created == 1
    assert result.auto_matched >= 1
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM athletes").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM identity_candidates").fetchone()[0] >= 1
