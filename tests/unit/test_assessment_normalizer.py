from pathlib import Path

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.domains.assessments.normalizer import build_physical_assessments


def test_build_physical_assessments_from_identity_seed_occurrences(tmp_path: Path) -> None:
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
            VALUES ('snap', 'run', 'historical_registro_atletas_demo', 'now', 'x', 'h', 2, 'ok')
            """
        )
        connection.execute(
            """
            INSERT INTO source_records
            (source_record_id, source_id, snapshot_id, source_row_key, record_hash, raw_payload_json,
             first_seen_at, last_seen_at, is_current)
            VALUES
            ('header', 'historical_registro_atletas_demo', 'snap', 'xlsx:Ocorrencias_por_Fonte:row:1',
             'h1', '{"sheet":"Ocorrencias_por_Fonte","row_number":1,"values":["ID_Atleta","Tipo","Modalidade","Categoria","Altura","Massa corporal [kg]"]}',
             'now', 'now', 1),
            ('occurrence', 'historical_registro_atletas_demo', 'snap', 'xlsx:Ocorrencias_por_Fonte:row:2',
             'h2', '{"sheet":"Ocorrencias_por_Fonte","row_number":2,"values":["ATH-0001","Caracterização","Basquete","SUB 15","180","70"]}',
             'now', 'now', 1)
            """
        )

    result = build_physical_assessments(connection)

    assert result.assessments_created == 1
    assert result.metrics_created == 2
