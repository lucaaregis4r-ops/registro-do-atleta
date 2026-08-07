from pathlib import Path
import csv
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.identity.reviews import import_identity_reviews
from registro_atleta.quality.blockers import apply_date_review, build_data_readiness_report, import_date_reviews, list_date_review_items
from registro_atleta.quality.dates import effective_psr_dates_sql
from registro_atleta.quality.review_progress import build_review_progress_report


def test_data_readiness_report_exports_identity_and_date_review_queues(tmp_path: Path) -> None:
    db_path = _seed_blocked_database(tmp_path)

    result = build_data_readiness_report(tmp_path, database_path=db_path)

    assert result.pending_identity == 1
    assert result.date_findings == 1
    assert result.report_path.exists()
    assert result.identity_review_path.exists()
    assert result.date_review_path.exists()
    report_text = result.report_path.read_text(encoding="utf-8")
    assert "Identidades pendentes" in report_text
    assert "Achados de data abertos" in report_text


def test_import_identity_reviews_requires_confirm_and_applies_decisions(tmp_path: Path) -> None:
    db_path = _seed_blocked_database(tmp_path)
    csv_path = tmp_path / "reviews.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["candidate_id", "decision", "selected_athlete_id", "notes"])
        writer.writerow(["candidate-1", "confirm_match", "athlete-1", "Mesmo atleta"])

    blocked = import_identity_reviews(csv_path, db_path, reviewed_by="Lucas", confirm=False)
    applied = import_identity_reviews(csv_path, db_path, reviewed_by="Lucas", confirm=True)

    assert blocked.blocked_reason is not None
    assert applied.applied_reviews == 1
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT decision_status FROM identity_candidates WHERE candidate_id = 'candidate-1'").fetchone()[0] == "human_confirmed"
    assert connection.execute("SELECT COUNT(*) FROM identity_reviews").fetchone()[0] == 1


def test_import_date_reviews_records_override_without_changing_raw_date(tmp_path: Path) -> None:
    db_path = _seed_blocked_database(tmp_path)
    csv_path = tmp_path / "date_reviews.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "finding_id",
                "entity_type",
                "entity_id",
                "source_record_id",
                "current_value",
                "decision",
                "corrected_date",
                "notes",
            ]
        )
        writer.writerow(
            [
                "finding-1",
                "psr_responses",
                "psr-1",
                "record-1",
                "2099-01-01",
                "use_corrected_date",
                "2026-01-01",
                "Corrigido por revisao humana.",
            ]
        )

    blocked = import_date_reviews(csv_path, db_path, reviewed_by="Lucas", confirm=False)
    applied = import_date_reviews(csv_path, db_path, reviewed_by="Lucas", confirm=True)

    assert blocked.blocked_reason is not None
    assert applied.applied_reviews == 1
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT response_date FROM psr_responses WHERE psr_id = 'psr-1'").fetchone()[0] == "2099-01-01"
    assert connection.execute("SELECT corrected_value, override_status FROM date_overrides").fetchone() == ("2026-01-01", "active")
    assert connection.execute("SELECT decision, reviewed_by FROM date_quality_reviews").fetchone() == ("use_corrected_date", "Lucas")
    assert connection.execute("SELECT status FROM data_quality_findings WHERE finding_id = 'finding-1'").fetchone()[0] == "reviewed"


def test_apply_date_review_from_ui_service(tmp_path: Path) -> None:
    db_path = _seed_blocked_database(tmp_path)

    rows = list_date_review_items(db_path)
    result = apply_date_review(
        db_path,
        finding_id=rows[0]["finding_id"],
        decision="exclude_from_temporal",
        reviewed_by="Lucas",
        notes="Sem data confiavel.",
    )

    assert result.status == "reviewed"
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT override_status FROM date_overrides").fetchone()[0] == "excluded"


def test_date_override_survives_recreated_psr_id(tmp_path: Path) -> None:
    db_path = _seed_blocked_database(tmp_path)
    apply_date_review(
        db_path,
        finding_id="finding-1",
        decision="exclude_from_temporal",
        reviewed_by="Lucas",
    )
    connection = connect_database(db_path)
    with connection:
        connection.execute("DELETE FROM psr_responses WHERE psr_id = 'psr-1'")
        connection.execute(
            """
            INSERT INTO psr_responses
            (psr_id, athlete_id, source_record_id, response_date, raw_values_json, created_at)
            VALUES ('psr-recreated', 'athlete-1', 'record-1', '2026-03-09', '{}', 'now')
            """
        )

    row = connection.execute(
        f"SELECT effective_response_date, date_override_status FROM ({effective_psr_dates_sql()})"
    ).fetchone()
    connection.close()

    assert row["effective_response_date"] is None
    assert row["date_override_status"] == "excluded"


def test_review_progress_report_counts_open_and_reviewed_items(tmp_path: Path) -> None:
    db_path = _seed_blocked_database(tmp_path)
    apply_date_review(db_path, "finding-1", "keep_as_is", "Lucas", notes="Conferido.")
    connection = connect_database(db_path)
    with connection:
        connection.execute(
            """
            INSERT INTO data_quality_findings
            (finding_id, finding_type, entity_type, entity_id, severity, status,
             evidence_json, human_summary, created_at)
            VALUES ('duplicate-1', 'duplicate_pending_identity_name', 'identity_candidates',
                    'ANA', 'medium', 'open', '{"candidate_count":2}',
                    'Nome pendente repetido.', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO duplicate_quality_reviews
            (review_id, finding_id, decision, reviewed_by, reviewed_at, notes, evidence_json)
            VALUES ('dup-review-1', 'duplicate-1', 'needs_follow_up', 'Lucas', 'now', 'Acompanhar.', '{}')
            """
        )
    connection.close()

    result = build_review_progress_report(tmp_path, database_path=db_path)

    assert result.pending_identity == 1
    assert result.open_date_findings == 0
    assert result.reviewed_dates == 1
    assert result.open_duplicate_findings == 1
    assert result.reviewed_duplicates == 1
    assert result.report_path.exists()
    assert result.json_path.exists()


def _seed_blocked_database(tmp_path: Path) -> Path:
    db_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO source_systems (source_id, source_type, name, domain, created_at)
            VALUES ('source-1', 'fixture', 'Fixture', 'psr', 'now')
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
            VALUES ('athlete-1', 'Ana Silva', 'ANA SILVA', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO identity_candidates
            (candidate_id, source_record_id, name_raw, name_normalized, proposed_athlete_id,
             confidence, evidence_json, decision_status, created_at)
            VALUES ('candidate-1', 'record-1', 'Ana S.', 'ANA S', 'athlete-1',
                    0.5, '{}', 'pending_review', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO psr_responses
            (psr_id, athlete_id, source_record_id, response_date, raw_values_json, created_at)
            VALUES ('psr-1', 'athlete-1', 'record-1', '2099-01-01', '{}', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO data_quality_findings
            (finding_id, finding_type, entity_type, entity_id, severity, status,
             evidence_json, human_summary, created_at)
            VALUES ('finding-1', 'psr_invalid_or_future_date', 'psr_responses', 'psr-1',
                    'high', 'open', '{"response_date":"2099-01-01"}',
                    'PSR com data ausente, invalida ou futura.', 'now')
            """
        )
    connection.close()
    return db_path
