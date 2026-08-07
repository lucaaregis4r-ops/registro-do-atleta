from pathlib import Path
import sqlite3

from registro_atleta.api.security import token_is_allowed
from registro_atleta.api.review import (
    apply_alert_review,
    apply_duplicate_review,
    apply_identity_review,
    apply_literature_review,
    list_athletes,
    list_alert_episodes,
    list_duplicate_findings,
    list_identity_candidates,
    list_latest_briefing_items,
    list_literature_reviews,
    list_open_alerts,
    status_summary,
)
from registro_atleta.database.schema import connect_database, initialize_database


def test_apply_identity_review_confirms_candidate_and_audits_alias(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    _seed_identity_candidate(db_path)

    result = apply_identity_review(
        db_path,
        candidate_id="candidate-1",
        decision="confirm_match",
        reviewed_by="Lucas",
        selected_athlete_id="OLY-ATH-000001",
        notes="Mesmo atleta.",
    )

    assert result.status == "human_confirmed"
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT decision_status FROM identity_candidates WHERE candidate_id = 'candidate-1'").fetchone()[0] == "human_confirmed"
    assert connection.execute("SELECT COUNT(*) FROM identity_reviews").fetchone()[0] == 1
    assert connection.execute("SELECT is_confirmed, confirmed_by FROM athlete_aliases").fetchone() == (1, "Lucas")
    connection.close()


def test_apply_identity_review_rejects_candidate_and_status_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    _seed_identity_candidate(db_path)

    result = apply_identity_review(db_path, "candidate-1", "reject_match", "Lucas")

    assert result.status == "human_rejected"
    assert list_identity_candidates(db_path) == []
    summary = status_summary(db_path)
    assert summary["athletes"] == 1
    assert summary["pending_identity"] == 0


def test_apply_identity_review_creates_new_athlete_with_membership(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    _seed_identity_candidate(db_path)
    connection = connect_database(db_path)
    with connection:
        connection.execute(
            "UPDATE identity_candidates SET proposed_athlete_id = NULL, sport = 'Futsal', category = 'Sub-17' WHERE candidate_id = 'candidate-1'"
        )
    connection.close()

    result = apply_identity_review(
        db_path,
        candidate_id="candidate-1",
        decision="create_new_athlete",
        reviewed_by="Lucas",
        notes="Atleta ainda nao cadastrado.",
    )

    assert result.status == "human_created"
    connection = sqlite3.connect(db_path)
    created = connection.execute(
        "SELECT athlete_id, canonical_name FROM athletes WHERE canonical_name = 'Ana S.'"
    ).fetchone()
    assert created is not None
    assert created[0] == "OLY-ATH-000002"
    assert connection.execute(
        "SELECT decision_status, proposed_athlete_id FROM identity_candidates WHERE candidate_id = 'candidate-1'"
    ).fetchone() == ("human_created", "OLY-ATH-000002")
    assert connection.execute(
        "SELECT sport, category FROM athlete_memberships WHERE athlete_id = 'OLY-ATH-000002'"
    ).fetchone() == ("Futsal", "Sub-17")
    assert connection.execute(
        "SELECT is_confirmed, confirmed_by FROM athlete_aliases WHERE athlete_id = 'OLY-ATH-000002'"
    ).fetchone() == (1, "Lucas")
    connection.close()


def test_review_lists_support_basic_filters_and_pagination(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    _seed_identity_candidate(db_path)

    assert list_identity_candidates(db_path, query="Ana", limit=1, offset=0)[0]["candidate_id"] == "candidate-1"
    assert list_identity_candidates(db_path, query="Inexistente") == []


def test_athlete_catalog_lists_aliases_and_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    _seed_identity_candidate(db_path)
    connection = connect_database(db_path)
    with connection:
        connection.execute(
            """
            INSERT INTO athlete_aliases
            (alias_id, athlete_id, alias_raw, alias_normalized, source_id, is_confirmed)
            VALUES ('alias-1', 'OLY-ATH-000001', 'Ana S.', 'ANA S', 'source-1', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO psr_responses
            (psr_id, athlete_id, source_record_id, raw_values_json, created_at)
            VALUES ('psr-1', 'OLY-ATH-000001', 'record-1', '{}', 'now')
            """
        )
    connection.close()

    rows = list_athletes(db_path, query="Ana")

    assert rows[0]["athlete_id"] == "OLY-ATH-000001"
    assert rows[0]["confirmed_alias_count"] == 1
    assert rows[0]["psr_count"] == 1
    assert "Ana S." in rows[0]["aliases"]


def test_duplicate_review_marks_finding_reviewed_and_audits(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO data_quality_findings
            (finding_id, finding_type, entity_type, entity_id, severity, status,
             evidence_json, human_summary, created_at)
            VALUES ('finding-1', 'duplicate_pending_identity_name', 'identity_candidates',
                    'ANA', 'medium', 'open', '{"name_normalized":"ANA"}',
                    'Nome pendente repetido.', 'now')
            """
        )
    connection.close()

    rows = list_duplicate_findings(db_path)
    result = apply_duplicate_review(db_path, "finding-1", "not_duplicate", "Lucas", notes="Homônimas.")

    assert rows[0]["finding_id"] == "finding-1"
    assert result.status == "not_duplicate"
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT status FROM data_quality_findings WHERE finding_id = 'finding-1'").fetchone()[0] == "reviewed"
    assert connection.execute("SELECT decision, reviewed_by, notes FROM duplicate_quality_reviews").fetchone() == ("not_duplicate", "Lucas", "Homônimas.")
    connection.close()


def test_local_api_token_permission_helper() -> None:
    assert token_is_allowed(None, None)
    assert token_is_allowed("local-token", "local-token")
    assert not token_is_allowed("local-token", None)
    assert not token_is_allowed("local-token", "outro")


def test_apply_alert_review_updates_alert_and_audits(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('OLY-ATH-000001', 'Ana Silva', 'ANA SILVA', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO alerts
            (alert_id, athlete_id, alert_type, reference_date, severity, status,
             rule_version, evidence_json, human_summary, created_at)
            VALUES ('alert-1', 'OLY-ATH-000001', 'fixture', '2026-07-01', 'low',
                    'open', 'test', '{}', 'Fixture', 'now')
            """
        )
    connection.close()


def test_alert_list_filters_by_severity(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('OLY-ATH-000001', 'Ana Silva', 'ANA SILVA', 'now', 'now')
            """
        )
        for alert_id, severity in [("alert-1", "low"), ("alert-2", "high")]:
            connection.execute(
                """
                INSERT INTO alerts
                (alert_id, athlete_id, alert_type, reference_date, severity, status,
                 rule_version, evidence_json, human_summary, created_at)
                VALUES (?, 'OLY-ATH-000001', 'fixture', '2026-07-01', ?,
                        'open', 'test', '{}', 'Fixture', ?)
                """,
                (alert_id, severity, alert_id),
            )
    connection.close()

    rows = list_open_alerts(db_path, severity="high")

    assert len(rows) == 1
    assert rows[0]["alert_id"] == "alert-2"

    result = apply_alert_review(db_path, "alert-1", "acknowledged", "Lucas", notes="Lido.")

    assert result.status == "acknowledged"
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT status FROM alerts WHERE alert_id = 'alert-1'").fetchone()[0] == "acknowledged"
    assert connection.execute("SELECT review_status, reviewed_by FROM alert_reviews").fetchone() == ("acknowledged", "Lucas")
    connection.close()


def test_episode_and_briefing_lists_use_phase55_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('OLY-ATH-000001', 'Ana Silva', 'ANA SILVA', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO alert_episodes
            (episode_id, episode_key, athlete_id, alert_type, first_seen_at, last_seen_at,
             episode_status, current_severity, peak_severity, occurrence_count, consecutive_days,
             novelty_status, priority_score, evidence_json, created_at, updated_at)
            VALUES ('episode-1', 'athlete|fixture', 'OLY-ATH-000001', 'fixture', '2026-07-15',
                    '2026-07-15', 'active', 'high', 'high', 2, 1, 'new', 80, '{}', 'now', 'now')
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
                    80, 'Novo episodio', '{}', 1, 1, 'now')
            """
        )
    connection.close()

    episodes = list_alert_episodes(db_path, novelty_status="new")
    items = list_latest_briefing_items(db_path, main_only=True)

    assert episodes[0]["episode_id"] == "episode-1"
    assert episodes[0]["canonical_name"] == "Ana Silva"
    assert items[0]["headline"] == "Novo episodio"
    assert status_summary(db_path)["active_alert_episodes"] == 1


def test_apply_literature_review_updates_status_and_audits(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO papers (paper_id, title, doi)
            VALUES ('paper-1', 'Artigo candidato', '10.1/test')
            """
        )
        connection.execute(
            """
            INSERT INTO paper_topics
            (paper_topic_id, paper_id, topic, reason_selected, human_status, created_at)
            VALUES ('pt-1', 'paper-1', 'fadiga', 'Teste.', 'pending_review', 'now')
            """
        )
    connection.close()

    pending = list_literature_reviews(db_path)
    assert len(pending) == 1

    result = apply_literature_review(db_path, "pt-1", "approved", "Lucas", notes="Boa revisao.")

    assert result.status == "approved"
    assert list_literature_reviews(db_path) == []
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT human_status FROM paper_topics WHERE paper_topic_id = 'pt-1'").fetchone()[0] == "approved"
    assert connection.execute("SELECT decision, reviewed_by, notes FROM paper_topic_reviews").fetchone() == ("approved", "Lucas", "Boa revisao.")
    connection.close()


def test_literature_list_filters_by_topic(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute("INSERT INTO papers (paper_id, title) VALUES ('paper-1', 'Artigo 1')")
        connection.execute("INSERT INTO papers (paper_id, title) VALUES ('paper-2', 'Artigo 2')")
        connection.execute(
            """
            INSERT INTO paper_topics
            (paper_topic_id, paper_id, topic, reason_selected, human_status, created_at)
            VALUES ('pt-1', 'paper-1', 'fadiga', 'Teste.', 'pending_review', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO paper_topics
            (paper_topic_id, paper_id, topic, reason_selected, human_status, created_at)
            VALUES ('pt-2', 'paper-2', 'dor', 'Teste.', 'pending_review', 'now')
            """
        )
    connection.close()

    rows = list_literature_reviews(db_path, topic="fadiga")

    assert len(rows) == 1
    assert rows[0]["paper_topic_id"] == "pt-1"


def _seed_identity_candidate(db_path: Path) -> None:
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO source_systems (source_id, source_type, name, domain, created_at)
            VALUES ('source-1', 'fixture', 'Fixture', 'test', 'now')
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
            INSERT INTO athletes (athlete_id, canonical_name, normalized_name, created_at, updated_at)
            VALUES ('OLY-ATH-000001', 'Ana Silva', 'ANA SILVA', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO identity_candidates
            (candidate_id, source_record_id, name_raw, name_normalized, proposed_athlete_id,
             confidence, evidence_json, decision_status, created_at)
            VALUES ('candidate-1', 'record-1', 'Ana S.', 'ANA S', 'OLY-ATH-000001',
                    0.5, '{}', 'pending_review', 'now')
            """
        )
    connection.close()
