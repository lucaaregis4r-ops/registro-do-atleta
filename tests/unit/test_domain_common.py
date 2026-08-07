from registro_atleta.domains.common import first_score, parse_date, parse_datetime, sport_from_category


def test_first_score_extracts_initial_number() -> None:
    assert first_score("4 - MAIS CANSADO QUE O NORMAL") == 4
    assert first_score("sem resposta") is None


def test_parse_excel_and_text_dates() -> None:
    assert parse_date("46090.0") == "2026-03-09"
    assert parse_date("09/03/2026") == "2026-03-09"
    assert parse_datetime("09/03/2026 12:30:00") == "2026-03-09T12:30:00"


def test_sport_from_category() -> None:
    assert sport_from_category("VÔLEI MASC SUB17") == "Voleibol"
    assert sport_from_category("BASQUETE SUB14") == "Basquete"
