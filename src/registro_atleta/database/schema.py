from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock


SCHEMA_VERSION = 1
_SCHEMA_INITIALIZATION_LOCK = RLock()


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_systems (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT,
    domain TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    code_version TEXT NOT NULL,
    records_created INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    records_unchanged INTEGER NOT NULL DEFAULT 0,
    warnings INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    local_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id),
    FOREIGN KEY (source_id) REFERENCES source_systems(source_id)
);

CREATE TABLE IF NOT EXISTS source_records (
    source_record_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    source_row_key TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (snapshot_id) REFERENCES source_snapshots(snapshot_id),
    FOREIGN KEY (source_id) REFERENCES source_systems(source_id)
);

CREATE INDEX IF NOT EXISTS idx_source_records_lookup
ON source_records(source_id, source_row_key, is_current);

CREATE INDEX IF NOT EXISTS idx_source_records_hash
ON source_records(record_hash);

CREATE TABLE IF NOT EXISTS staging_records (
    staging_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_row_key TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    staged_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id),
    FOREIGN KEY (snapshot_id) REFERENCES source_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_staging_records_run
ON staging_records(run_id, source_id);

CREATE TABLE IF NOT EXISTS athletes (
    athlete_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    birth_date TEXT,
    sex TEXT,
    active_status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    merged_into_athlete_id TEXT,
    FOREIGN KEY (merged_into_athlete_id) REFERENCES athletes(athlete_id)
);

CREATE TABLE IF NOT EXISTS athlete_aliases (
    alias_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    alias_raw TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    source_id TEXT,
    is_confirmed INTEGER NOT NULL DEFAULT 0,
    confirmed_by TEXT,
    confirmed_at TEXT,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_athlete_aliases_unique
ON athlete_aliases(athlete_id, alias_normalized, COALESCE(source_id, ''));

CREATE INDEX IF NOT EXISTS idx_athlete_aliases_lookup
ON athlete_aliases(alias_normalized, is_confirmed);

CREATE TABLE IF NOT EXISTS athlete_memberships (
    membership_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    sport TEXT,
    category TEXT,
    team TEXT,
    start_date TEXT,
    end_date TEXT,
    source_record_id TEXT,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id),
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_athlete_memberships_unique
ON athlete_memberships(athlete_id, COALESCE(sport, ''), COALESCE(category, ''), COALESCE(source_record_id, ''));

CREATE TABLE IF NOT EXISTS identity_candidates (
    candidate_id TEXT PRIMARY KEY,
    source_record_id TEXT NOT NULL UNIQUE,
    name_raw TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    sport TEXT,
    category TEXT,
    proposed_athlete_id TEXT,
    confidence REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    decision_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id),
    FOREIGN KEY (proposed_athlete_id) REFERENCES athletes(athlete_id)
);

CREATE INDEX IF NOT EXISTS idx_identity_candidates_status
ON identity_candidates(decision_status, name_normalized);

CREATE TABLE IF NOT EXISTS identity_reviews (
    review_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    selected_athlete_id TEXT,
    reviewed_by TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (candidate_id) REFERENCES identity_candidates(candidate_id),
    FOREIGN KEY (selected_athlete_id) REFERENCES athletes(athlete_id)
);

CREATE TABLE IF NOT EXISTS psr_responses (
    psr_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL UNIQUE,
    submitted_at TEXT,
    response_date TEXT,
    sport TEXT,
    category TEXT,
    pain_location_raw TEXT,
    pain_intensity REAL,
    fatigue_score INTEGER,
    sleep_score INTEGER,
    muscle_soreness_score INTEGER,
    stress_score INTEGER,
    mood_score INTEGER,
    raw_values_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id),
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_psr_responses_athlete_date
ON psr_responses(athlete_id, response_date);

CREATE TABLE IF NOT EXISTS physio_cases (
    case_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    diagnosis_raw TEXT NOT NULL,
    body_region TEXT,
    laterality TEXT,
    opened_at TEXT,
    closed_at TEXT,
    current_status TEXT NOT NULL,
    responsible_professional TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);

CREATE INDEX IF NOT EXISTS idx_physio_cases_athlete_status
ON physio_cases(athlete_id, current_status);

CREATE INDEX IF NOT EXISTS idx_physio_cases_lookup
ON physio_cases(athlete_id, diagnosis_raw, current_status);

