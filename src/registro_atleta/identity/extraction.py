from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from registro_atleta.identity.normalization import is_probable_person_name, normalize_name


NAME_HEADERS = {"NOME", "NOME_CANONICO", "NOME CANONICO", "ATLETA", "ATLETAS EM TRATAMENTO NOME"}
CATEGORY_HEADERS = {"CATEGORIA", "CATEGORIAS_PSR", "CATEGORIAS CARACTERIZACAO", "CATEGORIAS CARACTERIZAÇÃO"}
SPORT_HEADERS = {"MODALIDADE", "MODALIDADES"}


@dataclass(frozen=True)
class ExtractedIdentity:
    source_record_id: str
    source_id: str
    name_raw: str
    name_normalized: str
    sport: str | None
    category: str | None
    evidence: dict[str, object]


def extract_identities(connection: sqlite3.Connection) -> list[ExtractedIdentity]:
    rows = connection.execute(
        """
        SELECT source_record_id, source_id, raw_payload_json
        FROM source_records
        WHERE is_current = 1
        ORDER BY source_id, source_row_key
        """
    ).fetchall()
    header_cache = _build_header_cache(rows)
    identities: list[ExtractedIdentity] = []
    for row in rows:
        if _is_derived_source(row["source_id"]):
            continue
        payload = json.loads(row["raw_payload_json"])
        extracted = _extract_from_payload(row["source_record_id"], row["source_id"], payload, header_cache)
        if extracted is not None:
            identities.append(extracted)
    return identities


def _is_derived_source(source_id: str) -> bool:
    return any(marker in source_id for marker in ("analise", "prototipo", "relatorio_integrado"))


def _build_header_cache(rows: list[sqlite3.Row]) -> dict[tuple[str, str], dict[str, int]]:
    cache: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        payload = json.loads(row["raw_payload_json"])
        values = payload.get("values")
        if not isinstance(values, list):
            continue
        sheet = str(payload.get("sheet", ""))
        headers = {_normalize_header(value): index for index, value in enumerate(values) if isinstance(value, str)}
        if not headers:
            continue
        if any(_is_name_header(header) for header in headers):
            cache[(row["source_id"], sheet)] = headers
    return cache


def _extract_from_payload(
    source_record_id: str,
    source_id: str,
    payload: dict[str, object],
    header_cache: dict[tuple[str, str], dict[str, int]],
) -> ExtractedIdentity | None:
    values = payload.get("values")
    if isinstance(values, dict):
        return _extract_from_mapping(source_record_id, source_id, values)
    if isinstance(values, list):
        sheet = str(payload.get("sheet", ""))
        headers = header_cache.get((source_id, sheet), {})
        return _extract_from_sequence(source_record_id, source_id, sheet, values, headers)
    return None


def _extract_from_mapping(
    source_record_id: str,
    source_id: str,
    values: dict[str, object],
) -> ExtractedIdentity | None:
    normalized_keys = {_normalize_header(key): key for key in values}
    name = _first_probable_name(str(values[original_key]) for key, original_key in normalized_keys.items() if _is_name_header(key))
    if name is None:
        return None
    category = _first_value(values[original_key] for key, original_key in normalized_keys.items() if key in CATEGORY_HEADERS)
    sport = _first_value(values[original_key] for key, original_key in normalized_keys.items() if key in SPORT_HEADERS)
    return _identity(source_record_id, source_id, name, sport, category, {"method": "mapping_header"})


def _extract_from_sequence(
    source_record_id: str,
    source_id: str,
    sheet: str,
    values: list[object],
    headers: dict[str, int],
) -> ExtractedIdentity | None:
    name_indexes = [index for header, index in headers.items() if _is_name_header(header)]
    name = _first_probable_name(str(values[index]) for index in name_indexes if index < len(values))
    if name is None:
        return None
    category = _value_by_headers(values, headers, CATEGORY_HEADERS)
    sport = _value_by_headers(values, headers, SPORT_HEADERS)
    return _identity(
        source_record_id,
        source_id,
        name,
        sport,
        category,
        {"method": "sheet_header", "sheet": sheet, "name_indexes": name_indexes},
    )


def _identity(
    source_record_id: str,
    source_id: str,
    name: str,
    sport: str | None,
    category: str | None,
    evidence: dict[str, object],
) -> ExtractedIdentity:
    return ExtractedIdentity(
        source_record_id=source_record_id,
        source_id=source_id,
        name_raw=name.strip(),
        name_normalized=normalize_name(name),
        sport=sport.strip() if isinstance(sport, str) and sport.strip() else None,
        category=category.strip() if isinstance(category, str) and category.strip() else None,
        evidence=evidence,
    )


def _first_probable_name(values) -> str | None:
    for value in values:
        if is_probable_person_name(value):
            return value
    return None


def _first_value(values) -> str | None:
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return None


def _value_by_headers(values: list[object], headers: dict[str, int], wanted: set[str]) -> str | None:
    for header, index in headers.items():
        if header in wanted and index < len(values):
            text = str(values[index]).strip()
            if text:
                return text
    return None


def _normalize_header(value: str) -> str:
    return normalize_name(value).replace("_", " ")


def _is_name_header(header: str) -> bool:
    return header in NAME_HEADERS or header.startswith("NOME ")
