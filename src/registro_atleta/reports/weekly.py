from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


@dataclass
class WeeklyReportResult:
    report_path: Path
    alerts_count: int
    pending_identity_count: int
    quality_count: int


def build_weekly_report(root: Path, database_path: Path | None = None) -> WeeklyReportResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    report_dir = root / "data" / "reports" / "weekly"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"weekly-{utc_now().replace(':', '').replace('+', 'Z')}.md"

    alert_rows = _fetchall(
        connection,
        """
        SELECT a.alert_type, a.severity, COUNT(*) count
        FROM alerts a
        WHERE a.status = 'open'
        GROUP BY a.alert_type, a.severity
        ORDER BY a.alert_type, a.severity
        """,
    )
    top_alerts = _fetchall(
        connection,
        """
        SELECT al.athlete_id, at.canonical_name, COUNT(*) count
        FROM alerts al
        JOIN athletes at ON at.athlete_id = al.athlete_id
        WHERE al.status = 'open'
        GROUP BY al.athlete_id
        ORDER BY count DESC, at.canonical_name
        LIMIT 10
        """,
    )
    quality_rows = _fetchall(
        connection,
        """
        SELECT finding_type, severity, COUNT(*) count
        FROM data_quality_findings
        WHERE status = 'open'
        GROUP BY finding_type, severity
        ORDER BY finding_type, severity
        """,
    )
    domain_counts = {
        "psr_responses": _count(connection, "psr_responses"),
        "weekly_physio_reports": _count(connection, "weekly_physio_reports"),
        "physio_case_events": _count(connection, "physio_case_events"),
        "physical_assessments": _count(connection, "physical_assessments"),
        "alerts": _count(connection, "alerts"),
    }
    pending_identity = connection.execute(
        "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'"
    ).fetchone()[0]
    alerts_count = connection.execute("SELECT COUNT(*) FROM alerts WHERE status = 'open'").fetchone()[0]
    quality_count = connection.execute("SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open'").fetchone()[0]

    lines = [
        "# Relatorio Semanal Deterministico",
        "",
        f"Gerado em UTC: `{utc_now()}`",
        "",
        "## Resumo",
        "",
        f"- Alertas abertos: `{alerts_count}`",
        f"- Candidatos de identidade pendentes: `{pending_identity}`",
        f"- Achados de qualidade abertos: `{quality_count}`",
        "",
        "## Cobertura",
        "",
    ]
    lines.extend(f"- {name}: `{value}`" for name, value in domain_counts.items())
    lines.extend(["", "## Alertas Por Tipo", "", "| Tipo | Severidade | Quantidade |", "|---|---:|---:|"])
    lines.extend(f"| {row['alert_type']} | {row['severity']} | {row['count']} |" for row in alert_rows)
    lines.extend(["", "## Atletas Com Mais Alertas", "", "| Atleta | Nome | Alertas |", "|---|---|---:|"])
    lines.extend(f"| {row['athlete_id']} | {row['canonical_name']} | {row['count']} |" for row in top_alerts)
    lines.extend(["", "## Qualidade Dos Dados", "", "| Achado | Severidade | Quantidade |", "|---|---:|---:|"])
    lines.extend(f"| {row['finding_type']} | {row['severity']} | {row['count']} |" for row in quality_rows)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    connection.close()
    return WeeklyReportResult(report_path, alerts_count, pending_identity, quality_count)


def _count(connection: sqlite3.Connection, table: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _fetchall(connection: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    return connection.execute(query).fetchall()
