from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


@dataclass
class ApprovedLiteratureReportResult:
    report_path: Path
    approved_links: int
    approved_papers: int


def build_approved_literature_report(root: Path, database_path: Path | None = None) -> ApprovedLiteratureReportResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    report_dir = root / "data" / "reports" / "literature"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"approved-literature-{utc_now().replace(':', '').replace('+', 'Z')}.md"

    rows = connection.execute(
        """
        SELECT
            pt.topic,
            pt.reason_selected,
            pt.relevance_score,
            p.title,
            p.authors_json,
            p.publication_year,
            p.journal,
            p.doi,
            p.url,
            p.abstract,
            p.source_provider
        FROM paper_topics pt
        JOIN papers p ON p.paper_id = pt.paper_id
        WHERE pt.human_status = 'approved'
        ORDER BY pt.topic, p.publication_year DESC, p.title
        """
    ).fetchall()
    approved_papers = connection.execute(
        """
        SELECT COUNT(DISTINCT p.paper_id)
        FROM paper_topics pt
        JOIN papers p ON p.paper_id = pt.paper_id
        WHERE pt.human_status = 'approved'
        """
    ).fetchone()[0]

    lines = [
        "# Boletim De Literatura Aprovada",
        "",
        f"Gerado em UTC: `{utc_now()}`",
        "",
        "## Escopo",
        "",
        "Este boletim usa somente artigos com revisao humana `approved` em `paper_topics`.",
        "Artigos pendentes, rejeitados ou em revisao nao sao usados.",
        "",
        f"- Vinculos tema-artigo aprovados: `{len(rows)}`",
        f"- Artigos distintos aprovados: `{approved_papers}`",
        "",
    ]
    if not rows:
        lines.extend(["## Artigos", "", "Nenhum artigo aprovado foi encontrado."])
    else:
        current_topic = None
        for row in rows:
            if row["topic"] != current_topic:
                current_topic = row["topic"]
                lines.extend(["", f"## {current_topic}", ""])
            evidence_source = "abstract" if row["abstract"] else "metadados"
            citation = _citation(row)
            lines.extend(
                [
                    f"### {row['title']}",
                    "",
                    f"- Citacao: {citation}",
                    f"- DOI: `{row['doi'] or ''}`",
                    f"- URL: {row['url'] or ''}",
                    f"- Fonte: `{row['source_provider'] or 'catalogo_local'}`",
                    f"- Base textual usada: `{evidence_source}`",
                    f"- Motivo da selecao: {row['reason_selected']}",
                    "",
                ]
            )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    connection.close()
    return ApprovedLiteratureReportResult(report_path=report_path, approved_links=len(rows), approved_papers=approved_papers)


def _citation(row: sqlite3.Row) -> str:
    year = row["publication_year"] or "s.d."
    journal = row["journal"] or "periodico nao informado"
    return f"{row['title']} ({year}). {journal}."
