from pathlib import Path
import csv
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.literature.catalog import catalog_literature_candidates, import_literature_reviews


def test_catalog_literature_requires_explicit_confirmation(tmp_path: Path) -> None:
    input_path = tmp_path / "papers.csv"
    input_path.write_text("topic,title\nfadiga,Artigo Teste\n", encoding="utf-8")

    result = catalog_literature_candidates(tmp_path, input_path, database_path=tmp_path / "db.sqlite")

    assert result.blocked_reason is not None
    assert result.imported_papers == 0


def test_catalog_literature_deduplicates_by_doi_and_title(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    connection.close()

    input_path = tmp_path / "papers.csv"
    with input_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["topic", "title", "authors", "publication_year", "journal", "doi", "url", "reason_selected"])
        writer.writerow(["fadiga", "Carga interna em atletas jovens", "Silva; Souza", "2024", "Revista A", "10.123/abc", "https://example.test/a", "Tema prioritario."])
        writer.writerow(["fadiga", "Outro titulo para DOI repetido", "Silva", "2024", "Revista B", "https://doi.org/10.123/ABC", "https://example.test/b", "Duplicata por DOI."])
        writer.writerow(["dor", "Carga Interna em Atletas Jovens!", "Pereira", "2023", "Revista C", "", "https://example.test/c", "Duplicata por titulo."])

    result = catalog_literature_candidates(tmp_path, input_path, database_path=db_path, confirm=True)

    assert result.imported_papers == 1
    assert result.duplicate_papers == 2
    assert result.linked_topics == 2
    assert result.review_queue_path is not None
    assert result.review_queue_path.exists()

    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM paper_topics").fetchone()[0] == 2
    connection.close()


def test_import_literature_reviews_requires_confirmation(tmp_path: Path) -> None:
    input_path = tmp_path / "reviews.csv"
    input_path.write_text("paper_topic_id,human_decision\npt-1,approved\n", encoding="utf-8")

    result = import_literature_reviews(tmp_path, input_path, reviewed_by="Lucas", database_path=tmp_path / "db.sqlite")

    assert result.blocked_reason is not None
    assert result.applied_reviews == 0


def test_import_literature_reviews_updates_status_and_audit_log(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    connection = connect_database(db_path)
    initialize_database(connection)
    with connection:
        connection.execute(
            """
            INSERT INTO papers (paper_id, title, doi)
            VALUES ('paper-1', 'Artigo aprovado', '10.1/test')
            """
        )
        connection.execute(
            """
            INSERT INTO paper_topics
            (paper_topic_id, paper_id, topic, reason_selected, human_status, created_at)
            VALUES ('pt-1', 'paper-1', 'fadiga', 'Teste.', 'pending_review', 'now')
            """
        )
    connection.close()

    input_path = tmp_path / "reviews.csv"
    with input_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["paper_topic_id", "human_decision", "notes"])
        writer.writerow(["pt-1", "approved", "Aplicavel ao contexto."])

    result = import_literature_reviews(tmp_path, input_path, reviewed_by="Lucas", database_path=db_path, confirm=True)

    assert result.applied_reviews == 1
    assert result.invalid_rows == 0
    assert result.review_queue_path is not None
    assert result.review_queue_path.exists()

    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT human_status FROM paper_topics WHERE paper_topic_id = 'pt-1'").fetchone()[0] == "approved"
    review = connection.execute(
        "SELECT decision, previous_status, new_status, reviewed_by, notes FROM paper_topic_reviews"
    ).fetchone()
    assert review == ("approved", "pending_review", "approved", "Lucas", "Aplicavel ao contexto.")
    connection.close()
