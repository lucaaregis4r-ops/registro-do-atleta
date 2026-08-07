from concurrent.futures import ThreadPoolExecutor

from registro_atleta.database.schema import (
    SCHEMA_VERSION,
    connect_database,
    initialize_database,
)


def test_initialize_database_is_safe_for_parallel_dashboard_reads(tmp_path):
    database_path = tmp_path / "registro_atleta.db"

    def initialize_and_count() -> tuple[int, int]:
        connection = connect_database(database_path)
        try:
            initialize_database(connection)
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            table_count = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
            return version, table_count
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: initialize_and_count(), range(16)))

    assert all(version == SCHEMA_VERSION for version, _ in results)
    assert all(table_count > 0 for _, table_count in results)


def test_initialize_database_skips_schema_writes_after_version_is_current(tmp_path):
    database_path = tmp_path / "registro_atleta.db"
    first_connection = connect_database(database_path)
    initialize_database(first_connection)
    first_connection.close()

    second_connection = connect_database(database_path)
    second_connection.execute("BEGIN")
    try:
        initialize_database(second_connection)
        assert second_connection.in_transaction
    finally:
        second_connection.rollback()
        second_connection.close()
