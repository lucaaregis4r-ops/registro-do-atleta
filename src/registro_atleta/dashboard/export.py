from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.dashboard.macrocycle import build_macrocycle_payload
from registro_atleta.ingestion.snapshots import utc_now
from registro_atleta.quality.review_progress import build_review_progress_payload


@dataclass
class DashboardExportResult:
    output_path: Path
    athletes: int
    alerts_open: int
    quality_open: int


def build_dashboard_payload(database_path: Path) -> dict:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        payload = {
            "generated_at": utc_now(),
            "summary": {
                "athletes": _count(connection, "athletes"),
                "psr_responses": _count(connection, "psr_responses"),
                "physio_cases": _count(connection, "physio_cases"),
                "physical_assessments": _count(connection, "physical_assessments"),
                "alerts_open": _scalar(connection, "SELECT COUNT(*) FROM alerts WHERE status = 'open'"),
                "alert_episodes_active": _scalar(connection, "SELECT COUNT(*) FROM alert_episodes WHERE episode_status = 'active'"),
                "briefing_main_items": _scalar(connection, "SELECT COUNT(*) FROM report_items WHERE included_in_main_brief = 1 AND report_run_id = (SELECT report_run_id FROM report_runs WHERE report_type = 'nightly_briefing' ORDER BY generated_at DESC LIMIT 1)"),
                "briefing_appendix_items": _scalar(connection, "SELECT COUNT(*) FROM report_items WHERE included_in_main_brief = 0 AND report_run_id = (SELECT report_run_id FROM report_runs WHERE report_type = 'nightly_briefing' ORDER BY generated_at DESC LIMIT 1)"),
                "quality_open": _scalar(connection, "SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open'"),
                "identity_pending": _scalar(connection, "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'"),
                "literature_approved": _scalar(connection, "SELECT COUNT(*) FROM paper_topics WHERE human_status = 'approved'"),
            },
            "alerts_by_type": _rows(
                connection,
                """
                SELECT alert_type label, COUNT(*) value
                FROM alerts
                WHERE status = 'open'
                GROUP BY alert_type
                ORDER BY value DESC, label
                LIMIT 12
                """,
            ),
            "alerts_by_severity": _rows(
                connection,
                """
                SELECT severity label, COUNT(*) value
                FROM alerts
                WHERE status = 'open'
                GROUP BY severity
                ORDER BY value DESC, label
                """,
            ),
            "episodes_by_novelty": _rows(
                connection,
                """
                SELECT novelty_status label, COUNT(*) value
                FROM alert_episodes
                GROUP BY novelty_status
                ORDER BY value DESC, label
                """,
            ),
            "episodes_by_severity": _rows(
                connection,
                """
                SELECT current_severity label, COUNT(*) value
                FROM alert_episodes
                WHERE episode_status = 'active'
                GROUP BY current_severity
                ORDER BY value DESC, label
                """,
            ),
            "quality_by_type": _rows(
                connection,
                """
                SELECT finding_type label, COUNT(*) value
                FROM data_quality_findings
                WHERE status = 'open'
                GROUP BY finding_type
                ORDER BY value DESC, label
                LIMIT 12
                """,
            ),
            "recent_alerts": _rows(
                connection,
                """
                SELECT al.alert_type, al.severity, al.reference_date, al.human_summary,
                       at.canonical_name athlete_name
                FROM alerts al
                JOIN athletes at ON at.athlete_id = al.athlete_id
                WHERE al.status = 'open'
                ORDER BY al.created_at DESC
                LIMIT 25
                """,
            ),
            "latest_briefing_items": _rows(
                connection,
                """
                SELECT ri.display_order, ri.priority_bucket, ri.priority_score, ri.headline,
                       ri.included_in_main_brief, ri.episode_id, ri.alert_id, ri.finding_id,
                       rr.reference_date, rr.status report_status
                FROM report_items ri
                JOIN report_runs rr ON rr.report_run_id = ri.report_run_id
                WHERE ri.report_run_id = (
                    SELECT report_run_id
                    FROM report_runs
                    WHERE report_type = 'nightly_briefing'
                    ORDER BY generated_at DESC
                    LIMIT 1
                )
                ORDER BY ri.display_order
                LIMIT 50
                """,
            ),
            "alert_episodes": _rows(
                connection,
                """
                SELECT ae.episode_id, ae.alert_type, ae.episode_status, ae.novelty_status,
                       ae.current_severity, ae.priority_score, ae.last_seen_at,
                       at.canonical_name athlete_name
                FROM alert_episodes ae
                JOIN athletes at ON at.athlete_id = ae.athlete_id
                ORDER BY ae.priority_score DESC, ae.updated_at DESC
                LIMIT 50
                """,
            ),
            "review_progress": build_review_progress_payload(database_path),
            "macrocycle": build_macrocycle_payload(database_path),
        }
        return payload
    finally:
        connection.close()


def export_dashboard_data(root: Path, database_path: Path | None = None, output_path: Path | None = None) -> DashboardExportResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    output_path = output_path or root / "data" / "dashboard" / "dashboard-data.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_dashboard_payload(database_path)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return DashboardExportResult(
        output_path=output_path,
        athletes=int(payload["summary"]["athletes"]),
        alerts_open=int(payload["summary"]["alerts_open"]),
        quality_open=int(payload["summary"]["quality_open"]),
    )


def _count(connection: sqlite3.Connection, table: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    return connection.execute(query).fetchone()[0]


def _rows(connection: sqlite3.Connection, query: str) -> list[dict]:
    return [dict(row) for row in connection.execute(query).fetchall()]
