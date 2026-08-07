from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


@dataclass(frozen=True)
class DuplicateAlertResult:
    report_path: Path
    review_path: Path
    findings_created: int
    alias_conflicts: int
    pending_name_duplicates: int
    source_record_duplicates: int


def build_duplicate_alerts(root: Path, database_path: Path | None = None) -> DuplicateAlertResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    report_dir = root / "data" / "reports" / "quality"
    review_dir = root / "data" / "reviews"
    report_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    alias_conflicts = _alias_conflicts(connection)
    pending_duplicates = _pending_name_duplicates(connection)
    source_duplicates = _source_record_duplicates(connection)
    findings_created = 0
    now = utc_now()
    with connection:
        connection.execute(
            "UPDATE data_quality_findings SET status = 'superseded' WHERE status = 'open' AND finding_type LIKE 'duplicate_%'"
        )
        for row in alias_conflicts:
            findings_created += _insert_finding(
                connection,
                finding_type="duplicate_alias_conflict",
                entity_type="athlete_aliases",
                entity_id=row["alias_normalized"],
                severity="high",
                summary=f"Alias confirmado aparece ligado a {row['athlete_count']} atletas.",
                evidence={
                    "alias_normalized": row["alias_normalized"],
                    "athlete_count": row["athlete_count"],
                    "athlete_ids": row["athlete_ids"].split("|") if row["athlete_ids"] else [],
                    "alias_examples": row["alias_examples"].split("|") if row["alias_examples"] else [],
                },
                now=now,
            )
        for row in pending_duplicates:
            findings_created += _insert_finding(
                connection,
                finding_type="duplicate_pending_identity_name",
                entity_type="identity_candidates",
                entity_id=row["name_normalized"],
                severity="medium",
                summary=f"Nome pendente repetido em {row['candidate_count']} candidatos de identidade.",
                evidence={
                    "name_normalized": row["name_normalized"],
                    "candidate_count": row["candidate_count"],
                    "source_count": row["source_count"],
                    "candidate_ids": row["candidate_ids"].split("|") if row["candidate_ids"] else [],
                    "source_record_ids": row["source_record_ids"].split("|") if row["source_record_ids"] else [],
                },
                now=now,
            )
        for row in source_duplicates:
            findings_created += _insert_finding(
                connection,
                finding_type="duplicate_current_source_record_hash",
                entity_type="source_records",
                entity_id=row["record_hash"],
                severity="low",
                summary=f"Hash de registro atual repetido {row['record_count']} vezes na fonte {row['source_id']}.",
                evidence={
                    "source_id": row["source_id"],
                    "record_hash": row["record_hash"],
                    "record_count": row["record_count"],
                    "source_record_ids": row["source_record_ids"].split("|") if row["source_record_ids"] else [],
                },
                now=now,
            )

    review_path = review_dir / "duplicate_alerts_review.csv"
    _write_review_csv(review_path, alias_conflicts, pending_duplicates, source_duplicates)
    report_path = report_dir / f"duplicate-alerts-{utc_now().replace(':', '').replace('+', 'Z')}.md"
    report_path.write_text(
        _render_markdown(alias_conflicts, pending_duplicates, source_duplicates, review_path),
        encoding="utf-8",
    )
    connection.close()
    return DuplicateAlertResult(
        report_path=report_path,
        review_path=review_path,
        findings_created=findings_created,
        alias_conflicts=len(alias_conflicts),
        pending_name_duplicates=len(pending_duplicates),
        source_record_duplicates=len(source_duplicates),
    )


