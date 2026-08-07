from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
import sqlite3
from typing import Any

from registro_atleta.identity.normalization import normalize_name


def auto_matched_records(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT source_record_id, proposed_athlete_id
        FROM identity_candidates
        WHERE decision_status = 'auto_matched'
          AND proposed_athlete_id IS NOT NULL
        """
    ).fetchall()
    return {row["source_record_id"]: row["proposed_athlete_id"] for row in rows}


def current_source_rows(connection: sqlite3.Connection, source_predicate: str) -> list[sqlite3.Row]:
    return connection.execute(
        f"""
        SELECT source_record_id, source_id, source_row_key, raw_payload_json
        FROM source_records
        WHERE is_current = 1 AND ({source_predicate})
        ORDER BY source_id, source_row_key
        """
    ).fetchall()


def payload_values(row: sqlite3.Row) -> dict[str, Any]:
    return json.loads(row["raw_payload_json"])


def normalize_header(value: str) -> str:
    return normalize_name(value).replace("_", " ")


def first_score(value: object) -> int | None:
    text = str(value).strip()
    match = re.search(r"\d+", text)
    if not match:
        return None
    score = int(match.group(0))
    return score if 0 <= score <= 10 else None


def number_value(value: object) -> float | None:
    text = str(value).strip().replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def parse_date(value: object) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    number = number_value(text)
    if number is not None and re.fullmatch(r"\d+(?:\.\d+)?", text):
        if 20000 <= number <= 60000:
            return (datetime(1899, 12, 30) + timedelta(days=number)).date().isoformat()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_datetime(value: object) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    number = number_value(text)
    if number is not None and re.fullmatch(r"\d+(?:\.\d+)?", text):
        if 20000 <= number <= 60000:
            return (datetime(1899, 12, 30) + timedelta(days=number)).isoformat(timespec="seconds")
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def sport_from_category(category: str | None) -> str | None:
    if not category:
        return None
    normalized = normalize_name(category)
    if "BASQUETE" in normalized:
        return "Basquete"
    if "VOLEI" in normalized or "VOLEIBOL" in normalized:
        return "Voleibol"
    if "FUTSAL" in normalized:
        return "Futsal"
    if "NATACAO" in normalized:
        return "Natacao"
    return None


def source_row_sheet(payload: dict[str, Any]) -> str | None:
    sheet = payload.get("sheet")
    return str(sheet) if sheet else None