CREATE TABLE IF NOT EXISTS physio_case_events (
    event_id TEXT PRIMARY KEY,
    case_id TEXT,
    athlete_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL UNIQUE,
    event_date TEXT,
    event_type TEXT NOT NULL,
    treatment_phase TEXT,
    training_restriction TEXT,
    physical_training_restriction TEXT,
    severity TEXT,
    notes TEXT,
    raw_values_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES physio_cases(case_id),
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id),
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_physio_case_events_athlete
ON physio_case_events(athlete_id, event_date);

CREATE TABLE IF NOT EXISTS weekly_physio_reports (
    weekly_report_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL UNIQUE,
    week_start TEXT,
    week_end TEXT,
    sport TEXT,
    category TEXT,
    injury_raw TEXT,
    severity TEXT,
    treatment_phase TEXT,
    observations TEXT,
    training_restriction TEXT,
    physical_training_restriction TEXT,
    raw_values_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id),
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_weekly_physio_reports_athlete
ON weekly_physio_reports(athlete_id, week_start);

CREATE TABLE IF NOT EXISTS physical_assessments (
    assessment_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL UNIQUE,
    assessment_date TEXT,
    sport TEXT,
    category TEXT,
    protocol TEXT,
    evaluator TEXT,
    raw_values_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id),
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id)
);

CREATE TABLE IF NOT EXISTS physical_assessment_metrics (
    metric_id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    unit TEXT,
    side TEXT,
    raw_value TEXT,
    FOREIGN KEY (assessment_id) REFERENCES physical_assessments(assessment_id)
);

CREATE TABLE IF NOT EXISTS athlete_psr_baselines (
    baseline_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    mean_value REAL NOT NULL,
    min_value REAL,
    max_value REAL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_athlete_psr_baselines_unique
ON athlete_psr_baselines(athlete_id, metric_name);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    reference_date TEXT,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    human_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_lookup
ON alerts(athlete_id, alert_type, reference_date, status);

CREATE TABLE IF NOT EXISTS alert_reviews (
    alert_review_id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL,
    episode_id TEXT,
    review_status TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (alert_id) REFERENCES alerts(alert_id),
    FOREIGN KEY (episode_id) REFERENCES alert_episodes(episode_id)
);

CREATE TABLE IF NOT EXISTS alert_episodes (
    episode_id TEXT PRIMARY KEY,
    episode_key TEXT NOT NULL UNIQUE,
    athlete_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    episode_status TEXT NOT NULL,
    current_severity TEXT NOT NULL,
    peak_severity TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    consecutive_days INTEGER NOT NULL DEFAULT 0,
    novelty_status TEXT NOT NULL,
    priority_score REAL NOT NULL DEFAULT 0,
    evidence_json TEXT NOT NULL,
    last_reported_at TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id)
);

CREATE INDEX IF NOT EXISTS idx_alert_episodes_status
ON alert_episodes(episode_status, novelty_status, priority_score);

CREATE INDEX IF NOT EXISTS idx_alert_episodes_lookup
ON alert_episodes(athlete_id, alert_type, episode_status);

