from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3


BACKUP_PATTERN = "registro_atleta-*.db"
REQUIRED_TABLES = {
    "source_systems",
    "pipeline_runs",
    "source_snapshots",
    "source_records",
    "athletes",
    "identity_candidates",
    "psr_responses",
    "physio_cases",
    "alerts",
    "data_quality_findings",
}


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@dataclass(frozen=True)
class DatabaseIntegrityReport:
    database_path: Path
    ok: bool
    integrity_check: str
    missing_tables: tuple[str, ...]
    table_counts: dict[str, int]
    error_message: str | None = None

    @property
    def status(self) -> str:
        return "ok" if self.ok else "failed"


def backup_database(database_path: Path, root: Path) -> Path | None:
    if not database_path.exists():
        return None
    backup_dir = root / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{database_path.stem}-{timestamp}{database_path.suffix}"
    try:
        with closing(sqlite3.connect(database_path, timeout=30.0)) as source:
            with closing(sqlite3.connect(backup_path, timeout=30.0)) as destination:
                source.backup(destination)
    except sqlite3.DatabaseError:
        # Keep compatibility with non-SQLite fixtures; real databases use the
        # transactional SQLite backup API above.
        backup_path.unlink(missing_ok=True)
        shutil.copy2(database_path, backup_path)
    return backup_path


def list_backups(root: Path) -> list[Path]:
    backup_dir = root / "data" / "backups"
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob(BACKUP_PATTERN), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)


def prune_backups(root: Path, keep_last: int = 10) -> list[Path]:
    backups = list_backups(root)
    if keep_last < 1:
        raise ValueError("keep_last deve ser >= 1")
    removed: list[Path] = []
    for backup in backups[keep_last:]:
        backup.unlink()
        removed.append(backup)
    return removed


def verify_database_integrity(database_path: Path, required_tables: set[str] | None = None) -> DatabaseIntegrityReport:
    required = required_tables or REQUIRED_TABLES
    if not database_path.exists():
        return DatabaseIntegrityReport(
            database_path=database_path,
            ok=False,
            integrity_check="missing",
            missing_tables=tuple(sorted(required)),
            table_counts={},
            error_message=f"Banco nao encontrado: {database_path}",
        )
    try:
        with closing(sqlite3.connect(database_path)) as connection:
            integrity_check = connection.execute("PRAGMA integrity_check").fetchone()[0]
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            existing_tables = {row[0] for row in table_rows}
            missing_tables = tuple(sorted(required - existing_tables))
            table_counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]
                for table in sorted(required & existing_tables)
            }
    except sqlite3.DatabaseError as exc:
        return DatabaseIntegrityReport(
            database_path=database_path,
            ok=False,
            integrity_check="error",
            missing_tables=tuple(sorted(required)),
            table_counts={},
            error_message=str(exc),
        )
    ok = integrity_check == "ok" and not missing_tables
    return DatabaseIntegrityReport(
        database_path=database_path,
        ok=ok,
        integrity_check=integrity_check,
        missing_tables=missing_tables,
        table_counts=table_counts,
        error_message=None if ok else "Falha na verificacao minima de integridade.",
    )


def restore_database(backup_path: Path, database_path: Path, verify: bool = True) -> DatabaseIntegrityReport:
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup nao encontrado: {backup_path}")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, database_path)
    if not verify:
        return DatabaseIntegrityReport(
            database_path=database_path,
            ok=True,
            integrity_check="not_checked",
            missing_tables=(),
            table_counts={},
        )
    return verify_database_integrity(database_path)
