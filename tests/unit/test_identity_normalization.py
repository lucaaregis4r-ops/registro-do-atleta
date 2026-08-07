from registro_atleta.identity.normalization import is_probable_person_name, normalize_name


def test_normalize_name_removes_accents_case_and_punctuation() -> None:
    assert normalize_name("  João   D'Ávila-Silva ") == "JOAO D AVILA SILVA"


def test_probable_person_name_rejects_sections_and_single_tokens() -> None:
    assert is_probable_person_name("Kaique Lucas")
    assert not is_probable_person_name("ATENDIMENTOS IMEDIATOS DA SEMANA")
    assert not is_probable_person_name("NOME")
    assert not is_probable_person_name("Noah")
