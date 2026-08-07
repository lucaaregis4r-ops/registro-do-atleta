from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


@dataclass(frozen=True)
class ReviewResult:
    entity_id: str
    status: str
    audit_id: str


def status_summary(database_path: Path) -> dict[str, int]:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        return {
            "athletes": _count(connection, "athletes"),
            "pending_identity": _scalar(connection, "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'"),
            "open_alerts": _scalar(connection, "SELECT COUNT(*) FROM alerts WHERE status = 'open'"),
            "active_alert_episodes": _scalar(connection, "SELECT COUNT(*) FROM alert_episodes WHERE episode_status = 'active'"),
            "latest_briefing_items": _scalar(connection, "SELECT COUNT(*) FROM report_items WHERE report_run_id = (SELECT report_run_id FROM report_runs WHERE report_type = 'nightly_briefing' ORDER BY generated_at DESC LIMIT 1)"),
            "approved_literature_links": _scalar(connection, "SELECT COUNT(*) FROM paper_topics WHERE human_status = 'approved'"),
        }
    finally:
        connection.close()


def list_identity_candidates(database_path: Path, limit: int = 50, offset: int = 0, query: str | None = None) -> list[dict]:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        filters = ["decision_status = 'pending_review'"]
        params: list[object] = []
        if query:
            filters.append("(name_raw LIKE ? OR name_normalized LIKE ?)")
            like = f"%{query.strip()}%"
            params.extend([like, like])
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        rows = connection.execute(
            f"""
            SELECT candidate_id, source_record_id, name_raw, name_normalized, sport,
                   category, proposed_athlete_id, confidence, evidence_json, created_at
            FROM identity_candidates
            WHERE {' AND '.join(filters)}
            ORDER BY name_normalized, created_at
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_athletes(database_path: Path, limit: int = 100, offset: int = 0, query: str | None = None) -> list[dict]:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        filters = ["a.merged_into_athlete_id IS NULL"]
        params: list[object] = []
        if query:
            filters.append(
                """
                (
                    a.athlete_id LIKE ?
                    OR a.canonical_name LIKE ?
                    OR a.normalized_name LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM athlete_aliases aa_query
                        WHERE aa_query.athlete_id = a.athlete_id
                          AND (aa_query.alias_raw LIKE ? OR aa_query.alias_normalized LIKE ?)
                    )
                )
                """
            )
            like = f"%{query.strip()}%"
            params.extend([like, like, like, like, like])
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        rows = connection.execute(
            f"""
            SELECT
                a.athlete_id,
                a.canonical_name,
                a.normalized_name,
                a.active_status,
                COUNT(DISTINCT aa.alias_id) alias_count,
                COUNT(DISTINCT CASE WHEN aa.is_confirmed = 1 THEN aa.alias_id END) confirmed_alias_count,
                GROUP_CONCAT(DISTINCT aa.alias_raw) aliases,
                GROUP_CONCAT(DISTINCT COALESCE(am.sport, '') || ' / ' || COALESCE(am.category, '')) memberships,
                COUNT(DISTINCT psr.psr_id) psr_count,
                COUNT(DISTINCT pc.case_id) physio_case_count,
                COUNT(DISTINCT pa.assessment_id) assessment_count
            FROM athletes a
            LEFT JOIN athlete_aliases aa ON aa.athlete_id = a.athlete_id
            LEFT JOIN athlete_memberships am ON am.athlete_id = a.athlete_id
            LEFT JOIN psr_responses psr ON psr.athlete_id = a.athlete_id
            LEFT JOIN physio_cases pc ON pc.athlete_id = a.athlete_id
            LEFT JOIN physical_assessments pa ON pa.athlete_id = a.athlete_id
            WHERE {' AND '.join(filters)}
            GROUP BY a.athlete_id
            ORDER BY a.canonical_name
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_duplicate_findings(database_path: Path, limit: int = 50, offset: int = 0, status: str = "open") -> list[dict]:
    status = _require_choice(status, {"open", "reviewed", "superseded"})
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        rows = connection.execute(
            """
            SELECT finding_id, finding_type, entity_type, entity_id, severity, status,
                   evidence_json, human_summary, created_at
            FROM data_quality_findings
            WHERE finding_type LIKE 'duplicate_%'
              AND status = ?
            ORDER BY
                CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                created_at DESC,
                finding_type
            LIMIT ? OFFSET ?
            """,
            (status, max(1, min(limit, 200)), max(0, offset)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_open_alerts(
    database_path: Path,
    limit: int = 50,
    offset: int = 0,
    severity: str | None = None,
    alert_type: str | None = None,
) -> list[dict]:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        filters = ["al.status = 'open'"]
        params: list[object] = []
        if severity:
            filters.append("al.severity = ?")
            params.append(severity)
        if alert_type:
            filters.append("al.alert_type = ?")
            params.append(alert_type)
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        rows = connection.execute(
            f"""
            SELECT al.alert_id, al.athlete_id, at.canonical_name, al.alert_type,
                   al.reference_date, al.severity, al.human_summary, al.created_at
            FROM alerts al
            JOIN athletes at ON at.athlete_id = al.athlete_id
            WHERE {' AND '.join(filters)}
            ORDER BY al.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_alert_episodes(
    database_path: Path,
    limit: int = 50,
    offset: int = 0,
    novelty_status: str | None = None,
    episode_status: str | None = None,
) -> list[dict]:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        filters = ["1 = 1"]
        params: list[object] = []
        if novelty_status:
            filters.append("ae.novelty_status = ?")
            params.append(novelty_status)
        if episode_status:
            filters.append("ae.episode_status = ?")
            params.append(episode_status)
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        rows = connection.execute(
            f"""
            SELECT ae.episode_id, ae.episode_key, ae.athlete_id, at.canonical_name,
                   ae.alert_type, ae.first_seen_at, ae.last_seen_at, ae.episode_status,
                   ae.current_severity, ae.peak_severity, ae.occurrence_count,
                   ae.consecutive_days, ae.novelty_status, ae.priority_score,
                   ae.evidence_json, ae.resolved_at, ae.updated_at
            FROM alert_episodes ae
            JOIN athletes at ON at.athlete_id = ae.athlete_id
            WHERE {' AND '.join(filters)}
            ORDER BY ae.priority_score DESC, ae.updated_at DESC, at.canonical_name
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_latest_briefing_items(database_path: Path, limit: int = 50, main_only: bool = False) -> list[dict]:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        latest = connection.execute(
            """
            SELECT report_run_id
            FROM report_runs
            WHERE report_type = 'nightly_briefing'
            ORDER BY generated_at DESC
            LIMIT 1
            """
        ).fetchone()
        if latest is None:
            return []
        filters = ["ri.report_run_id = ?"]
        params: list[object] = [latest["report_run_id"]]
        if main_only:
            filters.append("ri.included_in_main_brief = 1")
        params.append(max(1, min(limit, 200)))
        rows = connection.execute(
            f"""
            SELECT ri.report_item_id, ri.report_run_id, rr.reference_date, rr.status report_status,
                   ri.item_type, ri.athlete_id, at.canonical_name, ri.episode_id, ri.alert_id,
                   ri.finding_id, ri.source_record_id, ri.priority_bucket, ri.priority_score,
                   ri.headline, ri.evidence_json, ri.display_order, ri.included_in_main_brief
            FROM report_items ri
            JOIN report_runs rr ON rr.report_run_id = ri.report_run_id
            LEFT JOIN athletes at ON at.athlete_id = ri.athlete_id
            WHERE {' AND '.join(filters)}
            ORDER BY ri.display_order
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_literature_reviews(
    database_path: Path,
    limit: int = 50,
    offset: int = 0,
    topic: str | None = None,
    status: str | None = None,
) -> list[dict]:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        statuses = ["pending_review", "needs_revision"] if not status else [_require_choice(status, {"pending_review", "needs_revision", "approved", "rejected"})]
        placeholders = ",".join("?" for _ in statuses)
        filters = [f"pt.human_status IN ({placeholders})"]
        params: list[object] = list(statuses)
        if topic:
            filters.append("pt.topic LIKE ?")
            params.append(f"%{topic.strip()}%")
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        rows = connection.execute(
            f"""
            SELECT
                pt.paper_topic_id,
                pt.topic,
                pt.relevance_score,
                pt.reason_selected,
                pt.human_status,
                p.title,
                p.authors_json,
                p.publication_year,
                p.journal,
                p.doi,
                p.url,
                p.source_provider
            FROM paper_topics pt
            JOIN papers p ON p.paper_id = pt.paper_id
            WHERE {' AND '.join(filters)}
            ORDER BY pt.created_at DESC, p.title
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def apply_identity_review(
    database_path: Path,
    candidate_id: str,
    decision: str,
    reviewed_by: str,
    selected_athlete_id: str | None = None,
    new_athlete_name: str | None = None,
    notes: str | None = None,
) -> ReviewResult:
    decision = _require_choice(decision, {"confirm_match", "reject_match", "create_new_athlete"})
    reviewed_by = _require_text(reviewed_by, "reviewed_by")
    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        candidate = connection.execute(
            "SELECT * FROM identity_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if candidate is None:
            raise ValueError("candidate_id nao encontrado")
        if candidate["decision_status"] != "pending_review":
            raise ValueError("candidate_id nao esta pendente de revisao")

        selected = selected_athlete_id or candidate["proposed_athlete_id"]
        if decision == "confirm_match":
            if not selected:
                raise ValueError("selected_athlete_id e obrigatorio para confirm_match")
            _ensure_athlete_exists(connection, selected)
            new_status = "human_confirmed"
            connection.execute(
                """
                UPDATE identity_candidates
                SET decision_status = ?, proposed_athlete_id = ?, confidence = 1.0
                WHERE candidate_id = ?
                """,
                (new_status, selected, candidate_id),
            )
            _ensure_confirmed_alias(connection, selected, candidate["name_raw"], candidate["source_record_id"], reviewed_by)
            _ensure_membership_from_candidate(connection, selected, candidate)
        elif decision == "create_new_athlete":
            selected = _create_athlete_from_candidate(connection, candidate, reviewed_by, new_athlete_name)
            new_status = "human_created"
            connection.execute(
                """
                UPDATE identity_candidates
                SET decision_status = ?, proposed_athlete_id = ?, confidence = 1.0
                WHERE candidate_id = ?
                """,
                (new_status, selected, candidate_id),
            )
            _ensure_confirmed_alias(connection, selected, candidate["name_raw"], candidate["source_record_id"], reviewed_by)
            _ensure_membership_from_candidate(connection, selected, candidate)
        else:
            selected = None
            new_status = "human_rejected"
            connection.execute(
                "UPDATE identity_candidates SET decision_status = ?, proposed_athlete_id = NULL WHERE candidate_id = ?",
                (new_status, candidate_id),
            )

        review_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO identity_reviews
            (review_id, candidate_id, decision, selected_athlete_id, reviewed_by, reviewed_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, candidate_id, decision, selected, reviewed_by, utc_now(), notes),
        )
    connection.close()
    return ReviewResult(entity_id=candidate_id, status=new_status, audit_id=review_id)


def apply_alert_review(
    database_path: Path,
    alert_id: str,
    review_status: str,
    reviewed_by: str,
    notes: str | None = None,
) -> ReviewResult:
    review_status = _require_choice(review_status, {"acknowledged", "resolved", "dismissed"})
    reviewed_by = _require_text(reviewed_by, "reviewed_by")
    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        alert = connection.execute("SELECT alert_id FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
        if alert is None:
            raise ValueError("alert_id nao encontrado")
        review_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO alert_reviews
            (alert_review_id, alert_id, review_status, reviewed_by, reviewed_at, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (review_id, alert_id, review_status, reviewed_by, utc_now(), notes),
        )
        connection.execute("UPDATE alerts SET status = ? WHERE alert_id = ?", (review_status, alert_id))
    connection.close()
    return ReviewResult(entity_id=alert_id, status=review_status, audit_id=review_id)


def apply_literature_review(
    database_path: Path,
    paper_topic_id: str,
    decision: str,
    reviewed_by: str,
    notes: str | None = None,
) -> ReviewResult:
    decision = _require_choice(decision, {"approved", "rejected", "needs_revision"})
    reviewed_by = _require_text(reviewed_by, "reviewed_by")
    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        paper_topic = connection.execute(
            "SELECT human_status FROM paper_topics WHERE paper_topic_id = ?",
            (paper_topic_id,),
        ).fetchone()
        if paper_topic is None:
            raise ValueError("paper_topic_id nao encontrado")
        previous_status = paper_topic["human_status"]
        review_id = uuid4().hex
        connection.execute(
            "UPDATE paper_topics SET human_status = ? WHERE paper_topic_id = ?",
            (decision, paper_topic_id),
        )
        connection.execute(
            """
            INSERT INTO paper_topic_reviews
            (review_id, paper_topic_id, decision, previous_status, new_status,
             reviewed_by, reviewed_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, paper_topic_id, decision, previous_status, decision, reviewed_by, utc_now(), notes),
        )
    connection.close()
    return ReviewResult(entity_id=paper_topic_id, status=decision, audit_id=review_id)


def apply_duplicate_review(
    database_path: Path,
    finding_id: str,
    decision: str,
    reviewed_by: str,
    notes: str | None = None,
) -> ReviewResult:
    decision = _require_choice(decision, {"mark_reviewed", "not_duplicate", "needs_follow_up"})
    reviewed_by = _require_text(reviewed_by, "reviewed_by")
    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        finding = connection.execute(
            """
            SELECT *
            FROM data_quality_findings
            WHERE finding_id = ?
              AND finding_type LIKE 'duplicate_%'
            """,
            (finding_id,),
        ).fetchone()
        if finding is None:
            raise ValueError("finding_id de duplicidade nao encontrado")
        if finding["status"] != "open":
            raise ValueError("finding_id nao esta aberto")
        review_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO duplicate_quality_reviews
            (review_id, finding_id, decision, reviewed_by, reviewed_at, notes, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, finding_id, decision, reviewed_by, utc_now(), notes, finding["evidence_json"]),
        )
        if decision in {"mark_reviewed", "not_duplicate"}:
            connection.execute("UPDATE data_quality_findings SET status = 'reviewed' WHERE finding_id = ?", (finding_id,))
    connection.close()
    return ReviewResult(entity_id=finding_id, status=decision, audit_id=review_id)


def _ensure_confirmed_alias(connection: sqlite3.Connection, athlete_id: str, alias_raw: str, source_record_id: str, reviewed_by: str) -> None:
    source = connection.execute("SELECT source_id FROM source_records WHERE source_record_id = ?", (source_record_id,)).fetchone()
    source_id = source["source_id"] if source else None
    alias_normalized = _normalize_alias(alias_raw)
    existing = connection.execute(
        """
        SELECT alias_id FROM athlete_aliases
        WHERE athlete_id = ? AND alias_normalized = ? AND COALESCE(source_id, '') = COALESCE(?, '')
        """,
        (athlete_id, alias_normalized, source_id),
    ).fetchone()
    if existing:
        connection.execute(
            "UPDATE athlete_aliases SET is_confirmed = 1, confirmed_by = ?, confirmed_at = ? WHERE alias_id = ?",
            (reviewed_by, utc_now(), existing["alias_id"]),
        )
        return
    connection.execute(
        """
        INSERT INTO athlete_aliases
        (alias_id, athlete_id, alias_raw, alias_normalized, source_id, is_confirmed, confirmed_by, confirmed_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (uuid4().hex, athlete_id, alias_raw, alias_normalized, source_id, reviewed_by, utc_now()),
    )


def _create_athlete_from_candidate(
    connection: sqlite3.Connection,
    candidate: sqlite3.Row,
    reviewed_by: str,
    new_athlete_name: str | None,
) -> str:
    from registro_atleta.identity.normalization import normalize_name

    canonical_name = (new_athlete_name or candidate["name_raw"] or "").strip()
    if not canonical_name:
        raise ValueError("nome do novo atleta e obrigatorio")
    normalized_name = normalize_name(canonical_name)
    if connection.execute("SELECT 1 FROM athletes WHERE normalized_name = ?", (normalized_name,)).fetchone():
        raise ValueError("ja existe atleta com este nome normalizado; use confirmar vinculo")
    athlete_id = _next_athlete_id(connection)
    now = utc_now()
    connection.execute(
        """
        INSERT INTO athletes
        (athlete_id, canonical_name, normalized_name, active_status, created_at, updated_at)
        VALUES (?, ?, ?, 'active', ?, ?)
        """,
        (athlete_id, canonical_name, normalized_name, now, now),
    )
    return athlete_id


def _next_athlete_id(connection: sqlite3.Connection) -> str:
    rows = connection.execute("SELECT athlete_id FROM athletes WHERE athlete_id LIKE 'OLY-ATH-%'").fetchall()
    numbers: list[int] = []
    for row in rows:
        suffix = str(row["athlete_id"]).replace("OLY-ATH-", "", 1)
        if suffix.isdigit():
            numbers.append(int(suffix))
    return f"OLY-ATH-{(max(numbers) if numbers else 0) + 1:06d}"


def _ensure_membership_from_candidate(connection: sqlite3.Connection, athlete_id: str, candidate: sqlite3.Row) -> None:
    sport = candidate["sport"]
    category = candidate["category"]
    source_record_id = candidate["source_record_id"]
    if not sport and not category and not source_record_id:
        return
    existing = connection.execute(
        """
        SELECT membership_id
        FROM athlete_memberships
        WHERE athlete_id = ?
          AND COALESCE(sport, '') = COALESCE(?, '')
          AND COALESCE(category, '') = COALESCE(?, '')
          AND COALESCE(source_record_id, '') = COALESCE(?, '')
        """,
        (athlete_id, sport, category, source_record_id),
    ).fetchone()
    if existing:
        return
    connection.execute(
        """
        INSERT INTO athlete_memberships
        (membership_id, athlete_id, sport, category, source_record_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (uuid4().hex, athlete_id, sport, category, source_record_id),
    )


def _normalize_alias(value: str) -> str:
    from registro_atleta.identity.normalization import normalize_name

    return normalize_name(value)


def _ensure_athlete_exists(connection: sqlite3.Connection, athlete_id: str) -> None:
    if connection.execute("SELECT 1 FROM athletes WHERE athlete_id = ?", (athlete_id,)).fetchone() is None:
        raise ValueError("selected_athlete_id nao encontrado")


def _require_choice(value: str, choices: set[str]) -> str:
    normalized = (value or "").strip()
    if normalized not in choices:
        raise ValueError(f"valor invalido: {value}")
    return normalized


def _require_text(value: str, field: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(f"{field} e obrigatorio")
    return normalized


def _count(connection: sqlite3.Connection, table: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    return connection.execute(query).fetchone()[0]