CREATE TABLE IF NOT EXISTS report_runs (
    report_run_id TEXT PRIMARY KEY,
    pipeline_run_id TEXT,
    report_type TEXT NOT NULL,
    reference_date TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    status TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    deterministic_path TEXT,
    enriched_path TEXT,
    llm_run_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(run_id),
    FOREIGN KEY (llm_run_id) REFERENCES llm_generations(generation_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_report_runs_unique
ON report_runs(report_type, reference_date);

CREATE TABLE IF NOT EXISTS report_items (
    report_item_id TEXT PRIMARY KEY,
    report_run_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    athlete_id TEXT,
    episode_id TEXT,
    alert_id TEXT,
    finding_id TEXT,
    source_record_id TEXT,
    priority_bucket TEXT NOT NULL,
    priority_score REAL NOT NULL DEFAULT 0,
    headline TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    included_in_main_brief INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (report_run_id) REFERENCES report_runs(report_run_id),
    FOREIGN KEY (athlete_id) REFERENCES athletes(athlete_id),
    FOREIGN KEY (episode_id) REFERENCES alert_episodes(episode_id),
    FOREIGN KEY (alert_id) REFERENCES alerts(alert_id),
    FOREIGN KEY (finding_id) REFERENCES data_quality_findings(finding_id),
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_report_items_run
ON report_items(report_run_id, display_order);

CREATE TABLE IF NOT EXISTS data_quality_findings (
    finding_id TEXT PRIMARY KEY,
    finding_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    human_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_data_quality_findings_lookup
ON data_quality_findings(finding_type, status, severity);

CREATE TABLE IF NOT EXISTS date_quality_reviews (
    review_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    source_record_id TEXT,
    decision TEXT NOT NULL,
    original_value TEXT,
    corrected_date TEXT,
    reviewed_by TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    notes TEXT,
    evidence_json TEXT NOT NULL,
    FOREIGN KEY (finding_id) REFERENCES data_quality_findings(finding_id),
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_date_quality_reviews_finding
ON date_quality_reviews(finding_id, reviewed_at);

CREATE TABLE IF NOT EXISTS duplicate_quality_reviews (
    review_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    notes TEXT,
    evidence_json TEXT NOT NULL,
    FOREIGN KEY (finding_id) REFERENCES data_quality_findings(finding_id)
);

CREATE INDEX IF NOT EXISTS idx_duplicate_quality_reviews_finding
ON duplicate_quality_reviews(finding_id, reviewed_at);

CREATE TABLE IF NOT EXISTS date_overrides (
    override_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    source_record_id TEXT,
    field_name TEXT NOT NULL,
    original_value TEXT,
    corrected_value TEXT,
    override_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    finding_id TEXT,
    FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id),
    FOREIGN KEY (finding_id) REFERENCES data_quality_findings(finding_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_date_overrides_entity_field
ON date_overrides(entity_type, entity_id, field_name);

CREATE TABLE IF NOT EXISTS llm_generations (
    generation_id TEXT PRIMARY KEY,
    generation_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    prompt_json TEXT NOT NULL,
    output_text TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_generations_type
ON llm_generations(generation_type, created_at);

CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors_json TEXT,
    publication_year INTEGER,
    journal TEXT,
    doi TEXT,
    url TEXT,
    abstract TEXT,
    citation_count INTEGER,
    citation_count_checked_at TEXT,
    source_provider TEXT
);

DROP INDEX IF EXISTS idx_papers_doi;

CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi
ON papers(LOWER(doi))
WHERE doi IS NOT NULL AND TRIM(doi) != '';

CREATE TABLE IF NOT EXISTS paper_topics (
    paper_topic_id TEXT PRIMARY KEY,
    paper_id TEXT,
    topic TEXT NOT NULL,
    sport TEXT,
    body_region TEXT,
    relevance_score REAL,
    reason_selected TEXT NOT NULL,
    human_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_topics_status
ON paper_topics(human_status, topic);

CREATE TABLE IF NOT EXISTS paper_topic_reviews (
    review_id TEXT PRIMARY KEY,
    paper_topic_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (paper_topic_id) REFERENCES paper_topics(paper_topic_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_topic_reviews_topic
ON paper_topic_reviews(paper_topic_id, reviewed_at);

CREATE TABLE IF NOT EXISTS literature_search_topics (
    topic_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    source_alert_type TEXT,
    source_count INTEGER NOT NULL,
    priority INTEGER NOT NULL,
    reason_selected TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_literature_search_topics_unique
ON literature_search_topics(topic, COALESCE(source_alert_type, ''));

CREATE TABLE IF NOT EXISTS literature_search_runs (
    search_run_id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    query TEXT NOT NULL,
    searched_at TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    FOREIGN KEY (topic_id) REFERENCES literature_search_topics(topic_id)
);

CREATE INDEX IF NOT EXISTS idx_literature_search_runs_topic
ON literature_search_runs(topic_id, searched_at);
"""


def connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    # FastAPI serves dashboard requests in parallel. Schema setup must be a
    # single write operation; ordinary reads should never compete for it.
    with _SCHEMA_INITIALIZATION_LOCK:
        if _database_schema_version(connection) >= SCHEMA_VERSION:
            return
        connection.executescript(SCHEMA)
        _apply_lightweight_migrations(connection)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()


def _database_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row is not None else 0


def _apply_lightweight_migrations(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(alert_reviews)").fetchall()
    }
    if "episode_id" not in columns:
        connection.execute("ALTER TABLE alert_reviews ADD COLUMN episode_id TEXT")
