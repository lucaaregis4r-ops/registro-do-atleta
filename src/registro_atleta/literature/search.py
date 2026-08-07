from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import html
import json
import re
import sqlite3
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


Fetcher = Callable[[str, dict[str, str]], dict[str, Any]]


@dataclass
class LiteratureSearchResult:
    topics_searched: int = 0
    candidates_written: int = 0
    errors: int = 0
    output_path: Path | None = None
    blocked_reason: str | None = None


def search_literature_candidates(
    root: Path,
    database_path: Path | None = None,
    output_path: Path | None = None,
    provider: str = "crossref",
    limit_per_topic: int = 5,
    confirm: bool = False,
    mailto: str | None = None,
    fetcher: Fetcher | None = None,
) -> LiteratureSearchResult:
    result = LiteratureSearchResult()
    if not confirm:
        result.blocked_reason = "busca bloqueada: use --confirm para consultar provedor academico externo."
        return result
    if provider != "crossref":
        raise ValueError(f"provedor de literatura nao suportado: {provider}")

    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    output_path = output_path or root / "data" / "reviews" / "literature_candidates_crossref.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or fetch_crossref_json

    connection = connect_database(database_path)
    initialize_database(connection)
    rows_to_write: list[dict[str, str]] = []
    topics = _pending_topics(connection)
    with connection:
        for topic in topics:
            query = topic["topic"]
            try:
                payload = fetcher(_crossref_url(query, limit_per_topic, mailto), _headers(mailto))
                candidates = _crossref_candidates(payload, topic=query)
                rows_to_write.extend(candidates)
                result.topics_searched += 1
                result.candidates_written += len(candidates)
                _record_search_run(connection, topic["topic_id"], provider, query, len(candidates), "success", None)
                connection.execute(
                    "UPDATE literature_search_topics SET status = ? WHERE topic_id = ?",
                    ("searched", topic["topic_id"]),
                )
            except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                result.errors += 1
                _record_search_run(connection, topic["topic_id"], provider, query, 0, "error", str(exc))

    _write_candidates(output_path, rows_to_write)
    result.output_path = output_path
    connection.close()
    return result


def fetch_crossref_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _pending_topics(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT topic_id, topic
        FROM literature_search_topics
        WHERE status IN ('pending_search', 'needs_retry')
        ORDER BY priority ASC, created_at ASC
        """
    ).fetchall()


def _crossref_url(query: str, limit: int, mailto: str | None) -> str:
    params = {
        "query.bibliographic": query,
        "rows": str(max(1, min(limit, 20))),
        "select": "DOI,title,author,published-print,published-online,published,container-title,URL,abstract,score",
    }
    if mailto:
        params["mailto"] = mailto
    return f"https://api.crossref.org/works?{urlencode(params)}"


def _headers(mailto: str | None) -> dict[str, str]:
    user_agent = "RegistroAtleta/0.1"
    if mailto:
        user_agent = f"{user_agent} (mailto:{mailto})"
    return {"User-Agent": user_agent, "Accept": "application/json"}


def _crossref_candidates(payload: dict[str, Any], topic: str) -> list[dict[str, str]]:
    items = payload.get("message", {}).get("items", [])
    candidates: list[dict[str, str]] = []
    for item in items:
        title = _first_text(item.get("title"))
        if not title:
            continue
        candidates.append(
            {
                "topic": topic,
                "title": title,
                "authors": _authors(item.get("author") or []),
                "publication_year": _year(item),
                "journal": _first_text(item.get("container-title")),
                "doi": str(item.get("DOI") or "").strip(),
                "url": str(item.get("URL") or "").strip(),
                "abstract": _clean_abstract(str(item.get("abstract") or "")),
                "citation_count": "",
                "source_provider": "crossref",
                "relevance_score": str(item.get("score") or ""),
                "reason_selected": "Candidato retornado por busca Crossref para tema pendente.",
            }
        )
    return candidates


def _write_candidates(output_path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "topic",
        "title",
        "authors",
        "publication_year",
        "journal",
        "doi",
        "url",
        "abstract",
        "citation_count",
        "source_provider",
        "relevance_score",
        "reason_selected",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _record_search_run(
    connection: sqlite3.Connection,
    topic_id: str,
    provider: str,
    query: str,
    result_count: int,
    status: str,
    error_message: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO literature_search_runs
        (search_run_id, topic_id, provider, query, searched_at, result_count, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid4().hex, topic_id, provider, query, utc_now(), result_count, status, error_message),
    )


def _first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0]).strip()
    return str(value or "").strip()


def _authors(value: list[dict[str, Any]]) -> str:
    authors = []
    for author in value:
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        name = " ".join(part for part in [given, family] if part)
        if name:
            authors.append(name)
    return "; ".join(authors)


def _year(item: dict[str, Any]) -> str:
    for key in ["published-print", "published-online", "published"]:
        date_parts = item.get(key, {}).get("date-parts")
        if date_parts and date_parts[0]:
            return str(date_parts[0][0])
    return ""


def _clean_abstract(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
