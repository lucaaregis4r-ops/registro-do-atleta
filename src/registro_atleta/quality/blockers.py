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
class DataReadinessResult:
    report_path: Path
    identity_review_path: Path
    date_review_path: Path
    pending_identity: int
    date_findings: int
    open_quality_findings: int


@dataclass(frozen=True)
class DateReviewImportResult:
    applied_reviews: int = 0
    skipped_rows: int = 0
    invalid_rows: int = 0
    blocked_reason: str | None = None


@dataclass(frozen=True)
class DateReviewResult:
    finding_id: str
    status: str
    audit_id: str


def build_data_readiness_report(root: Path, database_path: Path | None = None) -> DataReadinessResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    report_dir = root / "data" / "reports" / "quality"
    review_dir = root / "data" / "reviews"
    report_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    pending_identity_rows = _pending_identity_rows(connection)
    date_rows = _date_quality_rows(connection)
    source_summary = _pending_identity_by_source(connection)
    quality_summary = _quality_summary(connection)

    identity_review_path = review_dir / "identity_pending_enriched.csv"
    date_review_path = review_dir / "date_quality_review.csv"
    _write_identity_review_csv(identity_review_path, pending_identity_rows)
    _write_date_review_csv(date_review_path, date_rows)

    report_path = report_dir / f"data-readiness-{utc_now().replace(':', '').replace('+', 'Z')}.md"
    report_path.write_text(
        _render_markdown(
            pending_identity_rows=pending_identity_rows,
            date_rows=date_rows,
            source_summary=source_summary,
            quality_summary=quality_summary,
            identity_review_path=identity_review_path,
            date_review_path=date_review_path,
        ),
        encoding="utf-8",
    )
    result = DataReadinessResult(
        report_path=report_path,
        identity_review_path=identity_review_path,
        date_review_path=date_review_path,
        pending_identity=len(pending_identity_rows),
        date_findings=len(date_rows),
        open_quality_findings=sum(row["count"] for row in quality_summary),
    )
    connection.close()
    return result


def _pending_identity_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT ic.candidate_id, ic.source_record_id, sr.source_id, ss.domain, ic.name_raw,
               ic.name_normalized, ic.sport, ic.category, ic.confidence, ic.evidence_json,
               sr.source_row_key, sr.last_seen_at
        FROM identity_candidates ic
        JOIN source_records sr ON sr.source_record_id = ic.source_record_id
        LEFT JOIN source_systems ss ON ss.source_id = sr.source_id
        WHERE ic.decision_status = 'pending_review'
        ORDER BY ss.domain, sr.source_id, ic.name_normalized, ic.candidate_id
        """
    ).fetchall()


def _pending_identity_by_source(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT sr.source_id, COALESCE(ss.domain, 'unknown') domain, COUNT(*) count
        FROM identity_candidates ic
        JOIN source_records sr ON sr.source_record_id = ic.source_record_id
        LEFT JOIN source_systems ss ON ss.source_id = sr.source_id
        WHERE ic.decision_status = 'pending_review'
        GROUP BY sr.source_id, ss.domain
        ORDER BY count DESC, sr.source_id
        """
    ).fetchall()


def _date_quality_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT dq.finding_id, dq.finding_type, dq.entity_type, dq.entity_id, dq.severity,
               dq.evidence_json, dq.human_summary, dq.created_at,
               p.athlete_id, at.canonical_name, p.source_record_id, sr.source_id, sr.source_row_key
        FROM data_quality_findings dq
        LEFT JOIN psr_responses p ON p.psr_id = dq.entity_id
        LEFT JOIN athletes at ON at.athlete_id = p.athlete_id
        LEFT JOIN source_records sr ON sr.source_record_id = p.source_record_id
        WHERE dq.status = 'open'
          AND (dq.finding_type LIKE '%date%' OR dq.human_summary LIKE '%data%')
        ORDER BY dq.severity DESC, dq.finding_type, dq.entity_id
        """
    ).fetchall()


def _quality_summary(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT finding_type, severity, COUNT(*) count
        FROM data_quality_findings
        WHERE status = 'open'
        GROUP BY finding_type, severity
        ORDER BY count DESC, finding_type, severity
        """
    ).fetchall()


def _write_identity_review_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "candidate_id",
                "source_record_id",
                "source_id",
                "domain",
                "name_raw",
                "name_normalized",
                "sport",
                "category",
                "confidence",
                "decision",
                "selected_athlete_id",
                "notes",
                "source_row_key",
                "evidence_json",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["candidate_id"],
                    row["source_record_id"],
                    row["source_id"],
                    row["domain"] or "",
                    row["name_raw"],
                    row["name_normalized"],
                    row["sport"] or "",
                    row["category"] or "",
                    row["confidence"],
                    "",
                    "",
                    "",
                    row["source_row_key"],
                    row["evidence_json"],
                ]
            )


