from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from uuid import uuid4

from registro_atleta.domains.common import number_value, payload_values
from registro_atleta.ingestion.snapshots import utc_now


METRIC_HEADERS = {
    "Altura": ("Altura", "cm"),
    "Massa corporal [kg]": ("Massa corporal", "kg"),
    "% gordura": ("% gordura", "%"),
    "Massa gordura [kg]": ("Massa gordura", "kg"),
    "Massa livre gordura [kg]": ("Massa livre gordura", "kg"),
    "1RM agachamento [kg]": ("1RM agachamento", "kg"),
    "1RM supino [kg]": ("1RM supino", "kg"),
    "Força relativa agachamento": ("Forca relativa agachamento", None),
    "Força relativa supino": ("Forca relativa supino", None),
    "SJ [cm]": ("SJ", "cm"),
    "CMJ [cm]": ("CMJ", "cm"),
    "Taxa utilização excêntrica": ("Taxa utilizacao excentrica", None),
}


@dataclass
class AssessmentBuildResult:
    assessments_created: int = 0
    assessments_updated: int = 0
    metrics_created: int = 0
    metrics_replaced: int = 0
    skipped_without_identity: int = 0


def build_physical_assessments(connection: sqlite3.Connection) -> AssessmentBuildResult:
    result = AssessmentBuildResult()
    header = _occurrence_header(connection)
    if not header:
        return result
    now = utc_now()
    rows = connection.execute(
        """
        SELECT source_record_id, raw_payload_json
        FROM source_records
        WHERE is_current = 1
          AND source_id LIKE 'historical_registro_atletas_demo%'
          AND json_extract(raw_payload_json, '$.sheet') = 'Ocorrencias_por_Fonte'
        ORDER BY source_row_key
        """
    ).fetchall()
    for row in rows:
        payload = payload_values(row)
        values = payload.get("values")
        if not isinstance(values, list) or _value(values, header, "Tipo") != "Caracterização":
            continue
        athlete_id = _map_seed_id(connection, _value(values, header, "ID_Atleta"))
        if athlete_id is None:
            result.skipped_without_identity += 1
            continue
        metrics = _metrics_from_values(values, header)
        if not metrics:
            continue
        assessment_id, created = _upsert_assessment(connection, row["source_record_id"], athlete_id, values, header, payload, now)
        if created:
            result.assessments_created += 1
        else:
            result.assessments_updated += 1
            result.metrics_replaced += connection.execute(
                "SELECT COUNT(*) FROM physical_assessment_metrics WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()[0]
            connection.execute("DELETE FROM physical_assessment_metrics WHERE assessment_id = ?", (assessment_id,))
        for metric_name, unit, raw_value, metric_value in metrics:
            connection.execute(
                """
                INSERT INTO physical_assessment_metrics
                (metric_id, assessment_id, metric_name, metric_value, unit, side, raw_value)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid4().hex, assessment_id, metric_name, metric_value, unit, None, raw_value),
            )
            result.metrics_created += 1
    return result


def _occurrence_header(connection: sqlite3.Connection) -> dict[str, int]:
    row = connection.execute(
        """
        SELECT raw_payload_json
        FROM source_records
        WHERE is_current = 1
          AND source_id LIKE 'historical_registro_atletas_demo%'
          AND json_extract(raw_payload_json, '$.sheet') = 'Ocorrencias_por_Fonte'
          AND json_extract(raw_payload_json, '$.row_number') = 1
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return {}
    values = payload_values(row).get("values", [])
    return {str(value): index for index, value in enumerate(values) if str(value).strip()}


def _map_seed_id(connection: sqlite3.Connection, seed_id: str | None) -> str | None:
    if not seed_id:
        return None
    row = connection.execute(
        """
        SELECT athlete_id
        FROM athletes
        ORDER BY athlete_id
        LIMIT 1 OFFSET ?
        """,
        (int(seed_id.replace("ATH-", "")) - 1,),
    ).fetchone() if seed_id.startswith("ATH-") else None
    return row["athlete_id"] if row else None


def _metrics_from_values(values: list, header: dict[str, int]) -> list[tuple[str, str | None, str, float | None]]:
    metrics: list[tuple[str, str | None, str, float | None]] = []
    for source_name, (metric_name, unit) in METRIC_HEADERS.items():
        raw = _value(values, header, source_name)
        if raw is None:
            continue
        text = raw.strip()
        if not text:
            continue
        metrics.append((metric_name, unit, text, number_value(text)))
    return metrics


def _upsert_assessment(
    connection: sqlite3.Connection,
    source_record_id: str,
    athlete_id: str,
    values: list,
    header: dict[str, int],
    payload: dict,
    now: str,
) -> tuple[str, bool]:
    existing = connection.execute(
        "SELECT assessment_id FROM physical_assessments WHERE source_record_id = ?",
        (source_record_id,),
    ).fetchone()
    sport = _value(values, header, "Modalidade")
    category = _value(values, header, "Categoria")
    raw_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if existing:
        connection.execute(
            """
            UPDATE physical_assessments
            SET athlete_id = ?, sport = ?, category = ?, protocol = ?, raw_values_json = ?
            WHERE assessment_id = ?
            """,
            (athlete_id, sport, category, "legacy_characterization_seed", raw_json, existing["assessment_id"]),
        )
        return existing["assessment_id"], False
    assessment_id = uuid4().hex
    connection.execute(
        """
        INSERT INTO physical_assessments
        (assessment_id, athlete_id, source_record_id, assessment_date, sport, category, protocol,
         evaluator, raw_values_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assessment_id,
            athlete_id,
            source_record_id,
            None,
            sport,
            category,
            "legacy_characterization_seed",
            None,
            raw_json,
            now,
        ),
    )
    return assessment_id, True


def _value(values: list, header: dict[str, int], key: str) -> str | None:
    index = header.get(key)
    if index is None or index >= len(values):
        return None
    text = str(values[index]).strip()
    return text or None
