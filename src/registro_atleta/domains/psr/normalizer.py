from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from uuid import uuid4

from registro_atleta.domains.common import (
    auto_matched_records,
    first_score,
    normalize_header,
    number_value,
    parse_date,
    parse_datetime,
    payload_values,
    sport_from_category,
)
from registro_atleta.ingestion.snapshots import utc_now


@dataclass
class PsrBuildResult:
    created: int = 0
    updated: int = 0
    skipped_without_identity: int = 0


def build_psr_responses(connection: sqlite3.Connection) -> PsrBuildResult:
    athlete_by_record = auto_matched_records(connection)
    headers = _header_cache(connection)
    result = PsrBuildResult()
    rows = connection.execute(
        """
        SELECT source_record_id, source_id, raw_payload_json
        FROM source_records
        WHERE is_current = 1
          AND (source_id = 'psr_2026_online' OR source_id LIKE '%chamada_psr%')
        ORDER BY source_id, source_row_key
        """
    ).fetchall()
    now = utc_now()
    for row in rows:
        athlete_id = athlete_by_record.get(row["source_record_id"])
        if athlete_id is None:
            result.skipped_without_identity += 1
            continue
        payload = payload_values(row)
        normalized = _normalize_psr_payload(payload, row["source_id"], headers)
        if normalized is None:
            continue
        existing = connection.execute(
            "SELECT psr_id FROM psr_responses WHERE source_record_id = ?",
            (row["source_record_id"],),
        ).fetchone()
        values = (
            athlete_id,
            row["source_record_id"],
            normalized["submitted_at"],
            normalized["response_date"],
            normalized["sport"],
            normalized["category"],
            normalized["pain_location_raw"],
            normalized["pain_intensity"],
            normalized["fatigue_score"],
            normalized["sleep_score"],
            normalized["muscle_soreness_score"],
            normalized["stress_score"],
            normalized["mood_score"],
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            now,
        )
        if existing:
            connection.execute(
                """
                UPDATE psr_responses
                SET athlete_id = ?, submitted_at = ?, response_date = ?, sport = ?, category = ?,
                    pain_location_raw = ?, pain_intensity = ?, fatigue_score = ?, sleep_score = ?,
                    muscle_soreness_score = ?, stress_score = ?, mood_score = ?, raw_values_json = ?
                WHERE source_record_id = ?
                """,
                (
                    athlete_id,
                    normalized["submitted_at"],
                    normalized["response_date"],
                    normalized["sport"],
                    normalized["category"],
                    normalized["pain_location_raw"],
                    normalized["pain_intensity"],
                    normalized["fatigue_score"],
                    normalized["sleep_score"],
                    normalized["muscle_soreness_score"],
                    normalized["stress_score"],
                    normalized["mood_score"],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    row["source_record_id"],
                ),
            )
            result.updated += 1
        else:
            connection.execute(
                """
                INSERT INTO psr_responses
                (psr_id, athlete_id, source_record_id, submitted_at, response_date, sport, category,
                 pain_location_raw, pain_intensity, fatigue_score, sleep_score, muscle_soreness_score,
                 stress_score, mood_score, raw_values_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid4().hex, *values),
            )
            result.created += 1
    return result


def _header_cache(connection: sqlite3.Connection) -> dict[tuple[str, str], dict[str, int]]:
    rows = connection.execute(
        """
        SELECT source_id, raw_payload_json
        FROM source_records
        WHERE is_current = 1 AND source_id LIKE '%chamada_psr%'
        """
    ).fetchall()
    cache: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        payload = payload_values(row)
        values = payload.get("values")
        sheet = str(payload.get("sheet", ""))
        if isinstance(values, list) and values and normalize_header(str(values[0])) == "CARIMBO DE DATA HORA":
            cache[(row["source_id"], sheet)] = {normalize_header(str(value)): index for index, value in enumerate(values)}
    return cache


def _normalize_psr_payload(payload: dict, source_id: str, headers: dict[tuple[str, str], dict[str, int]]) -> dict | None:
    values = payload.get("values")
    if isinstance(values, dict):
        category = _dict_get(values, "CATEGORIA")
        submitted_at = parse_datetime(_dict_get(values, "Carimbo de data/hora"))
        return {
            "submitted_at": submitted_at,
            "response_date": _canonical_response_date(
                submitted_at,
                _dict_get(values, "DATA DE HOJE"),
            ),
            "sport": sport_from_category(category),
            "category": category,
            "pain_location_raw": _dict_get(values, "Se você sente DOR MUSCULAR em algum dos locais marcados na imagem abaixo, escreva o número correspondente ao local."),
            "pain_intensity": number_value(_dict_get(values, "De 0 a 10, qual o nível da dor de acordo com a escala abaixo?")),
            "fatigue_score": first_score(_dict_get(values, "QUESTIONÁRIO DE BEM ESTAR [FADIGA]")),
            "sleep_score": first_score(_dict_get(values, "QUESTIONÁRIO DE BEM ESTAR [SONO]")),
            "muscle_soreness_score": first_score(_dict_get(values, "QUESTIONÁRIO DE BEM ESTAR [DOR MUSCULAR]")),
            "stress_score": first_score(_dict_get(values, "QUESTIONÁRIO DE BEM ESTAR [ESTRESSE]")),
            "mood_score": first_score(_dict_get(values, "QUESTIONÁRIO DE BEM ESTAR [HUMOR]")),
        }
    if isinstance(values, list):
        sheet = str(payload.get("sheet", ""))
        sheet_headers = headers.get((source_id, sheet))
        if not sheet_headers:
            return None
        category = _list_get(values, sheet_headers, "CATEGORIA")
        submitted_at = parse_datetime(_list_get(values, sheet_headers, "CARIMBO DE DATA HORA"))
        return {
            "submitted_at": submitted_at,
            "response_date": _canonical_response_date(
                submitted_at,
                _list_get(values, sheet_headers, "DATA DE HOJE"),
            ),
            "sport": sport_from_category(category),
            "category": category,
            "pain_location_raw": _list_get(values, sheet_headers, "SE VOCE SENTE DOR MUSCULAR EM ALGUM DOS LOCAIS MARCADOS NA IMAGEM ABAIXO ESCREVA O NUMERO CORRESPONDENTE AO LOCAL"),
            "pain_intensity": number_value(_list_get(values, sheet_headers, "DE 0 A 10 QUAL O NIVEL DA DOR DE ACORDO COM A ESCALA ABAIXO")),
            "fatigue_score": first_score(_list_get(values, sheet_headers, "QUESTIONARIO DE BEM ESTAR FADIGA")),
            "sleep_score": first_score(_list_get(values, sheet_headers, "QUESTIONARIO DE BEM ESTAR SONO")),
            "muscle_soreness_score": first_score(_list_get(values, sheet_headers, "QUESTIONARIO DE BEM ESTAR DOR MUSCULAR")),
            "stress_score": first_score(_list_get(values, sheet_headers, "QUESTIONARIO DE BEM ESTAR ESTRESSE")),
            "mood_score": first_score(_list_get(values, sheet_headers, "QUESTIONARIO DE BEM ESTAR HUMOR")),
        }
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


def _canonical_response_date(submitted_at: str | None, reported_date: str | None) -> str | None:
    """Use the auditable form timestamp; retain the reported value only in raw payload."""
    if submitted_at and len(submitted_at) >= 10:
        return submitted_at[:10]
    return parse_date(reported_date)
