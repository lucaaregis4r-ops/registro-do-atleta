from pathlib import Path
import sqlite3

from registro_atleta.ingestion.pipeline import sync
from registro_atleta.ingestion.sources import SourceConfig


def test_sync_is_idempotent_for_same_local_xlsx(tmp_path: Path) -> None:
    source_file = tmp_path / "source.xlsx"
    _write_minimal_xlsx(source_file, athlete_name="Ana")
    source = SourceConfig(
        source_id="fixture_xlsx",
        source_type="local_xlsx",
        name="fixture.xlsx",
        domain="test",
        enabled=True,
        local_path=source_file,
    )

    first = sync(tmp_path, sources=[source])
    second = sync(tmp_path, sources=[source])

    assert first.records_created == 2
    assert second.records_created == 0
    assert second.records_unchanged == 2

    connection = sqlite3.connect(tmp_path / "data" / "database" / "registro_atleta.db")
    current_records = connection.execute("SELECT COUNT(*) FROM source_records WHERE is_current = 1").fetchone()[0]
    assert current_records == 2


def _write_minimal_xlsx(path: Path, athlete_name: str) -> None:
    from zipfile import ZIP_DEFLATED, ZipFile

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "")
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Dados" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:B2"/>
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>Nome</t></is></c>
      <c r="B1" t="inlineStr"><is><t>Categoria</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>{athlete_name}</t></is></c>
      <c r="B2" t="inlineStr"><is><t>Sub-15</t></is></c>
    </row>
  </sheetData>
</worksheet>""",
        )
