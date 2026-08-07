from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import sqlite3
from uuid import uuid5, NAMESPACE_URL

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
NOVELTY_RANK = {"new": 40, "escalated": 35, "resolved": 30, "needs_review": 25, "improving": 15, "ongoing": 5}


@dataclass
class BriefingResult:
    report_run_id: str
    status: str
    markdown_path: Path
    html_path: Path | None
    json_path: Path
    main_items: int
    appendix_items: int
    episodes_touched: int


def build_nightly_briefing(
    root: Path,
    database_path: Path | None = None,
    main_limit: int = 12,
    reference_date: str | None = None,
) -> BriefingResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    reference_date = reference_date or _reference_date()
    generated_at = utc_now()
    connection = connect_database(database_path)
    initialize_database(connection)

    with connection:
        episode_items = _sync_alert_episodes(connection, reference_date, generated_at)
        quality_items = _quality_items(connection)
        identity_items = _identity_items(connection)
        all_items = sorted(episode_items + quality_items + identity_items, key=_item_sort_key)
        for index, item in enumerate(all_items, start=1):
            item["display_order"] = index
            item["included_in_main_brief"] = index <= main_limit and item["priority_score"] > 0

        report_run_id = _upsert_report_run(connection, reference_date, generated_at, all_items)
        connection.execute("DELETE FROM report_items WHERE report_run_id = ?", (report_run_id,))
        _insert_report_items(connection, report_run_id, all_items, generated_at)

    output_dir = root / "data" / "reports" / "briefings"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"briefing-{reference_date}"
    markdown_path = output_dir / f"{stem}.md"
    html_path = output_dir / f"{stem}.html"
    json_path = output_dir / f"{stem}.json"
    payload = _payload(reference_date, generated_at, all_items, report_run_id)
    markdown_path.write_text(_render_markdown(payload, main_limit), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    html_status = "success"
    try:
        html_path.write_text(_render_html(payload, main_limit), encoding="utf-8")
    except OSError:
        html_status = "degraded"
        html_path = None

    with connection:
        connection.execute(
            """
            UPDATE report_runs
            SET status = ?, deterministic_path = ?, enriched_path = ?, payload_json = ?
            WHERE report_run_id = ?
            """,
            (
                _status_for_items(all_items, html_status),
                str(markdown_path),
                str(html_path) if html_path else None,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                report_run_id,
            ),
        )
    connection.close()

    return BriefingResult(
        report_run_id=report_run_id,
        status=_status_for_items(all_items, html_status),
        markdown_path=markdown_path,
        html_path=html_path,
        json_path=json_path,
        main_items=sum(1 for item in all_items if item["included_in_main_brief"]),
        appendix_items=sum(1 for item in all_items if not item["included_in_main_brief"]),
        episodes_touched=len(episode_items),
    )


def _sync_alert_episodes(connection: sqlite3.Connection, reference_date: str, generated_at: str) -> list[dict]:
    current_groups = _current_alert_groups(connection)
    previous = {
        row["episode_key"]: row
        for row in connection.execute("SELECT * FROM alert_episodes").fetchall()
    }
    items: list[dict] = []
    seen_keys = set()

    for key, group in current_groups.items():
        seen_keys.add(key)
        old = previous.get(key)
        current_rank = SEVERITY_RANK.get(group["current_severity"], 0)
        old_rank = SEVERITY_RANK.get(old["current_severity"], 0) if old else 0
        if old is None or old["episode_status"] == "resolved":
            novelty = "new"
            episode_id = uuid5(NAMESPACE_URL, f"registro_atleta-alert-episode:{key}").hex
            first_seen = reference_date
            occurrence_count = group["occurrence_count"]
            consecutive_days = 1
            created_at = generated_at
        elif current_rank > old_rank:
            novelty = "escalated"
            episode_id = old["episode_id"]
            first_seen = old["first_seen_at"]
            occurrence_count = _next_occurrence_count(old, reference_date, group["occurrence_count"])
            consecutive_days = _next_consecutive_days(old, reference_date)
            created_at = old["created_at"]
        elif current_rank < old_rank:
            novelty = "improving"
            episode_id = old["episode_id"]
            first_seen = old["first_seen_at"]
            occurrence_count = _next_occurrence_count(old, reference_date, group["occurrence_count"])
            consecutive_days = _next_consecutive_days(old, reference_date)
            created_at = old["created_at"]
        else:
            novelty = "ongoing"
            episode_id = old["episode_id"]
            first_seen = old["first_seen_at"]
            occurrence_count = _next_occurrence_count(old, reference_date, group["occurrence_count"])
            consecutive_days = _next_consecutive_days(old, reference_date)
            created_at = old["created_at"]

        peak = _peak_severity(old["peak_severity"] if old else None, group["current_severity"])
        evidence = {
            "episode_key": key,
            "alert_ids": group["alert_ids"],
            "alert_type": group["alert_type"],
            "latest_reference_date": group["last_seen_at"],
            "representative_alert_id": group["representative_alert_id"],
        }
        priority = _priority_score(novelty, group["current_severity"], occurrence_count, len(group["alert_ids"]))
        connection.execute(
            """
            INSERT INTO alert_episodes
            (episode_id, episode_key, athlete_id, alert_type, first_seen_at, last_seen_at,
             episode_status, current_severity, peak_severity, occurrence_count, consecutive_days,
             novelty_status, priority_score, evidence_json, last_reported_at, resolved_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_key) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                episode_status = excluded.episode_status,
                current_severity = excluded.current_severity,
                peak_severity = excluded.peak_severity,
                occurrence_count = excluded.occurrence_count,
                consecutive_days = excluded.consecutive_days,
                novelty_status = excluded.novelty_status,
                priority_score = excluded.priority_score,
                evidence_json = excluded.evidence_json,
                last_reported_at = excluded.last_reported_at,
                resolved_at = excluded.resolved_at,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                key,
                group["athlete_id"],
                group["alert_type"],
                first_seen,
                reference_date,
                "active",
                group["current_severity"],
                peak,
                occurrence_count,
                consecutive_days,
                novelty,
                priority,
                json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                generated_at,
                None,
                created_at,
                generated_at,
            ),
        )
        items.append(_episode_item(episode_id, group, novelty, priority, evidence))

    for key, old in previous.items():
        if key in seen_keys or old["episode_status"] == "resolved":
            continue
        evidence = {
            "episode_key": key,
            "previous_last_seen_at": old["last_seen_at"],
            "reason": "alert signal absent in current alert set",
        }
        priority = _priority_score("resolved", old["current_severity"], old["occurrence_count"], 0)
        connection.execute(
            """
            UPDATE alert_episodes
            SET episode_status = 'resolved', novelty_status = 'resolved', priority_score = ?,
                evidence_json = ?, last_reported_at = ?, resolved_at = ?, updated_at = ?
            WHERE episode_key = ?
            """,
            (priority, json.dumps(evidence, ensure_ascii=False, sort_keys=True), generated_at, reference_date, generated_at, key),
        )
        items.append(
            {
                "item_type": "alert_episode",
                "athlete_id": old["athlete_id"],
                "episode_id": old["episode_id"],
                "alert_id": None,
                "finding_id": None,
                "source_record_id": None,
                "priority_bucket": "resolved",
                "priority_score": priority,
                "headline": f"Resolvido: {old['alert_type']} deixou de aparecer nos alertas atuais.",
                "evidence": evidence,
            }
        )
    return items


def _current_alert_groups(connection: sqlite3.Connection) -> dict[str, dict]:
    rows = connection.execute(
        """
        SELECT al.alert_id, al.athlete_id, al.alert_type, al.reference_date, al.severity,
               al.human_summary, at.canonical_name
        FROM alerts al
        JOIN athletes at ON at.athlete_id = al.athlete_id
        WHERE al.status = 'open'
        ORDER BY al.athlete_id, al.alert_type, al.reference_date, al.alert_id
        """
    ).fetchall()
    groups: dict[str, dict] = {}
    for row in rows:
        key = f"{row['athlete_id']}|{row['alert_type']}"
        group = groups.setdefault(
            key,
            {
                "episode_key": key,
                "athlete_id": row["athlete_id"],
                "canonical_name": row["canonical_name"],
                "alert_type": row["alert_type"],
                "alert_ids": [],
                "summaries": [],
                "current_severity": row["severity"],
                "representative_alert_id": row["alert_id"],
                "last_seen_at": row["reference_date"],
                "occurrence_count": 0,
            },
        )
        group["alert_ids"].append(row["alert_id"])
        group["summaries"].append(row["human_summary"])
        group["occurrence_count"] += 1
        if SEVERITY_RANK.get(row["severity"], 0) > SEVERITY_RANK.get(group["current_severity"], 0):
            group["current_severity"] = row["severity"]
            group["representative_alert_id"] = row["alert_id"]
        if row["reference_date"] and (group["last_seen_at"] is None or row["reference_date"] > group["last_seen_at"]):
            group["last_seen_at"] = row["reference_date"]
    return groups


def _episode_item(episode_id: str, group: dict, novelty: str, priority: float, evidence: dict) -> dict:
    label = {
        "new": "Novo",
        "ongoing": "Persistente",
        "escalated": "Escalou",
        "improving": "Melhorou",
    }.get(novelty, novelty)
    headline = f"{label}: {group['canonical_name']} - {group['alert_type']} ({group['current_severity']})."
    return {
        "item_type": "alert_episode",
        "athlete_id": group["athlete_id"],
        "episode_id": episode_id,
        "alert_id": group["representative_alert_id"],
        "finding_id": None,
        "source_record_id": None,
        "priority_bucket": novelty,
        "priority_score": priority,
        "headline": headline,
        "evidence": evidence,
    }


def _quality_items(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT finding_id, finding_type, severity, human_summary, evidence_json
        FROM data_quality_findings
        WHERE status = 'open' AND severity IN ('high', 'critical')
        ORDER BY severity DESC, finding_type, finding_id
        LIMIT 20
        """
    ).fetchall()
    items = []
    for row in rows:
        score = 45 if row["severity"] == "high" else 55
        items.append(
            {
                "item_type": "data_quality",
                "athlete_id": None,
                "episode_id": None,
                "alert_id": None,
                "finding_id": row["finding_id"],
                "source_record_id": None,
                "priority_bucket": "needs_review",
                "priority_score": score,
                "headline": f"Qualidade: {row['finding_type']} - {row['human_summary']}",
                "evidence": _loads(row["evidence_json"]),
            }
        )
    return items


def _identity_items(connection: sqlite3.Connection) -> list[dict]:
    pending = connection.execute(
        "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'"
    ).fetchone()[0]
    if pending == 0:
        return []
    return [
        {
            "item_type": "identity_review",
            "athlete_id": None,
            "episode_id": None,
            "alert_id": None,
            "finding_id": None,
            "source_record_id": None,
            "priority_bucket": "needs_review",
            "priority_score": 25,
            "headline": f"Identidade: {pending} candidatos aguardam revisao humana.",
            "evidence": {"pending_identity_candidates": pending},
        }
    ]


def _upsert_report_run(connection: sqlite3.Connection, reference_date: str, generated_at: str, items: list[dict]) -> str:
    report_run_id = uuid5(NAMESPACE_URL, f"registro_atleta-report-run:nightly_briefing:{reference_date}").hex
    status = _status_for_items(items, "success")
    connection.execute(
        """
        INSERT INTO report_runs
        (report_run_id, report_type, reference_date, period_start, period_end, status, generated_at, payload_json)
        VALUES (?, 'nightly_briefing', ?, ?, ?, ?, ?, '{}')
        ON CONFLICT(report_type, reference_date) DO UPDATE SET
            status = excluded.status,
            generated_at = excluded.generated_at,
            payload_json = excluded.payload_json
        """,
        (report_run_id, reference_date, reference_date, reference_date, status, generated_at),
    )
    row = connection.execute(
        "SELECT report_run_id FROM report_runs WHERE report_type = 'nightly_briefing' AND reference_date = ?",
        (reference_date,),
    ).fetchone()
    return row["report_run_id"]


def _insert_report_items(connection: sqlite3.Connection, report_run_id: str, items: list[dict], generated_at: str) -> None:
    for item in items:
        stable = f"{report_run_id}:{item['item_type']}:{item.get('episode_id') or item.get('finding_id') or item['headline']}"
        connection.execute(
            """
            INSERT INTO report_items
            (report_item_id, report_run_id, item_type, athlete_id, episode_id, alert_id, finding_id,
             source_record_id, priority_bucket, priority_score, headline, evidence_json, display_order,
             included_in_main_brief, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid5(NAMESPACE_URL, stable).hex,
                report_run_id,
                item["item_type"],
                item.get("athlete_id"),
                item.get("episode_id"),
                item.get("alert_id"),
                item.get("finding_id"),
                item.get("source_record_id"),
                item["priority_bucket"],
                item["priority_score"],
                item["headline"],
                json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True),
                item["display_order"],
                1 if item["included_in_main_brief"] else 0,
                generated_at,
            ),
        )


def _payload(reference_date: str, generated_at: str, items: list[dict], report_run_id: str) -> dict:
    return {
        "report_run_id": report_run_id,
        "reference_date": reference_date,
        "generated_at": generated_at,
        "status": _status_for_items(items, "success"),
        "items": items,
        "summary": {
            "total_items": len(items),
            "main_items": sum(1 for item in items if item["included_in_main_brief"]),
            "appendix_items": sum(1 for item in items if not item["included_in_main_brief"]),
        },
    }


def _render_markdown(payload: dict, main_limit: int) -> str:
    main = [item for item in payload["items"] if item["included_in_main_brief"]]
    appendix = [item for item in payload["items"] if not item["included_in_main_brief"]]
    lines = [
        "# Briefing Matinal - Registro do Atleta",
        "",
        f"- data_referencia: `{payload['reference_date']}`",
        f"- status: `{payload['status']}`",
        f"- itens_principais: `{len(main)}`",
        f"- itens_apendice: `{len(appendix)}`",
        "",
    ]
    if not main:
        lines.extend(["## Resumo", "", "Nenhuma mudanca prioritaria para o briefing principal.", ""])
    else:
        lines.extend(["## Briefing Principal", ""])
        for item in main:
            lines.append(f"{item['display_order']}. **{item['priority_bucket']}** - {item['headline']}")
            lines.append(f"   - prioridade_revisao: `{item['priority_score']}`")
            lines.append(f"   - referencias: `{_reference_summary(item)}`")
    lines.extend(["", "## Apendice", ""])
    if not appendix:
        lines.append("Sem itens adicionais.")
    else:
        lines.append(f"Itens fora do limite principal configurado (`{main_limit}`) ou de menor prioridade.")
        for item in appendix:
            lines.append(f"- {item['display_order']}. {item['priority_bucket']} - {item['headline']} (`{_reference_summary(item)}`)")
    return "\n".join(lines) + "\n"


def _render_html(payload: dict, main_limit: int) -> str:
    markdown_note = f"Limite principal: {main_limit}"
    rows = []
    for item in payload["items"]:
        section = "Principal" if item["included_in_main_brief"] else "Apendice"
        rows.append(
            "<tr>"
            f"<td>{item['display_order']}</td>"
            f"<td>{escape(section)}</td>"
            f"<td>{escape(item['priority_bucket'])}</td>"
            f"<td>{escape(item['headline'])}</td>"
            f"<td>{escape(_reference_summary(item))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan=\"5\">Nenhuma mudanca prioritaria.</td></tr>")
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><title>Briefing Registro do Atleta</title>",
            "<style>body{font-family:Arial,sans-serif;margin:32px;color:#1f2933}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d9e2ec;padding:6px 8px;text-align:left}th{background:#f0f4f8}</style>",
            "</head><body>",
            "<h1>Briefing Matinal - Registro do Atleta</h1>",
            f"<p>Data: <code>{escape(payload['reference_date'])}</code> Status: <code>{escape(payload['status'])}</code></p>",
            f"<p>{escape(markdown_note)}</p>",
            "<table><tr><th>#</th><th>Secao</th><th>Estado</th><th>Item</th><th>Referencias</th></tr>",
            *rows,
            "</table></body></html>",
        ]
    )


def _status_for_items(items: list[dict], html_status: str) -> str:
    if html_status == "degraded":
        return "degraded"
    if any(item["priority_bucket"] == "needs_review" for item in items):
        return "success_with_warnings"
    return "success"


def _item_sort_key(item: dict) -> tuple:
    return (-float(item["priority_score"]), item["priority_bucket"], item["headline"])


def _priority_score(novelty: str, severity: str, occurrence_count: int, alert_count: int) -> float:
    return float(NOVELTY_RANK.get(novelty, 0) + SEVERITY_RANK.get(severity, 0) * 10 + min(occurrence_count, 10) + min(alert_count, 5))


def _peak_severity(previous: str | None, current: str) -> str:
    if previous and SEVERITY_RANK.get(previous, 0) > SEVERITY_RANK.get(current, 0):
        return previous
    return current


def _next_occurrence_count(old: sqlite3.Row, reference_date: str, current_count: int) -> int:
    if old["last_seen_at"] == reference_date:
        return old["occurrence_count"]
    return old["occurrence_count"] + current_count


def _next_consecutive_days(old: sqlite3.Row, reference_date: str) -> int:
    if old["last_seen_at"] == reference_date:
        return old["consecutive_days"]
    return old["consecutive_days"] + 1


def _reference_summary(item: dict) -> str:
    refs = []
    for key in ("alert_id", "episode_id", "finding_id", "source_record_id"):
        if item.get(key):
            refs.append(f"{key}={item[key]}")
    return "; ".join(refs) if refs else "payload_json"


def _loads(value: str) -> dict:
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {"value": loaded}
    except json.JSONDecodeError:
        return {"raw": value}


def _reference_date() -> str:
    return utc_now()[:10]
