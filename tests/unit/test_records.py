from pathlib import Path

from registro_atleta.ingestion.records import read_records


def test_read_csv_records(tmp_path: Path) -> None:
    csv_path = tmp_path / "source.csv"
    csv_path.write_text("nome,categoria\nAna,Sub-15\n", encoding="utf-8")

    records = read_records(csv_path, "google_sheet")

    assert len(records) == 1
    assert records[0].source_row_key == "csv:row:2"
    assert records[0].payload["values"] == {"nome": "Ana", "categoria": "Sub-15"}
