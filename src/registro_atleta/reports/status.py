from __future__ import annotations

from html import escape
from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now
from registro_atleta.operations.backup import list_backups


def build_status_panel(root: Path, database_path: Path | None = None) -> Path:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    output_dir = root / "data" / "reports" / "status"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "status.html"

    latest_run = connection.execute(
        "SELECT run_id, started_at, finished_at, status, records_created, records_updated, errors FROM pipeline_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    counts = {
        "Atletas": _count(connection, "athletes"),
        "PSR": _count(connection, "psr_responses"),
        "Eventos fisio": _count(connection, "physio_case_events"),
        "Avaliacoes": _count(connection, "physical_assessments"),
        "Alertas": _count(connection, "alerts"),
        "Qualidade": _count(connection, "data_quality_findings"),
    }
    alert_rows = connection.execute(
        "SELECT alert_type, severity, COUNT(*) count FROM alerts GROUP BY alert_type, severity ORDER BY alert_type, severity"
    ).fetchall()
    backups = list_backups(root)[:5]

    html = [
        "<!doctype html>",
        "<html lang=\"pt-BR\">",
        "<head><meta charset=\"utf-8\"><title>Registro do Atleta Status</title>",
        "<style>body{font-family:Arial,sans-serif;margin:32px;color:#1f2933}table{border-collapse:collapse}td,th{border:1px solid #d9e2ec;padding:6px 10px}th{background:#f0f4f8}.ok{color:#0f7b0f}.bad{color:#b42318}</style>",
        "</head><body>",
        "<h1>Registro do Atleta - Status Operacional</h1>",
        f"<p>Gerado em UTC: <code>{escape(utc_now())}</code></p>",
        "<h2>Ultima sincronizacao</h2>",
    ]
    if latest_run:
        status_class = "ok" if latest_run["status"] == "success" else "bad"
        html.append("<table><tr><th>Run</th><th>Inicio</th><th>Fim</th><th>Status</th><th>Novos</th><th>Alterados</th><th>Erros</th></tr>")
        html.append(
            "<tr>"
            f"<td>{escape(str(latest_run['run_id']))}</td><td>{escape(str(latest_run['started_at']))}</td>"
            f"<td>{escape(str(latest_run['finished_at']))}</td><td class=\"{status_class}\">{escape(str(latest_run['status']))}</td>"
            f"<td>{latest_run['records_created']}</td><td>{latest_run['records_updated']}</td><td>{latest_run['errors']}</td>"
            "</tr></table>"
        )
    else:
        html.append("<p>Nenhuma sincronizacao registrada.</p>")
    html.extend(["<h2>Contagens</h2>", "<table><tr><th>Item</th><th>Total</th></tr>"])
    html.extend(f"<tr><td>{escape(name)}</td><td>{value}</td></tr>" for name, value in counts.items())
    html.extend(["</table>", "<h2>Alertas</h2>", "<table><tr><th>Tipo</th><th>Severidade</th><th>Total</th></tr>"])
    html.extend(f"<tr><td>{escape(row['alert_type'])}</td><td>{escape(row['severity'])}</td><td>{row['count']}</td></tr>" for row in alert_rows)
    html.extend(["</table>", "<h2>Backups recentes</h2>", "<table><tr><th>Arquivo</th><th>Tamanho</th></tr>"])
    html.extend(f"<tr><td>{escape(path.name)}</td><td>{path.stat().st_size}</td></tr>" for path in backups)
    html.extend(["</table>", "</body></html>"])
    output_path.write_text("\n".join(html), encoding="utf-8")
    connection.close()
    return output_path


def _count(connection: sqlite3.Connection, table: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
