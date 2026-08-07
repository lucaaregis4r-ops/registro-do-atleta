from registro_atleta.domains.psr.normalizer import _canonical_response_date


def test_psr_response_date_uses_form_submission_date() -> None:
    assert _canonical_response_date("2026-03-09T19:53:42", "3/9/0026") == "2026-03-09"
    assert _canonical_response_date("2026-03-10T14:39:49", "46298.0") == "2026-03-10"
    assert _canonical_response_date("2026-03-09T15:43:14", "40927.0") == "2026-03-09"


def test_psr_response_date_falls_back_when_submission_timestamp_is_missing() -> None:
    assert _canonical_response_date(None, "09/03/2026") == "2026-03-09"
    assert _canonical_response_date(None, None) is None
