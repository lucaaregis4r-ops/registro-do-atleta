from pathlib import Path
import csv
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.literature.search import search_literature_candidates


def test_search_literature_requires_confirmation(tmp_path: Path) -> None:
    result = search_literature_candidates(tmp_path, database_path=tmp_path / "db.sqlite")

    assert result.blocked_reason is not None
    assert result.candidates_written == 0


def test_search_literature_writes_crossref_candidates_and_audit_run(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO literature_search_topics
            (topic_id, topic, source_alert_type, source_count, priority, reason_selected, status, created_at)
            VALUES ('topic-1', 'fadiga em atletas jovens', 'psr_fatigue', 3, 1, 'Teste.', 'pending_search', 'now')
            """
        )
    connection.close()

    def fake_fetcher(url: str, headers: dict[str, str]) -> dict:
        assert "query.bibliographic=fadiga" in url
        assert headers["Accept"] == "application/json"
        return {
            "message": {
                "items": [
                    {
                        "title": ["Monitoring fatigue in youth athletes"],
                        "author": [{"given": "Ana", "family": "Silva"}],
                        "published-online": {"date-parts": [[2024, 1, 2]]},
                        "container-title": ["Sports Journal"],
                        "DOI": "10.1000/test",
                        "URL": "https://example.test/paper",
                        "abstract": "<jats:p>Resumo curto.</jats:p>",
                        "score": 42.5,
                    }
                ]
            }
        }

    output_path = tmp_path / "candidates.csv"
    result = search_literature_candidates(
        tmp_path,
        database_path=db_path,
        output_path=output_path,
        confirm=True,
        fetcher=fake_fetcher,
    )

    assert result.topics_searched == 1
    assert result.candidates_written == 1
    assert result.errors == 0

    with output_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["topic"] == "fadiga em atletas jovens"
    assert rows[0]["title"] == "Monitoring fatigue in youth athletes"
    assert rows[0]["doi"] == "10.1000/test"
    assert rows[0]["abstract"] == "Resumo curto."

    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM literature_search_runs").fetchone()[0] == 1
    assert connection.execute("SELECT status FROM literature_search_topics").fetchone()[0] == "searched"
    connection.close()
