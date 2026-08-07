from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


@dataclass(frozen=True)
class ReviewProgressResult:
    report_path: Path
    json_path: Path
    pending_identity: int
    open_date_findings: int
    open_duplicate_findings: int
    reviewed_identity: int
    reviewed_dates: int
    reviewed_duplicates: int


def build_review_progress_report(root: Path, database_path: Path | None = None) -> ReviewProgressResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    report_dir = root / "data" / "reports" / "quality"
    report_dir.mkdir(parents=True, exist_ok=True)
    try:
        payload = _payload(connection)
    finally:
        connection.close()

    stamp = utc_now().replace(":", "").replace("+", "Z")
    report_path = report_dir / f"review-progress-{stamp}.md"
    json_path = report_dir / f"review-progress-{stamp}.json"
    report_path.write_text(_render_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = payload["summary"]
    return ReviewProgressResult(
        report_path=report_path,
        json_path=json_path,
        pending_identity=summary["pending_identity"],
        open_date_findings=summary["open_date_findings"],
        open_duplicate_findings=summary["open_duplicate_findings"],
        reviewed_identity=summary["reviewed_identity"],
        reviewed_dates=summary["reviewed_dates"],
        reviewed_duplicates=summary["reviewed_duplicates"],
    )


def build_review_progress_payload(database_path: Path) -> dict:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        return _payload(connection)
    finally:
        connection.close()


def _payload(connection: sqlite3.Connection) -> dict:
    summary = {
        "pending_identity": _scalar(connection, "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'"),
        "reviewed_identity": _scalar(connection, "SELECT COUNT(*) FROM identity_reviews"),
        "open_date_findings": _scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM data_quality_findings
            WHERE status = 'open'
              AND (finding_type LIKE '%date%' OR human_summary LIKE '%data%')
            """,
        ),
        "reviewed_dates": _scalar(connection, "SELECT COUNT(*) FROM date_quality_reviews"),
        "open_duplicate_findings": _scalar(
            connection,
            "SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open' AND finding_type LIKE 'duplicate_%'",
        ),
        "reviewed_duplicates": _scalar(connection, "SELECT COUNT(*) FROM duplicate_quality_reviews"),
    }
    return {
        "generated_at": utc_now(),
        "summary": summary,
        "identity_by_source": _rows(
            connection,
            """
            SELECT sr.source_id, COALESCE(ss.domain, 'unknown') domain, COUNT(*) pending
            FROM identity_candidates ic
            JOIN source_records sr ON sr.source_record_id = ic.source_record_id
            LEFT JOIN source_systems ss ON ss.source_id = sr.source_id
            WHERE ic.decision_status = 'pending_review'
            GROUP BY sr.source_id, ss.domain
            ORDER BY pending DESC, sr.source_id
            LIMIT 20
            """,
        ),
        "identity_by_domain": _rows(
            connection,
            """
            SELECT COALESCE(ss.domain, 'unknown') domain, COUNT(*) pending
            FROM identity_candidates ic
            JOIN source_records sr ON sr.source_record_id = ic.source_record_id
            LEFT JOIN source_systems ss ON ss.source_id = sr.source_id
            WHERE ic.decision_status = 'pending_review'
            GROUP BY ss.domain
            ORDER BY pending DESC, domain
            """,
        ),
        "date_findings_by_type": _rows(
            connection,
            """
            SELECT finding_type, severity, COUNT(*) open
            FROM data_quality_findings
            WHERE status = 'open'
              AND (finding_type LIKE '%date%' OR human_summary LIKE '%data%')
            GROUP BY finding_type, severity
            ORDER BY open DESC, finding_type
            """,
        ),
        "duplicate_findings_by_type": _rows(
            connection,
            """
            SELECT finding_type, severity, COUNT(*) open
            FROM data_quality_findings
            WHERE status = 'open'
              AND finding_type LIKE 'duplicate_%'
            GROUP BY finding_type, severity
            ORDER BY open DESC, finding_type
            """,
        ),
        "recent_reviews": {
            "identity": _rows(
                connection,
                """
                SELECT decision, reviewed_by, reviewed_at, COUNT(*) count
                FROM identity_reviews
                GROUP BY decision, reviewed_by, reviewed_at
                ORDER BY reviewed_at DESC
                LIMIT 10
                """,
            ),
            "dates": _rows(
                connection,
                """
                SELECT decision, reviewed_by, reviewed_at, COUNT(*) count
                FROM date_quality_reviews
                GROUP BY decision, reviewed_by, reviewed_at
                ORDER BY reviewed_at DESC
                LIMIT 10
                """,
            ),
            "duplicates": _rows(
                connection,
                """
                SELECT decision, reviewed_by, reviewed_at, COUNT(*) count
                FROM duplicate_quality_reviews
                GROUP BY decision, reviewed_by, reviewed_at
                ORDER BY reviewed_at DESC
                LIMIT 10
                """,
            ),
        },
    }


def _render_markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = [
        "# Progresso Das Revisoes Humanas",
        "",
        f"Gerado em UTC: `{payload['generated_at']}`",
        "",
        "## Resumo",
        "",
        f"- Identidades pendentes: `{summary['pending_identity']}`",
        f"- Identidades revisadas: `{summary['reviewed_identity']}`",
        f"- Achados de data abertos: `{summary['open_date_findings']}`",
        f"- Revisoes de data registradas: `{summary['reviewed_dates']}`",
        f"- Duplicatas abertas: `{summary['open_duplicate_findings']}`",
        f"- Revisoes de duplicata registradas: `{summary['reviewed_duplicates']}`",
        "",
        "## Identidade Por Dominio",
        "",
        "| Dominio | Pendentes |",
        "|---|---:|",
    ]
    lines.extend(f"| {row['domain']} | {row['pending']} |" for row in payload["identity_by_domain"])
    lines.extend(["", "## Identidade Por Fonte", "", "| Fonte | Dominio | Pendentes |", "|---|---|---:|"])
    lines.extend(f"| {row['source_id']} | {row['domain']} | {row['pending']} |" for row in payload["identity_by_source"])
    lines.extend(["", "## Datas Abertas", "", "| Tipo | Severidade | Abertos |", "|---|---|---:|"])
    lines.extend(f"| {row['finding_type']} | {row['severity']} | {row['open']} |" for row in payload["date_findings_by_type"])
    lines.extend(["", "## Duplicatas Abertas", "", "| Tipo | Severidade | Abertos |", "|---|---|---:|"])
    lines.extend(f"| {row['finding_type']} | {row['severity']} | {row['open']} |" for row in payload["duplicate_findings_by_type"])
    lines.extend(
        [
            "",
            "## Proxima Acao",
            "",
            "1. Usar a aba `Atletas` para localizar `athlete_id` confiavel.",
            "2. Aplicar decisoes pendentes na aba `Revisoes`.",
            "3. Registrar duplicatas na aba `Atletas` sem fundir atletas automaticamente.",
            "4. Reexecutar `data-readiness-report`, `duplicate-alerts` e este relatorio para acompanhar queda dos bloqueios.",
            "",
        ]
    )
    return "\n".join(lines)


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def _rows(connection: sqlite3.Connection, query: str) -> list[dict]:
    return [dict(row) for row in connection.execute(query).fetchall()]