def _alias_conflicts(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT alias_normalized,
               COUNT(DISTINCT athlete_id) athlete_count,
               GROUP_CONCAT(DISTINCT athlete_id) athlete_ids,
               GROUP_CONCAT(DISTINCT alias_raw) alias_examples
        FROM athlete_aliases
        WHERE is_confirmed = 1
        GROUP BY alias_normalized
        HAVING COUNT(DISTINCT athlete_id) > 1
        ORDER BY athlete_count DESC, alias_normalized
        """
    ).fetchall()


def _pending_name_duplicates(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT name_normalized,
               COUNT(*) candidate_count,
               COUNT(DISTINCT source_record_id) source_count,
               GROUP_CONCAT(candidate_id, '|') candidate_ids,
               GROUP_CONCAT(source_record_id, '|') source_record_ids
        FROM identity_candidates
        WHERE decision_status = 'pending_review'
        GROUP BY name_normalized
        HAVING COUNT(*) > 1
        ORDER BY candidate_count DESC, name_normalized
        """
    ).fetchall()


def _source_record_duplicates(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT source_id, record_hash, COUNT(*) record_count,
               GROUP_CONCAT(source_record_id, '|') source_record_ids
        FROM source_records
        WHERE is_current = 1
        GROUP BY source_id, record_hash
        HAVING COUNT(*) > 1
        ORDER BY record_count DESC, source_id
        LIMIT 100
        """
    ).fetchall()


def _insert_finding(
    connection: sqlite3.Connection,
    finding_type: str,
    entity_type: str,
    entity_id: str,
    severity: str,
    summary: str,
    evidence: dict,
    now: str,
) -> int:
    connection.execute(
        """
        INSERT INTO data_quality_findings
        (finding_id, finding_type, entity_type, entity_id, severity, status, evidence_json, human_summary, created_at)
        VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (
            uuid4().hex,
            finding_type,
            entity_type,
            entity_id,
            severity,
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            summary,
            now,
        ),
    )
    return 1


def _write_review_csv(
    path: Path,
    alias_conflicts: list[sqlite3.Row],
    pending_duplicates: list[sqlite3.Row],
    source_duplicates: list[sqlite3.Row],
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["finding_type", "severity", "entity_key", "count", "decision", "notes", "evidence"])
        for row in alias_conflicts:
            writer.writerow([
                "duplicate_alias_conflict",
                "high",
                row["alias_normalized"],
                row["athlete_count"],
                "",
                "",
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
            ])
        for row in pending_duplicates:
            writer.writerow([
                "duplicate_pending_identity_name",
                "medium",
                row["name_normalized"],
                row["candidate_count"],
                "",
                "",
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
            ])
        for row in source_duplicates:
            writer.writerow([
                "duplicate_current_source_record_hash",
                "low",
                f"{row['source_id']}:{row['record_hash']}",
                row["record_count"],
                "",
                "",
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
            ])


def _render_markdown(
    alias_conflicts: list[sqlite3.Row],
    pending_duplicates: list[sqlite3.Row],
    source_duplicates: list[sqlite3.Row],
    review_path: Path,
) -> str:
    lines = [
        "# Alertas De Duplicacao",
        "",
        f"Gerado em UTC: `{utc_now()}`",
        "",
        "## Resumo",
        "",
        f"- Conflitos de alias confirmado: `{len(alias_conflicts)}`",
        f"- Nomes pendentes repetidos: `{len(pending_duplicates)}`",
        f"- Hashes atuais repetidos por fonte: `{len(source_duplicates)}`",
        f"- Fila de revisao: `{review_path}`",
        "",
        "## Top Duplicidades",
        "",
        "| Tipo | Chave | Total |",
        "|---|---|---:|",
    ]
    for row in alias_conflicts[:10]:
        lines.append(f"| alias_confirmado | {row['alias_normalized']} | {row['athlete_count']} |")
    for row in pending_duplicates[:10]:
        lines.append(f"| identidade_pendente | {row['name_normalized']} | {row['candidate_count']} |")
    for row in source_duplicates[:10]:
        lines.append(f"| registro_fonte | {row['source_id']} | {row['record_count']} |")
    if not alias_conflicts and not pending_duplicates and not source_duplicates:
        lines.append("| sem_duplicidade | - | 0 |")
    lines.extend(
        [
            "",
            "## Observacao",
            "",
            "Estes alertas nao fundem atletas nem alteram fontes brutas. Eles apenas criam achados auditaveis para revisao humana.",
            "",
        ]
    )
    return "\n".join(lines)
