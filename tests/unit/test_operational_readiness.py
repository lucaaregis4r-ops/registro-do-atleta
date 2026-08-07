from pathlib import Path

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.operations.backup import backup_database
from registro_atleta.operations.readiness import build_operational_readiness_report


def _database_with_backup(tmp_path: Path) -> Path:
    database_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    connection.close()
    backup_database(database_path, tmp_path)
    return database_path


def test_operational_readiness_rehearses_restore_without_touching_database(tmp_path: Path) -> None:
    database_path = _database_with_backup(tmp_path)
    original_size = database_path.stat().st_size

    result = build_operational_readiness_report(
        tmp_path,
        database_path=database_path,
        scheduler_probe=lambda name: (True, f"tarefa encontrada: {name}"),
    )

    assert result.status == "success"
    assert all(check.status == "ready" for check in result.checks)
    assert database_path.stat().st_size == original_size
    assert result.report_path.exists()
    assert list((tmp_path / "data" / "restore-tests").iterdir()) == []


def test_operational_readiness_reports_missing_scheduler_as_degraded(tmp_path: Path) -> None:
    database_path = _database_with_backup(tmp_path)

    result = build_operational_readiness_report(
        tmp_path,
        database_path=database_path,
        scheduler_probe=lambda name: (False, f"tarefa ausente: {name}"),
    )

    assert result.status == "degraded"
    scheduler = next(check for check in result.checks if check.name == "windows_scheduler")
    assert scheduler.status == "warning"


def test_operational_readiness_accepts_manual_policy(tmp_path: Path) -> None:
    database_path = _database_with_backup(tmp_path)

    result = build_operational_readiness_report(
        tmp_path,
        database_path=database_path,
        scheduler_required=False,
    )

    assert result.status == "success"
    scheduler = next(check for check in result.checks if check.name == "windows_scheduler")
    assert "manual" in scheduler.detail