def _write_date_review_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "finding_id",
                "finding_type",
                "severity",
                "entity_type",
                "entity_id",
                "athlete_id",
                "athlete_name",
                "source_record_id",
                "source_id",
                "source_row_key",
                "current_value",
                "decision",
                "corrected_date",
                "notes",
                "evidence_json",
            ]
        )
        for row in rows:
            evidence = _json(row["evidence_json"])
            writer.writerow(
                [
                    row["finding_id"],
                    row["finding_type"],
                    row["severity"],
                    row["entity_type"],
                    row["entity_id"] or "",
                    row["athlete_id"] or "",
                    row["canonical_name"] or "",
                    row["source_record_id"] or "",
                    row["source_id"] or "",
                    row["source_row_key"] or "",
                    evidence.get("response_date", ""),
                    "",
                    "",
                    "",
                    row["evidence_json"],
                ]
            )


def _render_markdown(
    pending_identity_rows: list[sqlite3.Row],
    date_rows: list[sqlite3.Row],
    source_summary: list[sqlite3.Row],
    quality_summary: list[sqlite3.Row],
    identity_review_path: Path,
    date_review_path: Path,
) -> str:
    lines = [
        "# Data Readiness - Identidade E Datas",
        "",
        f"Gerado em UTC: `{utc_now()}`",
        "",
        "## Resumo",
        "",
        f"- Identidades pendentes: `{len(pending_identity_rows)}`",
        f"- Achados de data abertos: `{len(date_rows)}`",
        f"- Fila identidade enriquecida: `{identity_review_path}`",
        f"- Fila datas: `{date_review_path}`",
        "",
        "## Identidade Por Fonte",
        "",
        "| Fonte | Dominio | Pendentes |",
        "|---|---|---:|",
    ]
    lines.extend(f"| {row['source_id']} | {row['domain']} | {row['count']} |" for row in source_summary)
    lines.extend(["", "## Qualidade Aberta", "", "| Achado | Severidade | Total |", "|---|---|---:|"])
    lines.extend(f"| {row['finding_type']} | {row['severity']} | {row['count']} |" for row in quality_summary)
    lines.extend(
        [
            "",
            "## Proxima Acao Recomendada",
            "",
            "1. Revisar `identity_pending_enriched.csv` e preencher `decision`, `selected_athlete_id` e `notes`.",
            "2. Aplicar decisoes com `import-identity-reviews --confirm --reviewed-by \"Nome\"`.",
            "3. Revisar `date_quality_review.csv` sem alterar fontes brutas.",
            "4. Reconstruir dominios, alertas e briefing depois das decisoes humanas.",
            "5. Aplicar decisoes de data com `import-date-reviews --confirm --reviewed-by \"Nome\"` quando a fila estiver revisada.",
            "",
        ]
    )
    return "\n".join(lines)


def _json(value: str) -> dict:
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {"value": loaded}
    except json.JSONDecodeError:
        return {"raw": value}


