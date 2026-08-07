from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Iterator
from xml.etree import ElementTree
from zipfile import ZipFile

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass(frozen=True)
class SheetSummary:
    name: str
    dimension: str
    max_row: int | None
    max_column: int | None
    probable_header_row: int | None
    probable_headers: list[str]


@dataclass(frozen=True)
class WorkbookSummary:
    sheets: list[SheetSummary]


def inspect_workbook(path: Path, scan_rows: int = 12) -> WorkbookSummary:
    with ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_refs = _read_sheet_refs(archive)
        sheets = [
            _inspect_sheet(archive, name, worksheet_path, shared_strings, scan_rows)
            for name, worksheet_path in sheet_refs
        ]
    return WorkbookSummary(sheets=sheets)


def iter_workbook_rows(path: Path) -> Iterator[tuple[str, int, list[str]]]:
    with ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)
        for sheet_name, worksheet_path in _read_sheet_refs(archive):
            root = ElementTree.fromstring(archive.read(worksheet_path))
            for row_index, values in _all_rows(root, shared_strings):
                yield sheet_name, row_index, values


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", NS):
        texts = [node.text or "" for node in item.findall(".//main:t", NS)]
        values.append("".join(texts))
    return values


def _read_sheet_refs(archive: ZipFile) -> list[tuple[str, str]]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("pkgrel:Relationship", NS)
    }

    refs: list[tuple[str, str]] = []
    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        name = sheet.attrib["name"]
        relationship_id = sheet.attrib[f"{{{NS['rel']}}}id"]
        target = targets[relationship_id].lstrip("/")
        worksheet_path = target if target.startswith("xl/") else f"xl/{target}"
        refs.append((name, worksheet_path))
    return refs


def _inspect_sheet(
    archive: ZipFile,
    name: str,
    worksheet_path: str,
    shared_strings: list[str],
    scan_rows: int,
) -> SheetSummary:
    root = ElementTree.fromstring(archive.read(worksheet_path))
    dimension = _dimension(root)
    rows = _first_rows(root, shared_strings, scan_rows)
    header_row, headers = _probable_headers(rows)
    max_row, max_column = _parse_dimension(dimension)
    if max_row is None or max_column is None:
        max_row, max_column = _max_cell_ref(root)
    return SheetSummary(
        name=name,
        dimension=dimension,
        max_row=max_row,
        max_column=max_column,
        probable_header_row=header_row,
        probable_headers=headers,
    )


def _dimension(root: ElementTree.Element) -> str:
    dimension = root.find("main:dimension", NS)
    return dimension.attrib.get("ref", "") if dimension is not None else ""


def _first_rows(
    root: ElementTree.Element,
    shared_strings: list[str],
    scan_rows: int,
) -> dict[int, list[str]]:
    rows: dict[int, list[str]] = {}
    for row in root.findall("main:sheetData/main:row", NS):
        row_index = int(row.attrib.get("r", "0"))
        if row_index > scan_rows:
            break
        values = _row_values(row, shared_strings)
        rows[row_index] = [value.strip() for value in values if value.strip()]
    return rows


def _all_rows(
    root: ElementTree.Element,
    shared_strings: list[str],
) -> Iterator[tuple[int, list[str]]]:
    for row in root.findall("main:sheetData/main:row", NS):
        row_index = int(row.attrib.get("r", "0"))
        values = [value.strip() for value in _row_values(row, shared_strings)]
        if any(values):
            yield row_index, values


def _row_values(row: ElementTree.Element, shared_strings: list[str]) -> list[str]:
    positioned: dict[int, str] = {}
    max_column = 0
    for fallback_index, cell in enumerate(row.findall("main:c", NS), start=1):
        ref = cell.attrib.get("r", "")
        match = re.match(r"([A-Z]+)\d+$", ref)
        column = _column_to_number(match.group(1)) if match else fallback_index
        positioned[column] = _cell_value(cell, shared_strings)
        max_column = max(max_column, column)
    return [positioned.get(index, "") for index in range(1, max_column + 1)]


def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        texts = [node.text or "" for node in cell.findall(".//main:t", NS)]
        return "".join(texts)

    value = cell.find("main:v", NS)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        index = int(value.text)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    return value.text


def _probable_headers(rows: dict[int, list[str]]) -> tuple[int | None, list[str]]:
    candidates = [(row_index, values) for row_index, values in rows.items() if len(values) >= 2]
    if not candidates:
        return None, []
    row_index, values = max(candidates, key=lambda item: (len(item[1]), -item[0]))
    return row_index, values[:30]


def _parse_dimension(dimension: str) -> tuple[int | None, int | None]:
    if not dimension:
        return None, None
    last_ref = dimension.split(":")[-1]
    match = re.match(r"([A-Z]+)(\d+)$", last_ref)
    if not match:
        return None, None
    column_name, row_name = match.groups()
    return int(row_name), _column_to_number(column_name)


def _max_cell_ref(root: ElementTree.Element) -> tuple[int | None, int | None]:
    max_row = 0
    max_column = 0
    for cell in root.findall("main:sheetData/main:row/main:c", NS):
        ref = cell.attrib.get("r", "")
        match = re.match(r"([A-Z]+)(\d+)$", ref)
        if not match:
            continue
        column_name, row_name = match.groups()
        max_row = max(max_row, int(row_name))
        max_column = max(max_column, _column_to_number(column_name))
    return (max_row or None), (max_column or None)


def _column_to_number(column_name: str) -> int:
    number = 0
    for char in column_name:
        number = number * 26 + (ord(char) - ord("A") + 1)
    return number


def compact_headers(headers: Iterable[str], max_items: int = 8) -> str:
    selected = [header for header in headers if header][:max_items]
    return ", ".join(selected)
