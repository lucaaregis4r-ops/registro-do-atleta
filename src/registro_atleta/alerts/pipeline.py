from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now
from registro_atleta.quality.dates import effective_psr_dates_sql

RULE_VERSION = "phase4.1"


@dataclass
class AlertBuildResult:
    baselines_created: int = 0
    alerts_created: int = 0
    quality_findings_created: int = 0
    report_path: Path | None = None


def build_alerts(root: Path, database_path: Path | None = None) -> AlertBuildResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    result = AlertBuildResult()
    with connection:
        _reset_outputs(connection)
        result.baselines_created = _build_psr_baselines(connection)
        result.alerts_created += _build_high_pain_alerts(connection)
        result.alerts_created += _build_multi_wellness_alerts(connection)
        result.alerts_created += _build_individual_deviation_alerts(connection)
        result.alerts_created += _build_no_recent_psr_alerts(connection)
        result.alerts_created += _build_physio_restriction_alerts(connection)
        result.quality_findings_created += _build_quality_findings(connection)
    result.report_path = _write_report(root, result)
    connection.close()
    return result


def _reset_outputs(connection: sqlite3.Connection) -> None:
    connection.execute("UPDATE data_quality_findings SET status = 'superseded' WHERE status = 'open'")
    connection.execute("UPDATE alerts SET status = 'superseded' WHERE status = 'open'")
    connection.execute("DELETE FROM athlete_psr_baselines")


def _build_psr_baselines(connection: sqlite3.Connection) -> int:
    created = 0
    now = utc_now()
    for metric_name in ("fatigue_score", "sleep_score", "muscle_soreness_score", "stress_score", "mood_score", "pain_intensity"):
        rows = connection.execute(
            f"""
            SELECT athlete_id, COUNT({metric_name}) sample_size, AVG({metric_name}) mean_value,
                   MIN({metric_name}) min_value, MAX({metric_name}) max_value
            FROM ({effective_psr_dates_sql()})
            WHERE {metric_name} IS NOT NULL
              AND effective_response_date >= '2026-01-01'
              AND effective_response_date <= ?
            GROUP BY athlete_id
            HAVING COUNT({metric_name}) >= 8
            """,
            (_today_iso(),),
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                INSERT INTO athlete_psr_baselines
                (baseline_id, athlete_id, metric_name, sample_size, mean_value, min_value, max_value, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid4().hex, row["athlete_id"], metric_name, row["sample_size"], row["mean_value"], row["min_value"], row["max_value"], now),
            )
            created += 1
    return created


def _build_high_pain_alerts(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        f"""
        SELECT psr_id, athlete_id, response_date, effective_response_date, pain_intensity, pain_location_raw,
               date_override_status, date_corrected_value
        FROM ({effective_psr_dates_sql()})
        WHERE pain_intensity >= 6 AND effective_response_date >= '2026-01-01' AND effective_response_date <= ?
        """,
        (_today_iso(),),
    ).fetchall()
    for row in rows:
        reference_date = row["effective_response_date"]
        _insert_alert(
            connection,
            row["athlete_id"],
            "psr_high_pain",
            reference_date,
            "high" if row["pain_intensity"] >= 8 else "medium",
            {
                "psr_id": row["psr_id"],
                "pain_intensity": row["pain_intensity"],
                "pain_location_raw": row["pain_location_raw"],
                "original_response_date": row["response_date"],
                "effective_response_date": reference_date,
                "date_override_status": row["date_override_status"],
                "rule": "pain_intensity >= 6",
            },
            f"PSR com dor {row['pain_intensity']} em {reference_date}.",
        )
    return len(rows)


