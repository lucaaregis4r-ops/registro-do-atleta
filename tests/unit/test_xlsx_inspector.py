from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from registro_atleta.audit.xlsx_inspector import inspect_workbook


def test_inspect_workbook_reads_sheets_and_headers(tmp_path: Path) -> None:
    workbook = tmp_path / "fixture.xlsx"
    _write_minimal_xlsx(workbook)

    summary = inspect_workbook(workbook)

    assert len(summary.sheets) == 1
    sheet = summary.sheets[0]
    assert sheet.name == "Dados"
    assert sheet.dimension == "A1:B2"
    assert sheet.max_row == 2
    assert sheet.max_column == 2
    assert sheet.probable_header_row == 1
    assert sheet.probable_headers == ["Nome", "Categoria"]


def _write_minimal_xlsx(path: Path) -> None:
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
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:B2"/>
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>Nome</t></is></c>
      <c r="B1" t="inlineStr"><is><t>Categoria</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>Ana</t></is></c>
      <c r="B2" t="inlineStr"><is><t>Sub-15</t></is></c>
    </row>
  </sheetData>
</worksheet>""",
        )