def import_date_reviews(
    csv_path: Path,
    database_path: Path,
    reviewed_by: str,
    confirm: bool,
) -> DateReviewImportResult:
    if not confirm:
        return DateReviewImportResult(blocked_reason="Importacao bloqueada: use --confirm para aplicar decisoes de data.")
    if not csv_path.exists():
        return DateReviewImportResult(blocked_reason=f"Arquivo nao encontrado: {csv_path}")

    connection = connect_database(database_path)
    initialize_database(connection)
    applied = 0
    skipped = 0
    invalid = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        with connection:
            for row in reader:
                decision = (row.get("decision") or "").strip()
                if not decision:
                    skipped += 1
                    continue
                if decision not in {"use_corrected_date", "exclude_from_temporal", "keep_as_is"}:
                    invalid += 1
                    continue
                corrected = (row.get("corrected_date") or "").strip() or None
                if decision == "use_corrected_date" and not _valid_iso_date(corrected):
                    invalid += 1
                    continue
                finding_id = (row.get("finding_id") or "").strip()
                finding = connection.execute(
                    "SELECT * FROM data_quality_findings WHERE finding_id = ?",
                    (finding_id,),
                ).fetchone()
                if finding is None:
                    invalid += 1
                    continue
                evidence = _json(finding["evidence_json"])
                original = (row.get("current_value") or evidence.get("response_date") or "").strip()
                entity_type = (row.get("entity_type") or finding["entity_type"]).strip()
                entity_id = (row.get("entity_id") or finding["entity_id"] or "").strip()
                source_record_id = (row.get("source_record_id") or "").strip() or _source_record_for_entity(connection, entity_type, entity_id)
                notes = (row.get("notes") or "").strip() or None
                review_id = uuid4().hex
                connection.execute(
                    """
                    INSERT INTO date_quality_reviews
                    (review_id, finding_id, entity_type, entity_id, source_record_id, decision,
                     original_value, corrected_date, reviewed_by, reviewed_at, notes, evidence_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        finding_id,
                        entity_type,
                        entity_id or None,
                        source_record_id,
                        decision,
                        original,
                        corrected,
                        reviewed_by,
                        utc_now(),
                        notes,
                        finding["evidence_json"],
                    ),
                )
                if decision in {"use_corrected_date", "exclude_from_temporal"}:
                    _upsert_date_override(
                        connection,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        source_record_id=source_record_id,
                        original_value=original,
                        corrected_value=corrected,
                        status="active" if decision == "use_corrected_date" else "excluded",
                        reason=notes or decision,
                        reviewed_by=reviewed_by,
                        finding_id=finding_id,
                    )
                if decision in {"use_corrected_date", "exclude_from_temporal", "keep_as_is"}:
                    connection.execute(
                        "UPDATE data_quality_findings SET status = 'reviewed' WHERE finding_id = ?",
                        (finding_id,),
                    )
                applied += 1
    connection.close()
    return DateReviewImportResult(applied_reviews=applied, skipped_rows=skipped, invalid_rows=invalid)


def list_date_review_items(database_path: Path, limit: int = 50, offset: int = 0) -> list[dict]:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        rows = _date_quality_rows(connection)
        sliced = rows[max(0, offset) : max(0, offset) + max(1, min(limit, 200))]
        return [dict(row) for row in sliced]
    finally:
        connection.close()


def apply_date_review(
    database_path: Path,
    finding_id: str,
    decision: str,
    reviewed_by: str,
    corrected_date: str | None = None,
    notes: str | None = None,
) -> DateReviewResult:
    decision = (decision or "").strip()
    reviewed_by = (reviewed_by or "").strip()
    if not reviewed_by:
        raise ValueError("reviewed_by e obrigatorio")
    if decision not in {"use_corrected_date", "exclude_from_temporal", "keep_as_is"}:
        raise ValueError("decisao de data invalida")
    if decision == "use_corrected_date" and not _valid_iso_date(corrected_date):
        raise ValueError("corrected_date deve estar em YYYY-MM-DD para use_corrected_date")

    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        finding = connection.execute(
            "SELECT * FROM data_quality_findings WHERE finding_id = ?",
            (finding_id,),
        ).fetchone()
        if finding is None:
            raise ValueError("finding_id nao encontrado")
        evidence = _json(finding["evidence_json"])
        entity_type = finding["entity_type"]
        entity_id = finding["entity_id"] or ""
        source_record_id = _source_record_for_entity(connection, entity_type, entity_id)
        original = str(evidence.get("response_date") or "")
        review_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO date_quality_reviews
            (review_id, finding_id, entity_type, entity_id, source_record_id, decision,
             original_value, corrected_date, reviewed_by, reviewed_at, notes, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                finding_id,
                entity_type,
                entity_id or None,
                source_record_id,
                decision,
                original,
                corrected_date,
                reviewed_by,
                utc_now(),
                notes,
                finding["evidence_json"],
            ),
        )
        if decision in {"use_corrected_date", "exclude_from_temporal"}:
            _upsert_date_override(
                connection,
                entity_type=entity_type,
                entity_id=entity_id,
                source_record_id=source_record_id,
                original_value=original,
                corrected_value=corrected_date,
                status="active" if decision == "use_corrected_date" else "excluded",
                reason=notes or decision,
                reviewed_by=reviewed_by,
                finding_id=finding_id,
            )
        connection.execute("UPDATE data_quality_findings SET status = 'reviewed' WHERE finding_id = ?", (finding_id,))
    connection.close()
    return DateReviewResult(finding_id=finding_id, status="reviewed", audit_id=review_id)


def _valid_iso_date(value: str | None) -> bool:
    if not value:
        return False
    parts = value.split("-")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return False
    year, month, day = [int(part) for part in parts]
    return 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31


def _source_record_for_entity(connection: sqlite3.Connection, entity_type: str, entity_id: str) -> str | None:
    if entity_type == "psr_responses" and entity_id:
        row = connection.execute("SELECT source_record_id FROM psr_responses WHERE psr_id = ?", (entity_id,)).fetchone()
        return row["source_record_id"] if row else None
    return None


def _upsert_date_override(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    source_record_id: str | None,
    original_value: str,
    corrected_value: str | None,
    status: str,
    reason: str,
    reviewed_by: str,
    finding_id: str,
) -> None:
    override_id = uuid4().hex
    connection.execute(
        """
        INSERT INTO date_overrides
        (override_id, entity_type, entity_id, source_record_id, field_name, original_value,
         corrected_value, override_status, reason, reviewed_by, reviewed_at, finding_id)
        VALUES (?, ?, ?, ?, 'response_date', ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id, field_name) DO UPDATE SET
            source_record_id = excluded.source_record_id,
            original_value = excluded.original_value,
            corrected_value = excluded.corrected_value,
            override_status = excluded.override_status,
            reason = excluded.reason,
            reviewed_by = excluded.reviewed_by,
            reviewed_at = excluded.reviewed_at,
            finding_id = excluded.finding_id
        """,
        (
            override_id,
            entity_type,
            entity_id,
            source_record_id,
            original_value,
            corrected_value,
            status,
            reason,
            reviewed_by,
            utc_now(),
            finding_id,
        ),
    )
