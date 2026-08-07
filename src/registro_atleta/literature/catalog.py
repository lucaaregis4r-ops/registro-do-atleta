from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import json
import re
import sqlite3
import unicodedata
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


@dataclass
class LiteratureCatalogResult:
    imported_papers: int = 0
    duplicate_papers: int = 0
    linked_topics: int = 0
    skipped_rows: int = 0
    review_queue_path: Path | None = None
    blocked_reason: str | None = None


@dataclass
class LiteratureReviewImportResult:
    applied_reviews: int = 0
    skipped_rows: int = 0
    invalid_rows: int = 0
    review_queue_path: Path | None = None
    blocked_reason: str | None = None


def catalog_literature_candidates(
    root: Path,
    csv_path: Path,
    database_path: Path | None = None,
    confirm: bool = False,
) -> LiteratureCatalogResult:
    result = LiteratureCatalogResult()
    if not confirm:
        result.blocked_reason = "catalogacao bloqueada: use --confirm para importar candidatos de artigos."
        return result

    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        for row in _read_rows(csv_path):
            topic = (row.get("topic") or row.get("tema") or "").strip()
            title = (row.get("title") or row.get("titulo") or "").strip()
            if not topic or not title:
                result.skipped_rows += 1
                continue

            paper_id = _find_existing_paper(connection, title=title, doi=row.get("doi"))
            if paper_id:
                result.duplicate_papers += 1
            else:
                paper_id = uuid4().hex
                _insert_paper(connection, paper_id, row, title)
                result.imported_papers += 1

            if _link_topic(connection, paper_id, row, topic):
                result.linked_topics += 1

    result.review_queue_path = write_literature_review_queue(root, connection)
    connection.close()
    return result


def write_literature_review_queue(root: Path, connection: sqlite3.Connection) -> Path:
    review_dir = root / "data" / "reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / "literature_review_queue.csv"
    rows = connection.execute(
        """
        SELECT
            pt.paper_topic_id,
            pt.topic,
            p.title,
            p.authors_json,
            p.publication_year,
            p.journal,
            p.doi,
            p.url,
            pt.relevance_score,
            pt.reason_selected,
            pt.human_status
        FROM paper_topics pt
        JOIN papers p ON p.paper_id = pt.paper_id
        WHERE pt.human_status IN ('pending_review', 'needs_revision')
        ORDER BY pt.created_at DESC, p.title
        """
    ).fetchall()
    with review_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "paper_topic_id",
                "topic",
                "title",
                "authors",
                "publication_year",
                "journal",
                "doi",
                "url",
                "relevance_score",
                "reason_selected",
                "human_status",
                "human_decision",
                "notes",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["paper_topic_id"],
                    row["topic"],
                    row["title"],
                    _authors_text(row["authors_json"]),
                    row["publication_year"] or "",
                    row["journal"] or "",
                    row["doi"] or "",
                    row["url"] or "",
                    row["relevance_score"] if row["relevance_score"] is not None else "",
                    row["reason_selected"],
                    row["human_status"],
                    "",
                    "",
                ]
            )
    return review_path


