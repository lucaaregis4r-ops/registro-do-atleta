from pathlib import Path
import asyncio
import json
from urllib.parse import urlsplit

import pytest

from registro_atleta.dashboard.export import export_dashboard_data
from registro_atleta.dashboard.macrocycle import build_macrocycle_report
from registro_atleta.database.schema import connect_database, initialize_database


def test_dashboard_api_handles_parallel_read_requests(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from registro_atleta.api.app import create_app

    database_path = tmp_path / "data" / "database" / "registro_atleta.db"
    app = create_app(database_path)
    paths = (
        "/dashboard/summary",
        "/identity/pending?limit=5",
        "/quality/dates?limit=5",
        "/quality/duplicates?limit=5",
        "/quality/review-progress",
    )

    async def asgi_get(path: str) -> int:
        url = urlsplit(path)
        messages = [{"type": "http.request", "body": b"", "more_body": False}]
        status_code = 0

        async def receive() -> dict:
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": url.path,
                "raw_path": url.path.encode("ascii"),
                "query_string": url.query.encode("ascii"),
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 8000),
                "root_path": "",
            },
            receive,
            send,
        )
        return status_code

    async def run_parallel_requests() -> list[int]:
        return await asyncio.gather(
            *(asgi_get(paths[index % len(paths)]) for index in range(20))
        )

    responses = asyncio.run(run_parallel_requests())

    assert responses == [200] * 20


