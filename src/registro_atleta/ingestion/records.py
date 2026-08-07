from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterator

from registro_atleta.audit.hashing import file_sha256
from registro_atleta.audit.xlsx_inspector import iter_workbook_rows


@dataclass(frozen=True)
class SourceRecord:
    source_row_key: str
    payload: dict[str, object]
    record_hash: str


def file_hash(path: Path) -> str:
    return file_sha256(path)


def read_records(path: Path, source_type: str) -> list[SourceRecord]:
    if source_type == "google_sheet":
        return list(_read_csv_records(path))
    if source_type == "local_xlsx":
        return list(_read_xlsx_records(path))
    return []


def canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_payload(payload: dict[str, object]) -> str:
    from hashlib import sha256

    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _read_csv_records(path: Path) -> Iterator[SourceRecord]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row_number, row in enumerate(reader, start=2):
            payload = {"row_number": row_number, "values": dict(row)}
            yield SourceRecord(
                source_row_key=f"csv:row:{row_number}",
                payload=payload,
                record_hash=hash_payload(payload),
            )


def _read_xlsx_records(path: Path) -> Iterator[SourceRecord]:
    for sheet_name, row_index, values in iter_workbook_rows(path):
        payload = {"sheet": sheet_name, "row_number": row_index, "values": values}
        yield SourceRecord(
            source_row_key=f"xlsx:{sheet_name}:row:{row_index}",
            payload=payload,
            record_hash=hash_payload(payload),
        )