def import_literature_reviews(
    root: Path,
    csv_path: Path,
    reviewed_by: str,
    database_path: Path | None = None,
    confirm: bool = False,
) -> LiteratureReviewImportResult:
    result = LiteratureReviewImportResult()
    if not confirm:
        result.blocked_reason = "importacao bloqueada: use --confirm para aplicar decisoes humanas de literatura."
        return result
    reviewed_by = reviewed_by.strip()
    if not reviewed_by:
        result.blocked_reason = "importacao bloqueada: informe --reviewed-by."
        return result
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    with connection:
        for row in _read_rows(csv_path):
            paper_topic_id = (row.get("paper_topic_id") or "").strip()
            decision = _normalize_decision(row.get("human_decision"))
            notes = (row.get("notes") or "").strip() or None
            if not paper_topic_id and not decision:
                result.skipped_rows += 1
                continue
            if not paper_topic_id or decision is None:
                result.invalid_rows += 1
                continue

            current = connection.execute(
                "SELECT human_status FROM paper_topics WHERE paper_topic_id = ?",
                (paper_topic_id,),
            ).fetchone()
            if current is None:
                result.invalid_rows += 1
                continue

            previous_status = current["human_status"]
            new_status = _status_for_decision(decision)
            connection.execute(
                "UPDATE paper_topics SET human_status = ? WHERE paper_topic_id = ?",
                (new_status, paper_topic_id),
            )
            connection.execute(
                """
                INSERT INTO paper_topic_reviews
                (review_id, paper_topic_id, decision, previous_status, new_status,
                 reviewed_by, reviewed_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid4().hex, paper_topic_id, decision, previous_status, new_status, reviewed_by, utc_now(), notes),
            )
            result.applied_reviews += 1

    result.review_queue_path = write_literature_review_queue(root, connection)
    connection.close()
    return result


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _normalize_decision(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    aliases = {
        "approve": "approved",
        "approved": "approved",
        "aprovar": "approved",
        "aprovado": "approved",
        "aprovada": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "rejeitar": "rejected",
        "rejeitado": "rejected",
        "rejeitada": "rejected",
        "needs_revision": "needs_revision",
        "revision": "needs_revision",
        "revisar": "needs_revision",
        "revisao": "needs_revision",
        "revisão": "needs_revision",
    }
    return aliases.get(text)


def _status_for_decision(decision: str) -> str:
    if decision == "approved":
        return "approved"
    if decision == "rejected":
        return "rejected"
    return "needs_revision"


def _insert_paper(connection: sqlite3.Connection, paper_id: str, row: dict[str, str], title: str) -> None:
    connection.execute(
        """
        INSERT INTO papers
        (paper_id, title, authors_json, publication_year, journal, doi, url, abstract,
         citation_count, citation_count_checked_at, source_provider)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            title,
            _authors_json(row.get("authors") or row.get("autores")),
            _optional_int(row.get("publication_year") or row.get("ano")),
            _blank_to_none(row.get("journal") or row.get("periodico")),
            _normalize_doi(row.get("doi")),
            _blank_to_none(row.get("url")),
            _blank_to_none(row.get("abstract") or row.get("resumo")),
            _optional_int(row.get("citation_count") or row.get("citacoes")),
            _blank_to_none(row.get("citation_count_checked_at")),
            _blank_to_none(row.get("source_provider") or row.get("fonte")),
        ),
    )


def _link_topic(connection: sqlite3.Connection, paper_id: str, row: dict[str, str], topic: str) -> bool:
    exists = connection.execute(
        "SELECT 1 FROM paper_topics WHERE paper_id = ? AND topic = ?",
        (paper_id, topic),
    ).fetchone()
    if exists:
        return False
    connection.execute(
        """
        INSERT INTO paper_topics
        (paper_topic_id, paper_id, topic, sport, body_region, relevance_score,
         reason_selected, human_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            paper_id,
            topic,
            _blank_to_none(row.get("sport") or row.get("modalidade")),
            _blank_to_none(row.get("body_region") or row.get("regiao_corporal")),
            _optional_float(row.get("relevance_score") or row.get("relevancia")),
            (row.get("reason_selected") or row.get("motivo") or "Candidato importado para avaliacao humana.").strip(),
            "pending_review",
            utc_now(),
        ),
    )
    return True


def _find_existing_paper(connection: sqlite3.Connection, title: str, doi: str | None) -> str | None:
    normalized_doi = _normalize_doi(doi)
    if normalized_doi:
        row = connection.execute("SELECT paper_id FROM papers WHERE LOWER(doi) = LOWER(?)", (normalized_doi,)).fetchone()
        if row:
            return row["paper_id"]

    normalized_title = _normalize_title(title)
    for row in connection.execute("SELECT paper_id, title FROM papers").fetchall():
        if _normalize_title(row["title"]) == normalized_title:
            return row["paper_id"]
    return None


def _normalize_doi(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    return value.lower()


def _normalize_title(value: str) -> str:
    without_accents = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in without_accents if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def _authors_json(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    authors = [item.strip() for item in re.split(r";|\|", value) if item.strip()]
    if not authors:
        authors = [value]
    return json.dumps(authors, ensure_ascii=False)


def _authors_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        authors = json.loads(value)
    except json.JSONDecodeError:
        return value
    return "; ".join(str(author) for author in authors)


def _optional_int(value: str | None) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _optional_float(value: str | None) -> float | None:
    text = (value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None
