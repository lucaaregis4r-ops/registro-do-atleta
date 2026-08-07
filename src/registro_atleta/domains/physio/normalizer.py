from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from uuid import uuid4

from registro_atleta.domains.common import auto_matched_records, normalize_header, payload_values, source_row_sheet
from registro_atleta.ingestion.snapshots import utc_now


@dataclass
class PhysioBuildResult:
    weekly_created: int = 0
    weekly_updated: int = 0
    events_created: int = 0
    events_updated: int = 0
    skipped_without_identity: int = 0


def build_physio_records(connection: sqlite3.Connection) -> PhysioBuildResult:
    athlete_by_record = auto_matched_records(connection)
    header_cache = _header_cache(connection)
    result = PhysioBuildResult()
    now = utc_now()
    rows = connection.execute(
        """
        SELECT source_record_id, source_id, raw_payload_json
        FROM source_records
        WHERE is_current = 1
          AND (
            source_id = 'operational_source_a'
            OR source_id LIKE '%report_semanal%'
            OR source_id LIKE '%controle_de_atletas_em_reabilita%'
          )
        ORDER BY source_id, source_row_key
        """
    ).fetchall()
    for row in rows:
        athlete_id = athlete_by_record.get(row["source_record_id"])
        if athlete_id is None:
            result.skipped_without_identity += 1
            continue
        payload = payload_values(row)
        normalized = _normalize_physio_payload(payload, row["source_id"], header_cache)
        if normalized is None or not normalized["injury_raw"]:
            continue
        raw_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if row["source_id"] == "operational_source_a" or "controle_de_atletas_em_reabilita" in row["source_id"]:
            case_id = _ensure_case(connection, athlete_id, normalized, now)
            created = _upsert_event(connection, row["source_record_id"], athlete_id, case_id, normalized, raw_json, now)
            result.events_created += 1 if created else 0
            result.events_updated += 0 if created else 1
        else:
            created = _upsert_weekly_report(connection, row["source_record_id"], athlete_id, normalized, raw_json, now)
            result.weekly_created += 1 if created else 0
            result.weekly_updated += 0 if created else 1
    return result


def _header_cache(connection: sqlite3.Connection) -> dict[tuple[str, str], dict[str, int]]:
    rows = connection.execute(
        """
        SELECT source_id, raw_payload_json
        FROM source_records
        WHERE is_current = 1
          AND (source_id LIKE '%report_semanal%' OR source_id LIKE '%controle_de_atletas_em_reabilita%')
        """
    ).fetchall()
    cache: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        payload = payload_values(row)
        values = payload.get("values")
        sheet = str(payload.get("sheet", ""))
        if isinstance(values, list):
            headers = {normalize_header(str(value)): index for index, value in enumerate(values)}
            if "NOME" in headers or "ATLETA" in headers:
                cache[(row["source_id"], sheet)] = headers
    return cache


def _normalize_physio_payload(payload: dict, source_id: str, headers: dict[tuple[str, str], dict[str, int]]) -> dict | None:
    values = payload.get("values")
    if isinstance(values, dict):
        return {
            "sport": None,
            "category": _dict_get(values, "CATEGORIA"),
            "injury_raw": _dict_get(values, "LESÃO"),
            "severity": _dict_get(values, "GRAVIDADE"),
            "treatment_phase": _dict_get(values, "FASE DO TRATAMENTO"),
            "training_restriction": _dict_get(values, "VETO TREINO"),
            "physical_training_restriction": _dict_get(values, "VETO PF"),
            "observations": _dict_get(values, "OBSERVAÇÕES"),
            "event_type": "operational_physio",
        }
    if isinstance(values, list):
        sheet = source_row_sheet(payload) or ""
        sheet_headers = headers.get((source_id, sheet))
        if not sheet_headers:
            return None
        return {
            "sport": sheet.title() if sheet else None,
            "category": _list_get(values, sheet_headers, "CATEGORIA"),
            "injury_raw": _list_get(values, sheet_headers, "LESAO") or _list_get(values, sheet_headers, "DIAGNOSTICO FISIOTERAPEUTICO"),
            "severity": _list_get(values, sheet_headers, "GRAVIDADE"),
            "treatment_phase": _list_get(values, sheet_headers, "FASE DO TRATAMENTO"),
            "training_restriction": _list_get(values, sheet_headers, "VETO TREINO") or _list_get(values, sheet_headers, "VETADO DE TREINO TECNICO TATICO"),
            "physical_training_restriction": _list_get(values, sheet_headers, "VETO PF") or _list_get(values, sheet_headers, "VETADO DE PREPARACAO FISICA"),
            "observations": _list_get(values, sheet_headers, "OBSERVACOES"),
            "event_type": "weekly_report" if "report_semanal" in source_id else "rehab_control",
        }
    return None


