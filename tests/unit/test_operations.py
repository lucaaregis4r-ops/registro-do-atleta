from pathlib import Path
from types import SimpleNamespace

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.operations.backup import (
    backup_database,
    list_backups,
    prune_backups,
    restore_database,
    verify_database_integrity,
)
from registro_atleta.operations.lock import PipelineLock
from registro_atleta.operations.pipeline import run_operational_pipeline


def test_backup_database_returns_none_without_database(tmp_path: Path) -> None:
    assert backup_database(tmp_path / "missing.db", tmp_path) is None


def test_backup_database_copies_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "data" / "database" / "registro_atleta.db"
    database.parent.mkdir(parents=True)
    database.write_text("db", encoding="utf-8")

    backup = backup_database(database, tmp_path)

    assert backup is not None
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "db"


def test_backup_database_creates_consistent_sqlite_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes
            (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('athlete-1', 'Ana', 'ANA', 'now', 'now')
            """
        )

    backup = backup_database(database, tmp_path)
    connection.close()
    report = verify_database_integrity(backup)
    backup_connection = connect_database(backup)
    athlete_count = backup_connection.execute("SELECT COUNT(*) FROM athletes").fetchone()[0]
    backup_connection.close()

    assert report.ok is True
    assert athlete_count == 1


def test_prune_and_restore_backups(tmp_path: Path) -> None:
    database = tmp_path / "data" / "database" / "registro_atleta.db"
    database.parent.mkdir(parents=True)
    backups_dir = tmp_path / "data" / "backups"
    backups_dir.mkdir(parents=True)
    first = backups_dir / "registro_atleta-20260101T000000Z.db"
    second = backups_dir / "registro_atleta-20260102T000000Z.db"
    first.write_text("old", encoding="utf-8")
    second.write_text("new", encoding="utf-8")

    removed = prune_backups(tmp_path, keep_last=1)
    restore_database(list_backups(tmp_path)[0], database, verify=False)

    assert len(removed) == 1
    assert database.read_text(encoding="utf-8") == "new"


def test_restore_database_verifies_schema_after_copy(tmp_path: Path) -> None:
    backup = tmp_path / "data" / "backups" / "registro_atleta-20260101T000000Z.db"
    restored = tmp_path / "data" / "database" / "registro_atleta.db"
    backup.parent.mkdir(parents=True)
    connection = connect_database(backup)
    initialize_database(connection)
    connection.close()

    report = restore_database(backup, restored)

    assert report.ok is True
    assert report.integrity_check == "ok"
    assert report.missing_tables == ()
    assert report.table_counts["athletes"] == 0


def test_verify_database_integrity_reports_invalid_sqlite_file(tmp_path: Path) -> None:
    database = tmp_path / "data" / "database" / "registro_atleta.db"
    database.parent.mkdir(parents=True)
    database.write_text("not sqlite", encoding="utf-8")

    report = verify_database_integrity(database)

    assert report.ok is False
    assert report.integrity_check == "error"
    assert report.error_message is not None


def test_verify_database_integrity_releases_file_handle(tmp_path: Path) -> None:
    database = tmp_path / "registro_atleta.db"
    connection = connect_database(database)
    initialize_database(connection)
    connection.close()

    report = verify_database_integrity(database)
    database.unlink()

    assert report.ok is True
    assert not database.exists()


def test_pipeline_lock_blocks_second_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "data" / "locks" / "nightly.lock"

    with PipelineLock(lock_path):
        try:
            with PipelineLock(lock_path):
                raise AssertionError("second lock should not be acquired")
        except RuntimeError:
            pass

    assert not lock_path.exists()


def test_operational_pipeline_reports_degraded_when_a_source_fails(tmp_path: Path, monkeypatch) -> None:
    import registro_atleta.operations.pipeline as pipeline

    monkeypatch.setattr(pipeline, "backup_database", lambda database_path, root: None)
    monkeypatch.setattr(
        pipeline,
        "sync",
        lambda root, database_path: SimpleNamespace(
            errors=1,
            snapshots_saved=2,
            records_created=3,
            records_updated=0,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "build_identity",
        lambda root, database_path: SimpleNamespace(auto_matched=3, pending_review=0),
    )
    monkeypatch.setattr(
        pipeline,
        "build_domains",
        lambda root, database_path: SimpleNamespace(
            psr_created=3,
            psr_updated=0,
            physio_events_created=0,
            physio_events_updated=0,
            assessments_created=0,
            assessments_updated=0,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "build_alerts",
        lambda root, database_path: SimpleNamespace(
            baselines_created=0,
            alerts_created=0,
            quality_findings_created=0,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "build_nightly_briefing",
        lambda root, database_path: SimpleNamespace(
            status="success",
            main_items=0,
            appendix_items=0,
            markdown_path=tmp_path / "briefing.md",
        ),
    )

    result = run_operational_pipeline(tmp_path)

    assert result.status == "degraded"
    assert next(step for step in result.steps if step.name == "sync").status == "degraded"
