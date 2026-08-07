from registro_atleta.audit.source_inventory import classify_domain


def test_classify_domains() -> None:
    assert classify_domain("CHAMADA _ PSR 2026.xlsx") == "psr"
    assert classify_domain("Controle de Atletas em Reabilitação 2026.xlsx") == "physio_rehab"
    assert classify_domain("REPORT SEMANAL.xlsx") == "weekly_physio_report"
    assert classify_domain("Caracterização Atletas Basquete.xlsx") == "assessment_or_roster"
    assert classify_domain("registro_unificador_atletas_demo.xlsx") == "identity_seed_derived"
    assert classify_domain("analise_fatores_risco_fisio_demo.xlsx") == "derived_reference"
    assert classify_domain("relatorio_integrado_demo.xlsx") == "derived_reference"
