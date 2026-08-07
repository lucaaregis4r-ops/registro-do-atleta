from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from registro_atleta.quality.dates import effective_psr_dates_sql


DEFAULT_DATABASE = Path("data/database/registro_atleta.db")


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    metric: str
    detail: str
    required_action: str


@dataclass(frozen=True)
class Phase9ReadinessResult:
    overall_status: str
    models_allowed: bool
    checks: list[ReadinessCheck]
    metrics: dict[str, Any]
    report_path: Path
    json_path: Path


@dataclass(frozen=True)
class Phase9ExploratoryResult:
    status: str
    models_allowed: bool
    report_path: Path
    readiness_report_path: Path


def assess_phase9_readiness(root: Path, database_path: Path = DEFAULT_DATABASE) -> Phase9ReadinessResult:
    database_path = _resolve(root, database_path)
    generated_at = _utc_now()
    metrics = _collect_metrics(database_path)
    checks = _build_readiness_checks(root, metrics)
    models_allowed = all(check.status == "ready" for check in checks)
    overall_status = "ready" if models_allowed else "blocked"

    reports_dir = root / "data" / "reports" / "analytics"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = _file_stamp(generated_at)
    report_path = reports_dir / f"phase9-readiness-{stamp}.md"
    json_path = reports_dir / f"phase9-readiness-{stamp}.json"

    payload = {
        "generated_at": generated_at,
        "overall_status": overall_status,
        "models_allowed": models_allowed,
        "metrics": metrics,
        "checks": [check.__dict__ for check in checks],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    report_path.write_text(_render_readiness_markdown(payload), encoding="utf-8")

    return Phase9ReadinessResult(
        overall_status=overall_status,
        models_allowed=models_allowed,
        checks=checks,
        metrics=metrics,
        report_path=report_path,
        json_path=json_path,
    )


def build_phase9_exploratory_report(root: Path, database_path: Path = DEFAULT_DATABASE) -> Phase9ExploratoryResult:
    database_path = _resolve(root, database_path)
    readiness = assess_phase9_readiness(root, database_path)
    generated_at = _utc_now()
    metrics = _collect_exploratory_metrics(database_path)

    reports_dir = root / "data" / "reports" / "analytics"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"phase9-exploratory-{_file_stamp(generated_at)}.md"
    report_path.write_text(
        _render_exploratory_markdown(
            generated_at=generated_at,
            readiness=readiness,
            metrics=metrics,
        ),
        encoding="utf-8",
    )
    status = "advanced_models_blocked" if not readiness.models_allowed else "exploratory_ready"
    return Phase9ExploratoryResult(
        status=status,
        models_allowed=readiness.models_allowed,
        report_path=report_path,
        readiness_report_path=readiness.report_path,
    )


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_stamp(iso_value: str) -> str:
    return iso_value.replace("-", "").replace(":", "").replace(".", "").replace("Z", "Z").replace("+00:00", "Z")


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _scalar(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return connection.execute(sql, params).fetchone()[0]


def _collect_metrics(database_path: Path) -> dict[str, Any]:
    with _connect(database_path) as connection:
        psr_total = int(_scalar(connection, "SELECT COUNT(*) FROM psr_responses"))
        psr_excluded = int(
            _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM psr_responses p
                JOIN date_overrides do ON do.entity_type = 'psr_responses'
                    AND do.entity_id = p.psr_id
                    AND do.field_name = 'response_date'
                    AND do.override_status = 'excluded'
                """,
            )
        )
        psr_temporal_total = psr_total - psr_excluded
        psr_dated = _psr_effective_dated_count(connection)
        physio_events = int(_scalar(connection, "SELECT COUNT(*) FROM physio_case_events"))
        physio_events_dated = int(
            _scalar(
                connection,
                "SELECT COUNT(*) FROM physio_case_events WHERE event_date IS NOT NULL AND event_date != ''",
            )
        )
        physio_cases = int(_scalar(connection, "SELECT COUNT(*) FROM physio_cases"))
        physio_cases_opened = int(
            _scalar(
                connection,
                "SELECT COUNT(*) FROM physio_cases WHERE opened_at IS NOT NULL AND opened_at != ''",
            )
        )
        metrics = {
            "athletes": int(_scalar(connection, "SELECT COUNT(*) FROM athletes")),
            "pending_identity_candidates": int(
                _scalar(connection, "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'")
            ),
            "open_quality_findings": int(
                _scalar(connection, "SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open'")
            ),
            "open_date_quality_findings": int(
                _scalar(
                    connection,
                    """
                    SELECT COUNT(*)
                    FROM data_quality_findings
                    WHERE status = 'open'
                      AND (finding_type LIKE '%date%' OR human_summary LIKE '%data%')
                    """,
                )
            ),
            "psr_responses": psr_total,
            "psr_responses_excluded_by_date_override": psr_excluded,
            "psr_temporal_records": psr_temporal_total,
            "psr_responses_with_effective_date": psr_dated,
            "psr_date_coverage": _ratio(psr_dated, psr_temporal_total),
            "active_date_overrides": int(
                _scalar(connection, "SELECT COUNT(*) FROM date_overrides WHERE override_status IN ('active', 'excluded')")
            ),
            "physio_cases": physio_cases,
            "physio_cases_with_opened_at": physio_cases_opened,
            "physio_case_opened_at_coverage": _ratio(physio_cases_opened, physio_cases),
            "physio_events": physio_events,
            "physio_events_with_date": physio_events_dated,
            "physio_event_date_coverage": _ratio(physio_events_dated, physio_events),
            "physical_assessments": int(_scalar(connection, "SELECT COUNT(*) FROM physical_assessments")),
            "approved_literature_links": int(
                _scalar(connection, "SELECT COUNT(*) FROM paper_topic_reviews WHERE decision = 'approved'")
            ),
        }
    return metrics


def _build_readiness_checks(root: Path, metrics: dict[str, Any]) -> list[ReadinessCheck]:
    checks: list[ReadinessCheck] = []
    pending_identity = int(metrics["pending_identity_candidates"])
    date_findings = int(metrics["open_date_quality_findings"])
    psr_date_coverage = float(metrics["psr_date_coverage"])
    event_date_coverage = float(metrics["physio_event_date_coverage"])
    physio_events = int(metrics["physio_events"])
    physio_cases = int(metrics["physio_cases"])
    psr_total = int(metrics["psr_responses"])
    assessments = int(metrics["physical_assessments"])
    methodology_file = root / "docs" / "decisions" / "phase9_methodology_approved.md"

    checks.append(
        ReadinessCheck(
            name="identity_stability",
            status="ready" if pending_identity == 0 else "blocked",
            metric=f"{pending_identity} pending identity candidates",
            detail="Advanced longitudinal models require stable athlete identity.",
            required_action="Review and resolve all pending identity candidates before fitting Phase 9 models.",
        )
    )
    checks.append(
        ReadinessCheck(
            name="date_reliability",
            status="ready" if date_findings == 0 and psr_date_coverage >= 0.98 else "blocked",
            metric=f"{date_findings} open date findings; PSR date coverage {psr_date_coverage:.1%}",
            detail="Temporal models need reliable ordering and windows.",
            required_action="Resolve open date quality findings before temporal modelling.",
        )
    )
    checks.append(
        ReadinessCheck(
            name="event_definition",
            status="ready" if physio_cases > 0 and physio_events > 0 and event_date_coverage >= 0.80 else "blocked",
            metric=f"{physio_cases} physio cases; {physio_events} events; event date coverage {event_date_coverage:.1%}",
            detail="Phase 9 requires a dated and agreed event definition.",
            required_action="Define the modelling event and ensure physio events have usable dates.",
        )
    )
    checks.append(
        ReadinessCheck(
            name="data_volume",
            status="ready" if psr_total >= 1000 and physio_cases >= 20 and assessments >= 100 else "blocked",
            metric=f"{psr_total} PSR; {physio_cases} physio cases; {assessments} assessments",
            detail="The current database must have enough observations for exploratory model design.",
            required_action="Keep ingesting data or narrow the modelling question if volume is insufficient.",
        )
    )
    checks.append(
        ReadinessCheck(
            name="methodological_validation",
            status="ready" if methodology_file.exists() else "blocked",
            metric=f"approval file exists: {methodology_file.exists()}",
            detail="The plan requires methodological validation with the team.",
            required_action="Create docs/decisions/phase9_methodology_approved.md after team validation.",
        )
    )
    return checks


def _collect_exploratory_metrics(database_path: Path) -> dict[str, Any]:
    with _connect(database_path) as connection:
        psr_by_group = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    CASE
                        WHEN athlete_id IN (SELECT DISTINCT athlete_id FROM physio_cases) THEN 'with_physio_case'
                        ELSE 'without_physio_case'
                    END AS group_name,
                    COUNT(*) AS psr_count,
                    COUNT(DISTINCT athlete_id) AS athlete_count,
                    ROUND(AVG(pain_intensity), 2) AS avg_pain,
                    ROUND(AVG(fatigue_score), 2) AS avg_fatigue,
                    ROUND(AVG(sleep_score), 2) AS avg_sleep,
                    ROUND(AVG(muscle_soreness_score), 2) AS avg_soreness,
                    ROUND(AVG(stress_score), 2) AS avg_stress,
                    ROUND(AVG(mood_score), 2) AS avg_mood
                FROM psr_responses
                GROUP BY group_name
                ORDER BY group_name
                """
            )
        ]
        physio_events_by_type = [
            dict(row)
            for row in connection.execute(
                """
                SELECT event_type, COUNT(*) AS events
                FROM physio_case_events
                GROUP BY event_type
                ORDER BY events DESC, event_type
                """
            )
        ]
        alerts_by_type = [
            dict(row)
            for row in connection.execute(
                """
                SELECT alert_type, severity, COUNT(*) AS alerts
                FROM alerts
                GROUP BY alert_type, severity
                ORDER BY alerts DESC, alert_type, severity
                LIMIT 20
                """
            )
        ]
        summary = {
            "athletes_with_psr": int(_scalar(connection, "SELECT COUNT(DISTINCT athlete_id) FROM psr_responses")),
            "athletes_with_physio_case": int(_scalar(connection, "SELECT COUNT(DISTINCT athlete_id) FROM physio_cases")),
            "athletes_with_assessment": int(_scalar(connection, "SELECT COUNT(DISTINCT athlete_id) FROM physical_assessments")),
            "psr_first_date": _scalar(connection, f"SELECT MIN(effective_date) FROM ({_effective_psr_dates_sql()}) WHERE effective_date IS NOT NULL"),
            "psr_last_date": _scalar(connection, f"SELECT MAX(effective_date) FROM ({_effective_psr_dates_sql()}) WHERE effective_date IS NOT NULL"),
        }
    return {
        "summary": summary,
        "psr_by_physio_group": psr_by_group,
        "physio_events_by_type": physio_events_by_type,
        "alerts_by_type": alerts_by_type,
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _psr_effective_dated_count(connection: sqlite3.Connection) -> int:
    return int(
        _scalar(
            connection,
            f"""
            SELECT COUNT(*)
            FROM ({_effective_psr_dates_sql()})
            WHERE effective_date IS NOT NULL AND effective_date != ''
            """,
        )
    )


def _effective_psr_dates_sql() -> str:
    return f"SELECT psr_id, effective_response_date AS effective_date FROM ({effective_psr_dates_sql()})"


def _render_readiness_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 9 readiness gate",
        "",
        f"Generated at: {payload['generated_at']}",
        f"Overall status: **{payload['overall_status']}**",
        f"Advanced models allowed: **{payload['models_allowed']}**",
        "",
        "This gate implements the Phase 9 plan condition. If any prerequisite is blocked, advanced probabilistic modelling must not be treated as production evidence.",
        "",
        "## Checks",
        "",
        "| Check | Status | Metric | Required action |",
        "| --- | --- | --- | --- |",
    ]
    for check in payload["checks"]:
        lines.append(
            f"| {check['name']} | {check['status']} | {check['metric']} | {check['required_action']} |"
        )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "```json",
            json.dumps(payload["metrics"], ensure_ascii=True, indent=2),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _render_exploratory_markdown(
    generated_at: str,
    readiness: Phase9ReadinessResult,
    metrics: dict[str, Any],
) -> str:
    lines = [
        "# Phase 9 exploratory analytics",
        "",
        f"Generated at: {generated_at}",
        f"Readiness status: **{readiness.overall_status}**",
        f"Advanced models allowed: **{readiness.models_allowed}**",
        f"Readiness report: `{readiness.report_path}`",
        "",
        "This report is descriptive only. It is not a prediction model, clinical decision rule, causal estimate, or athlete-level risk score.",
        "",
    ]
    if not readiness.models_allowed:
        lines.extend(
            [
                "## Methodological lock",
                "",
                "Advanced Phase 9 models are blocked by the readiness gate. The sections below only summarize available data to support cleanup and model design.",
                "",
            ]
        )

    summary = metrics["summary"]
    lines.extend(
        [
            "## Coverage",
            "",
            f"- Athletes with PSR: {summary['athletes_with_psr']}",
            f"- Athletes with physio case: {summary['athletes_with_physio_case']}",
            f"- Athletes with physical assessment: {summary['athletes_with_assessment']}",
            f"- PSR date range: {summary['psr_first_date']} to {summary['psr_last_date']}",
            "",
            "## PSR by physio-case group",
            "",
            "| Group | Athletes | PSR | Avg pain | Avg fatigue | Avg sleep | Avg soreness | Avg stress | Avg mood |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in metrics["psr_by_physio_group"]:
        lines.append(
            "| {group_name} | {athlete_count} | {psr_count} | {avg_pain} | {avg_fatigue} | {avg_sleep} | {avg_soreness} | {avg_stress} | {avg_mood} |".format(
                **{key: _display(value) for key, value in row.items()}
            )
        )

    lines.extend(["", "## Physio events by type", "", "| Event type | Events |", "| --- | ---: |"])
    for row in metrics["physio_events_by_type"]:
        lines.append(f"| {_display(row['event_type'])} | {_display(row['events'])} |")

    lines.extend(["", "## Alerts by type", "", "| Alert type | Severity | Alerts |", "| --- | --- | ---: |"])
    for row in metrics["alerts_by_type"]:
        lines.append(f"| {_display(row['alert_type'])} | {_display(row['severity'])} | {_display(row['alerts'])} |")

    lines.extend(
        [
            "",
            "## Next modelling prerequisites",
            "",
            "- Resolve pending identity candidates.",
            "- Resolve open date quality findings.",
            "- Apply reviewed date overrides before temporal analysis.",
            "- Define and date the Phase 9 event, including distinction between immediate care, treatment, and injury.",
            "- Register team methodological approval before any probabilistic model is used.",
            "",
        ]
    )
    return "\n".join(lines)


def _display(value: Any) -> str:
    if value is None:
        return "-"
    return str(value).replace("|", "/")


def new_run_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
