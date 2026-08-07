from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from uuid import uuid4

from registro_atleta import __version__
from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.records import canonical_json, file_hash, read_records
from registro_atleta.ingestion.snapshots import collect_snapshot, utc_now
from registro_atleta.ingestion.sources import SourceConfig, default_sources


@dataclass
class SyncResult:
    run_id: str
    sources_checked: int = 0
    snapshots_saved: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_unchanged: int = 0
    errors: int = 0
    report_path: Path | None = None


def sync(root: Path, database_path: Path | None = None, sources: list[SourceConfig] | None = None) -> SyncResult:
    run_id = uuid4().hex
    started_at = utc_now()
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    sources = sources or default_sources(root)
    enabled_sources = [source for source in sources if source.enabled]

    connection = connect_database(database_path)
    initialize_database(connection)
    result = SyncResult(run_id=run_id, sources_checked=len(enabled_sources))

    with connection:
        connection.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, status, code_version)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, started_at, "running", __version__),
        )
        for source in enabled_sources:
            _upsert_source(connection, source, started_at)

    for source in enabled_sources:
        try:
            snapshot_path = collect_snapshot(source, run_id, root)
            snapshot_hash = file_hash(snapshot_path)
            records = read_records(snapshot_path, source.source_type)
            snapshot_id = uuid4().hex
            collected_at = utc_now()
            with connection:
                connection.execute(
                    """
                    INSERT INTO source_snapshots
                    (snapshot_id, run_id, source_id, collected_at, local_path, file_hash, row_count, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        run_id,
                        source.source_id,
                        collected_at,
                        str(snapshot_path),
                        snapshot_hash,
                        len(records),
                        "collected",
                    ),
                )
                for record in records:
                    change = _stage_record(connection, run_id, snapshot_id, source.source_id, record, collected_at)
                    if change == "created":
                        result.records_created += 1
                    elif change == "updated":
                        result.records_updated += 1
                    else:
                        result.records_unchanged += 1
            result.snapshots_saved += 1
        except Exception:  # noqa: BLE001 - pipeline records failure and continues with other sources.
            result.errors += 1

    finished_at = utc_now()
    status = "success" if result.errors == 0 else "degraded"
    with connection:
        connection.execute(
            """
            UPDATE pipeline_runs
            SET finished_at = ?, status = ?, records_created = ?, records_updated = ?,
                records_unchanged = ?, errors = ?
            WHERE run_id = ?
            """,
            (
                finished_at,
                status,
                result.records_created,
                result.records_updated,
                result.records_unchanged,
                result.errors,
                run_id,
            ),
        )

    result.report_path = _write_report(root, result, database_path, status)
    connection.close()
    return result


def _upsert_source(connection: sqlite3.Connection, source: SourceConfig, created_at: str) -> None:
    connection.execute(
        """
        INSERT INTO source_systems (source_id, source_type, name, url, domain, enabled, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            source_type = excluded.source_type,
            name = excluded.name,
            url = excluded.url,
            domain = excluded.domain,
            enabled = excluded.enabled
        """,
        (
            source.source_id,
            source.source_type,
            source.name,
            source.url,
            source.domain,
            1 if source.enabled else 0,
            created_at,
        ),
    )


def _stage_record(
    connection: sqlite3.Connection,
    run_id: str,
    snapshot_id: str,
    source_id: str,
    record,
    staged_at: str,
) -> str:
    payload_json = canonical_json(record.payload)
    staging_id = uuid4().hex
    connection.execute(
        """
        INSERT INTO staging_records
        (staging_id, run_id, snapshot_id, source_id, source_row_key, record_hash, payload_json, staged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (staging_id, run_id, snapshot_id, source_id, record.source_row_key, record.record_hash, payload_json, staged_at),
    )

    existing = connection.execute(
        """
        SELECT source_record_id, record_hash
        FROM source_records
        WHERE source_id = ? AND source_row_key = ? AND is_current = 1
        ORDER BY first_seen_at DESC
        LIMIT 1
        """,
        (source_id, record.source_row_key),
    ).fetchone()

    if existing and existing["record_hash"] == record.record_hash:
        connection.execute(
            """
            UPDATE source_records
            SET last_seen_at = ?, snapshot_id = ?
            WHERE source_record_id = ?
            """,
            (staged_at, snapshot_id, existing["source_record_id"]),
        )
        return "unchanged"

    if existing:
        connection.execute(
            "UPDATE source_records SET is_current = 0, last_seen_at = ? WHERE source_record_id = ?",
            (staged_at, existing["source_record_id"]),
        )

    connection.execute(
        """
        INSERT INTO source_records
        (source_record_id, source_id, snapshot_id, source_row_key, record_hash, raw_payload_json,
         first_seen_at, last_seen_at, is_current)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (uuid4().hex, source_id, snapshot_id, record.source_row_key, record.record_hash, payload_json, staged_at, staged_at),
    )
    return "updated" if existing else "created"


def _write_report(root: Path, result: SyncResult, database_path: Path, status: str) -> Path:
    report_dir = root / "data" / "reports" / "runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{result.run_id}.md"
    report = {
        "run_id": result.run_id,
        "status": status,
        "sources_checked": result.sources_checked,
        "snapshots_saved": result.snapshots_saved,
        "records_created": result.records_created,
        "records_updated": result.records_updated,
        "records_unchanged": result.records_unchanged,
        "errors": result.errors,
        "database": str(database_path),
    }
    lines = ["# Relatorio De Sincronizacao", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in report.items())
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