def _upsert_weekly_report(
    connection: sqlite3.Connection,
    source_record_id: str,
    athlete_id: str,
    normalized: dict,
    raw_json: str,
    now: str,
) -> bool:
    existing = connection.execute(
        "SELECT weekly_report_id FROM weekly_physio_reports WHERE source_record_id = ?",
        (source_record_id,),
    ).fetchone()
    values = (
        athlete_id,
        source_record_id,
        None,
        None,
        normalized["sport"],
        normalized["category"],
        normalized["injury_raw"],
        normalized["severity"],
        normalized["treatment_phase"],
        normalized["observations"],
        normalized["training_restriction"],
        normalized["physical_training_restriction"],
        raw_json,
    )
    if existing:
        connection.execute(
            """
            UPDATE weekly_physio_reports
            SET athlete_id = ?, week_start = ?, week_end = ?, sport = ?, category = ?, injury_raw = ?,
                severity = ?, treatment_phase = ?, observations = ?, training_restriction = ?,
                physical_training_restriction = ?, raw_values_json = ?
            WHERE source_record_id = ?
            """,
            (
                athlete_id,
                None,
                None,
                normalized["sport"],
                normalized["category"],
                normalized["injury_raw"],
                normalized["severity"],
                normalized["treatment_phase"],
                normalized["observations"],
                normalized["training_restriction"],
                normalized["physical_training_restriction"],
                raw_json,
                source_record_id,
            ),
        )
        return False
    connection.execute(
        """
        INSERT INTO weekly_physio_reports
        (weekly_report_id, athlete_id, source_record_id, week_start, week_end, sport, category,
         injury_raw, severity, treatment_phase, observations, training_restriction,
         physical_training_restriction, raw_values_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid4().hex, *values, now),
    )
    return True


def _upsert_event(
    connection: sqlite3.Connection,
    source_record_id: str,
    athlete_id: str,
    case_id: str | None,
    normalized: dict,
    raw_json: str,
    now: str,
) -> bool:
    existing = connection.execute(
        "SELECT event_id FROM physio_case_events WHERE source_record_id = ?",
        (source_record_id,),
    ).fetchone()
    if existing:
        connection.execute(
            """
            UPDATE physio_case_events
            SET case_id = ?, athlete_id = ?, event_type = ?, treatment_phase = ?, training_restriction = ?,
                physical_training_restriction = ?, severity = ?, notes = ?, raw_values_json = ?
            WHERE source_record_id = ?
            """,
            (
                case_id,
                athlete_id,
                normalized["event_type"],
                normalized["treatment_phase"],
                normalized["training_restriction"],
                normalized["physical_training_restriction"],
                normalized["severity"],
                normalized["observations"],
                raw_json,
                source_record_id,
            ),
        )
        return False
    connection.execute(
        """
        INSERT INTO physio_case_events
        (event_id, case_id, athlete_id, source_record_id, event_date, event_type, treatment_phase,
         training_restriction, physical_training_restriction, severity, notes, raw_values_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            case_id,
            athlete_id,
            source_record_id,
            None,
            normalized["event_type"],
            normalized["treatment_phase"],
            normalized["training_restriction"],
            normalized["physical_training_restriction"],
            normalized["severity"],
            normalized["observations"],
            raw_json,
            now,
        ),
    )
    return True


def _ensure_case(connection: sqlite3.Connection, athlete_id: str, normalized: dict, now: str) -> str | None:
    diagnosis = normalized.get("injury_raw")
    if not diagnosis:
        return None
    status = _case_status(normalized.get("treatment_phase"))
    existing = connection.execute(
        """
        SELECT case_id FROM physio_cases
        WHERE athlete_id = ? AND diagnosis_raw = ? AND current_status = ?
        LIMIT 1
        """,
        (athlete_id, diagnosis, status),
    ).fetchone()
    if existing:
        connection.execute(
            "UPDATE physio_cases SET updated_at = ? WHERE case_id = ?",
            (now, existing["case_id"]),
        )
        return existing["case_id"]
    case_id = uuid4().hex
    connection.execute(
        """
        INSERT INTO physio_cases
        (case_id, athlete_id, diagnosis_raw, body_region, laterality, opened_at, closed_at,
         current_status, responsible_professional, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            athlete_id,
            diagnosis,
            None,
            _laterality(diagnosis),
            None,
            now if status == "closed" else None,
            status,
            None,
            now,
            now,
        ),
    )
    return case_id


def _case_status(phase: object) -> str:
    text = str(phase or "").upper()
    if "ALTA" in text:
        return "closed"
    return "open"


def _laterality(text: str) -> str | None:
    upper = text.upper()
    if " D" in upper and " E" in upper:
        return "bilateral"
    if " D" in upper or " DIREIT" in upper:
        return "right"
    if " E" in upper or " ESQUERD" in upper:
        return "left"
    return None


def _dict_get(values: dict, key: str) -> str | None:
    value = values.get(key)
    text = str(value).strip() if value is not None else ""
    return text or None


def _list_get(values: list, headers: dict[str, int], key: str) -> str | None:
    index = headers.get(key)
    if index is None or index >= len(values):
        return None
    text = str(values[index]).strip()
    return text or None