def _build_multi_wellness_alerts(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        f"""
        SELECT psr_id, athlete_id, response_date, effective_response_date, fatigue_score, sleep_score,
               muscle_soreness_score, stress_score, mood_score
        FROM ({effective_psr_dates_sql()})
        WHERE effective_response_date >= '2026-01-01' AND effective_response_date <= ?
        """,
        (_today_iso(),),
    ).fetchall()
    count = 0
    for row in rows:
        scores = {
            "fatigue": row["fatigue_score"],
            "sleep": row["sleep_score"],
            "muscle_soreness": row["muscle_soreness_score"],
            "stress": row["stress_score"],
            "mood": row["mood_score"],
        }
        flagged = {key: value for key, value in scores.items() if value is not None and value >= 4}
        if len(flagged) < 3:
            continue
        _insert_alert(
            connection,
            row["athlete_id"],
            "psr_multi_wellness_flag",
            row["effective_response_date"],
            "medium",
            {"psr_id": row["psr_id"], "flagged_scores": flagged, "original_response_date": row["response_date"], "effective_response_date": row["effective_response_date"], "rule": "3 or more wellbeing dimensions >= 4"},
            f"PSR com {len(flagged)} dimensoes de bem-estar elevadas em {row['effective_response_date']}.",
        )
        count += 1
    return count


def _build_individual_deviation_alerts(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        f"""
        SELECT p.psr_id, p.athlete_id, p.response_date, p.effective_response_date, p.fatigue_score, b.mean_value, b.sample_size
        FROM ({effective_psr_dates_sql()}) p
        JOIN athlete_psr_baselines b ON b.athlete_id = p.athlete_id AND b.metric_name = 'fatigue_score'
        WHERE p.fatigue_score IS NOT NULL
          AND p.effective_response_date >= '2026-01-01'
          AND p.effective_response_date <= ?
          AND p.fatigue_score >= b.mean_value + 1.5
          AND p.fatigue_score >= 4
        """,
        (_today_iso(),),
    ).fetchall()
    for row in rows:
        _insert_alert(
            connection,
            row["athlete_id"],
            "psr_fatigue_above_individual_baseline",
            row["effective_response_date"],
            "medium",
            {"psr_id": row["psr_id"], "fatigue_score": row["fatigue_score"], "baseline_mean": row["mean_value"], "baseline_sample_size": row["sample_size"], "original_response_date": row["response_date"], "effective_response_date": row["effective_response_date"], "rule": "fatigue >= mean + 1.5 and fatigue >= 4, sample >= 8"},
            f"Fadiga acima do baseline individual em {row['effective_response_date']}.",
        )
    return len(rows)


def _build_no_recent_psr_alerts(connection: sqlite3.Connection) -> int:
    reference = min(_max_valid_psr_date(connection), date.today())
    cutoff = (reference - timedelta(days=14)).isoformat()
    rows = connection.execute(
        f"""
        SELECT a.athlete_id, MAX(p.effective_response_date) last_response
        FROM athletes a
        JOIN ({effective_psr_dates_sql()}) p ON p.athlete_id = a.athlete_id
        WHERE p.effective_response_date >= '2026-01-01' AND p.effective_response_date <= ?
        GROUP BY a.athlete_id
        HAVING MAX(p.effective_response_date) < ?
        """,
        (reference.isoformat(), cutoff),
    ).fetchall()
    for row in rows:
        _insert_alert(
            connection,
            row["athlete_id"],
            "psr_no_recent_response",
            reference.isoformat(),
            "low",
            {"last_response": row["last_response"], "cutoff": cutoff, "rule": "last PSR response older than 14 days"},
            f"Atleta sem PSR desde {row['last_response']}.",
        )
    return len(rows)


def _build_physio_restriction_alerts(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        """
        SELECT event_id, athlete_id, event_type, training_restriction,
               physical_training_restriction, severity, treatment_phase
        FROM physio_case_events
        WHERE UPPER(COALESCE(training_restriction, '')) LIKE '%SIM%'
           OR UPPER(COALESCE(physical_training_restriction, '')) LIKE '%SIM%'
           OR UPPER(COALESCE(severity, '')) = 'VERMELHO'
        """
    ).fetchall()
    for row in rows:
        _insert_alert(
            connection,
            row["athlete_id"],
            "physio_training_restriction",
            _today_iso(),
            "high" if str(row["severity"]).upper() == "VERMELHO" else "medium",
            {"event_id": row["event_id"], "event_type": row["event_type"], "training_restriction": row["training_restriction"], "physical_training_restriction": row["physical_training_restriction"], "severity": row["severity"], "treatment_phase": row["treatment_phase"], "rule": "technical or physical training restriction, or red severity"},
            "Fisioterapia com restricao de treino ou gravidade alta.",
        )
    return len(rows)