def test_dashboard_export_writes_aggregated_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('OLY-ATH-000001', 'Ana Real', 'ANA REAL', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO alerts
            (alert_id, athlete_id, alert_type, reference_date, severity, status,
             rule_version, evidence_json, human_summary, created_at)
            VALUES ('alert-1', 'OLY-ATH-000001', 'fixture', '2026-07-01', 'low',
                    'open', 'test', '{}', 'Resumo agregado', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO alert_episodes
            (episode_id, episode_key, athlete_id, alert_type, first_seen_at, last_seen_at,
             episode_status, current_severity, peak_severity, occurrence_count, consecutive_days,
             novelty_status, priority_score, evidence_json, created_at, updated_at)
            VALUES ('episode-1', 'OLY-ATH-000001|fixture', 'OLY-ATH-000001', 'fixture',
                    '2026-07-01', '2026-07-01', 'active', 'low', 'low', 1, 1, 'new',
                    55, '{}', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO report_runs
            (report_run_id, report_type, reference_date, status, generated_at, payload_json)
            VALUES ('report-1', 'nightly_briefing', '2026-07-15', 'success', 'now', '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO report_items
            (report_item_id, report_run_id, item_type, athlete_id, episode_id, priority_bucket,
             priority_score, headline, evidence_json, display_order, included_in_main_brief, created_at)
            VALUES ('item-1', 'report-1', 'alert_episode', 'OLY-ATH-000001', 'episode-1', 'new',
                    55, 'Novo episodio sintetico', '{}', 1, 1, 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO source_systems (source_id, source_type, name, domain, created_at)
            VALUES ('source-1', 'fixture', 'Fixture', 'identity', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, status, code_version)
            VALUES ('run-1', 'now', 'success', 'test')
            """
        )
        connection.execute(
            """
            INSERT INTO source_snapshots
            (snapshot_id, run_id, source_id, collected_at, local_path, file_hash, status)
            VALUES ('snapshot-1', 'run-1', 'source-1', 'now', 'fixture.csv', 'hash', 'success')
            """
        )
        connection.execute(
            """
            INSERT INTO source_records
            (source_record_id, source_id, snapshot_id, source_row_key, record_hash,
             raw_payload_json, first_seen_at, last_seen_at)
            VALUES ('record-1', 'source-1', 'snapshot-1', 'row-1', 'hash', '{}', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO identity_candidates
            (candidate_id, source_record_id, name_raw, name_normalized,
             confidence, evidence_json, decision_status, created_at)
            VALUES ('candidate-1', 'record-1', 'Ana R.', 'ANA R',
                    0.5, '{}', 'pending_review', 'now')
            """
        )
    connection.close()

    result = export_dashboard_data(tmp_path, database_path=db_path)
    payload = json.loads(result.output_path.read_text(encoding="utf-8"))

    assert payload["summary"]["athletes"] == 1
    assert payload["summary"]["alerts_open"] == 1
    assert payload["summary"]["alert_episodes_active"] == 1
    assert payload["summary"]["briefing_main_items"] == 1
    assert payload["alerts_by_type"][0]["label"] == "fixture"
    assert payload["episodes_by_novelty"][0]["label"] == "new"
    assert payload["latest_briefing_items"][0]["headline"] == "Novo episodio sintetico"
    assert payload["review_progress"]["summary"]["pending_identity"] == 1
    assert payload["macrocycle"]["summary"]["weeks"] == 6
    assert payload["macrocycle"]["summary"]["active_episodes"] == 1
    assert payload["macrocycle"]["weeks"][0]["phase"] == "Diagnostico"


def test_macrocycle_report_writes_markdown_and_json(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('OLY-ATH-000001', 'Ana Real', 'ANA REAL', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO alerts
            (alert_id, athlete_id, alert_type, reference_date, severity, status,
             rule_version, evidence_json, human_summary, created_at)
            VALUES ('alert-1', 'OLY-ATH-000001', 'fixture', '2026-07-01', 'high',
                    'open', 'test', '{}', 'Resumo agregado', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO alert_episodes
            (episode_id, episode_key, athlete_id, alert_type, first_seen_at, last_seen_at,
             episode_status, current_severity, peak_severity, occurrence_count, consecutive_days,
             novelty_status, priority_score, evidence_json, created_at, updated_at)
            VALUES ('episode-1', 'OLY-ATH-000001|fixture', 'OLY-ATH-000001', 'fixture',
                    '2026-07-01', '2026-07-01', 'active', 'high', 'high', 1, 1, 'new',
                    88, '{}', 'now', 'now')
            """
        )
    connection.close()

    result = build_macrocycle_report(tmp_path, database_path=db_path, weeks=4)

    assert result.report_path.exists()
    assert result.json_path.exists()
    assert result.weeks == 4
    assert result.active_episodes == 1
    assert result.high_episodes == 1
    text = result.report_path.read_text(encoding="utf-8")
    assert "Macrociclo Operacional" in text
    assert "Semanas Do Ciclo" in text


def test_dashboard_static_files_do_not_reference_public_spreadsheets_or_real_data() -> None:
    dashboard_root = Path("apps/dashboard")
    text = "\n".join(path.read_text(encoding="utf-8") for path in dashboard_root.rglob("*") if path.is_file())

    assert "docs.google.com" not in text
    assert "spreadsheets" not in text
    assert "Ana Real" not in text
    assert "Atleta Demo" in text
    assert "/dashboard/summary" in text
    assert "/identity/reviews" in text
    assert "/quality/date-reviews" in text
    assert "reviewerName" in text
    assert "athleteOptions" in text
    assert "/athletes?limit=500" in text
    assert "operationalReport" in text
    assert "renderOperationalReport" in text
    assert "copyOperationalReport" in text
    assert "window.print()" in text
    assert "@media print" in text
    assert "macrocyclePanel" in text
    assert "renderMacrocycle" in text
    assert "decision-guide" in text
    assert "Criar novo atleta" in text
    assert "create_new_athlete" in text
    assert "Para vincular a atleta existente" in text
    assert "Para criar novo atleta" in text
    assert "o sistema gera automaticamente o proximo ID OLY-ATH" in text
    assert "ID existente (nao use para atleta novo)" in text
    assert "apiErrorMessage" in text
    assert "A API local parece estar em versao antiga" in text
    assert "Para usar data corrigida" in text
    assert "Nao e duplicata: sao pessoas/registros diferentes" in text
    assert "/macrocycle" in Path("src/registro_atleta/api/app.py").read_text(encoding="utf-8")
