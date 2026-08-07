from pathlib import Path
import json

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.llm.provider import LlmResult
from registro_atleta.reports.weekly_intelligence import build_weekly_intelligence_report


class StructuredProvider:
    provider = "fixture"
    model = "fixture-model"

    def generate(self, prompt: dict) -> LlmResult:
        paper_id = prompt["approved_articles"][0]["paper_id"]
        output = {
            "executive_summary": ["Houve revisoes humanas e atualizacao da base."],
            "article_assessments": [
                {
                    "paper_id": paper_id,
                    "main_message": "Monitoramento deve ser interpretado no contexto.",
                    "relation_to_weekly_changes": "Apoia a discussao dos episodios observados.",
                    "limitations": "Um artigo nao define causalidade.",
                    "practical_consideration": "Usar como apoio a revisao da equipe.",
                    "confidence": "medium",
                }
            ],
            "cross_article_synthesis": ["Sintese limitada a um artigo."],
            "limitations": ["Nao substitui avaliacao profissional."],
        }
        return LlmResult(self.provider, self.model, "success", json.dumps(output))


class InvalidProvider:
    provider = "fixture"
    model = "fixture-model"

    def generate(self, prompt: dict) -> LlmResult:
        return LlmResult(self.provider, self.model, "success", "")


def _seed_weekly_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO pipeline_runs
            (run_id, started_at, finished_at, status, code_version, records_created, records_updated, errors)
            VALUES ('run-1', '2026-07-15T10:00:00', '2026-07-15T10:01:00', 'success', 'test', 5, 2, 0)
            """
        )
        connection.execute(
            """
            INSERT INTO papers
            (paper_id, title, publication_year, journal, doi, abstract, source_provider)
            VALUES ('paper-1', 'Monitoring Athletes', 2025, 'Journal', '10.1/test',
                    'Monitoring requires contextual interpretation.', 'crossref')
            """
        )
        connection.execute(
            """
            INSERT INTO paper_topics
            (paper_topic_id, paper_id, topic, reason_selected, human_status, created_at)
            VALUES ('topic-1', 'paper-1', 'monitoramento', 'Aprovado pela equipe.', 'approved', '2026-07-15T11:00:00')
            """
        )
    connection.close()
    return database_path


def test_weekly_intelligence_combines_deterministic_changes_and_structured_articles(tmp_path: Path) -> None:
    database_path = _seed_weekly_database(tmp_path)

    result = build_weekly_intelligence_report(
        tmp_path,
        database_path=database_path,
        reference_date="2026-07-18",
        provider=StructuredProvider(),
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    markdown = result.report_path.read_text(encoding="utf-8")
    assert result.llm_status == "success"
    assert payload["deterministic_changes"]["pipeline"]["records_created"] == 5
    assert payload["literature"]["articles"][0]["title"] == "Monitoring Athletes"
    assert payload["literature"]["structured_analysis"]["article_assessments"][0]["confidence"] == "medium"
    assert "Mudancas Deterministicas Da Semana" in markdown
    assert "Artigos Aprovados - Analise Estruturada" in markdown


def test_weekly_intelligence_falls_back_when_llm_output_is_invalid(tmp_path: Path) -> None:
    database_path = _seed_weekly_database(tmp_path)

    result = build_weekly_intelligence_report(
        tmp_path,
        database_path=database_path,
        reference_date="2026-07-18",
        provider=InvalidProvider(),
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert result.llm_status == "deterministic_fallback"
    assert payload["literature"]["structured_analysis"]["article_assessments"][0]["paper_id"] == "paper-1"
    assert payload["deterministic_changes"]["pipeline"]["records_updated"] == 2


def test_weekly_intelligence_limits_metadata_only_article_confidence(tmp_path: Path) -> None:
    database_path = _seed_weekly_database(tmp_path)
    connection = connect_database(database_path)
    with connection:
        connection.execute("UPDATE papers SET abstract = NULL WHERE paper_id = 'paper-1'")
    connection.close()

    result = build_weekly_intelligence_report(
        tmp_path,
        database_path=database_path,
        reference_date="2026-07-18",
        provider=StructuredProvider(),
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    article = payload["literature"]["articles"][0]
    assessment = payload["literature"]["structured_analysis"]["article_assessments"][0]
    assert article["analysis_readiness"] == "needs_revalidation"
    assert assessment["confidence"] == "low"
    assert "Precisam de revalidacao" in result.report_path.read_text(encoding="utf-8")