def _build_quality_findings(connection: sqlite3.Connection) -> int:
    now = utc_now()
    findings = [
        ("psr_without_identity", "source_records", None, "medium", {"count": _count_psr_without_identity(connection)}, "Registros de PSR preservados sem identidade segura."),
        ("identity_pending_review", "identity_candidates", None, "medium", {"count": _count_identity_pending(connection)}, "Candidatos de identidade aguardando revisao humana."),
    ]
    invalid_dates = connection.execute(
        f"""
        SELECT psr_id, athlete_id, response_date, effective_response_date, date_override_status
        FROM ({effective_psr_dates_sql()})
        WHERE date_override_status IS NULL
          AND (response_date IS NULL OR response_date < '2026-01-01' OR response_date > ?)
        """,
        (_today_iso(),),
    ).fetchall()
    for row in invalid_dates:
        findings.append(("psr_invalid_or_future_date", "psr_responses", row["psr_id"], "high", {"athlete_id": row["athlete_id"], "response_date": row["response_date"]}, "PSR com data ausente, invalida ou futura."))
    for finding_type, entity_type, entity_id, severity, evidence, summary in findings:
        connection.execute(
            """
            INSERT INTO data_quality_findings
            (finding_id, finding_type, entity_type, entity_id, severity, status, evidence_json, human_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid4().hex, finding_type, entity_type, entity_id, severity, "open", json.dumps(evidence, ensure_ascii=False, sort_keys=True), summary, now),
        )
    return len(findings)


def _insert_alert(connection: sqlite3.Connection, athlete_id: str, alert_type: str, reference_date: str | None, severity: str, evidence: dict, summary: str) -> None:
    connection.execute(
        """
        INSERT INTO alerts
        (alert_id, athlete_id, alert_type, reference_date, severity, status, rule_version, evidence_json, human_summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid4().hex, athlete_id, alert_type, reference_date, severity, "open", RULE_VERSION, json.dumps(evidence, ensure_ascii=False, sort_keys=True), summary, utc_now()),
    )


def _today_iso() -> str:
    return date.today().isoformat()


def _max_valid_psr_date(connection: sqlite3.Connection) -> date:
    value = connection.execute(
        f"SELECT MAX(effective_response_date) FROM ({effective_psr_dates_sql()}) WHERE effective_response_date >= '2026-01-01' AND effective_response_date <= ?",
        (_today_iso(),),
    ).fetchone()[0]
    return datetime.strptime(value, "%Y-%m-%d").date() if value else date.today()


def _count_psr_without_identity(connection: sqlite3.Connection) -> int:
    return connection.execute(
        """
        SELECT COUNT(*)
        FROM source_records sr
        LEFT JOIN identity_candidates ic ON ic.source_record_id = sr.source_record_id
        WHERE sr.is_current = 1
          AND (sr.source_id = 'psr_2026_online' OR sr.source_id LIKE '%chamada_psr%')
          AND COALESCE(ic.decision_status, '') != 'auto_matched'
        """
    ).fetchone()[0]


def _count_identity_pending(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'").fetchone()[0]


def _write_report(root: Path, result: AlertBuildResult) -> Path:
    report_dir = root / "data" / "reports" / "alerts"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"alerts-{utc_now().replace(':', '').replace('+', 'Z')}.md"
    lines = [
        "# Relatorio De Alertas",
        "",
        f"- baselines_criados: `{result.baselines_created}`",
        f"- alertas_criados: `{result.alerts_created}`",
        f"- achados_qualidade_criados: `{result.quality_findings_created}`",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
