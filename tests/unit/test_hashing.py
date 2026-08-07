from pathlib import Path

from registro_atleta.audit.hashing import file_sha256, group_duplicates


def test_file_sha256(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("registro_atleta", encoding="utf-8")

    assert file_sha256(sample) == "f7cf4c93b5de630d35c1dd634ed65eb221fc1abe8ae41864d0f07cd0875a2a88"


def test_group_duplicates(tmp_path: Path) -> None:
    first = tmp_path / "a.xlsx"
    second = tmp_path / "b.xlsx"
    third = tmp_path / "c.xlsx"

    duplicates = group_duplicates({first: "same", second: "same", third: "different"})

    assert duplicates == {"same": [first, second]}
