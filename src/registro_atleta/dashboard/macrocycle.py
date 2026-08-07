from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.ingestion.snapshots import utc_now


PHASES = [
    ("Diagnostico", "limpar bloqueios de identidade, datas e duplicatas"),
    ("Estabilizacao", "acompanhar episodios ativos e sinais persistentes"),
    ("Ajuste de carga", "priorizar atletas com dor, fadiga e restricao de treino"),
    ("Reavaliacao", "conferir resposta dos casos e necessidade de avaliacao"),
    ("Consolidacao", "reduzir alertas recorrentes e documentar decisoes"),
    ("Fechamento", "preparar relatorio do ciclo e proximos bloqueios"),
]


@dataclass(frozen=True)
class MacrocycleReportResult:
    report_path: Path
    json_path: Path
    cycle_start: str
    cycle_end: str
    weeks: int
    decision_load: int
    active_episodes: int
    high_episodes: int


def build_macrocycle_payload(database_path: Path, weeks: int = 6, reference_date: date | None = None) -> dict:
    connection = connect_database(database_path)
    initialize_database(connection)
    try:
        reference_date = reference_date or _today_utc()
        cycle_start = reference_date - timedelta(days=reference_date.weekday())
        weeks = max(1, min(int(weeks), 12))
        cycle_end = cycle_start + timedelta(days=(weeks * 7) - 1)
        blockers = _blockers(connection)
        active_episodes = _scalar(connection, "SELECT COUNT(*) FROM alert_episodes WHERE episode_status = 'active'")
        high_episodes = _scalar(
            connection,
            "SELECT COUNT(*) FROM alert_episodes WHERE episode_status = 'active' AND current_severity = 'high'",
        )
        open_alerts = _scalar(connection, "SELECT COUNT(*) FROM alerts WHERE status = 'open'")
        decision_load = blockers["identity_pending"] + blockers["date_findings_open"] + blockers["duplicate_findings_open"]
        return {
            "generated_at": utc_now(),
            "summary": {
                "reference_date": reference_date.isoformat(),
                "cycle_start": cycle_start.isoformat(),
                "cycle_end": cycle_end.isoformat(),
                "weeks": weeks,
                "active_episodes": active_episodes,
                "high_episodes": high_episodes,
                "open_alerts": open_alerts,
                "decision_load": decision_load,
                "primary_focus": _primary_focus(decision_load, high_episodes, open_alerts),
            },
            "blockers": blockers,
            "top_alert_types": _rows(
                connection,
                """
                SELECT alert_type, COUNT(*) AS open_count
                FROM alerts
                WHERE status = 'open'
                GROUP BY alert_type
                ORDER BY open_count DESC, alert_type
                LIMIT 6
                """,
            ),
            "priority_episodes": _rows(
                connection,
                """
                SELECT ae.episode_id, ae.alert_type, ae.current_severity, ae.novelty_status,
                       ae.priority_score, ae.last_seen_at, at.canonical_name AS athlete_name
                FROM alert_episodes ae
                JOIN athletes at ON at.athlete_id = ae.athlete_id
                WHERE ae.episode_status = 'active'
                ORDER BY ae.priority_score DESC, ae.updated_at DESC
                LIMIT 8
                """,
            ),
            "weeks": [
                _week_payload(index, cycle_start + timedelta(days=index * 7), blockers, active_episodes, high_episodes)
                for index in range(weeks)
            ],
        }
    finally:
        connection.close()


def build_macrocycle_report(
    root: Path,
    database_path: Path | None = None,
    weeks: int = 6,
    reference_date: date | None = None,
) -> MacrocycleReportResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    payload = build_macrocycle_payload(database_path, weeks=weeks, reference_date=reference_date)
    report_dir = root / "data" / "reports" / "macrocycle"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("+", "Z")
    report_path = report_dir / f"macrocycle-{stamp}.md"
    json_path = report_dir / f"macrocycle-{stamp}.json"
    report_path.write_text(_render_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = payload["summary"]
    return MacrocycleReportResult(
        report_path=report_path,
        json_path=json_path,
        cycle_start=summary["cycle_start"],
        cycle_end=summary["cycle_end"],
        weeks=int(summary["weeks"]),
        decision_load=int(summary["decision_load"]),
        active_episodes=int(summary["active_episodes"]),
        high_episodes=int(summary["high_episodes"]),
    )


def _today_utc() -> date:
    return datetime.fromisoformat(utc_now()).date()


def _blockers(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "identity_pending": _scalar(connection, "SELECT COUNT(*) FROM identity_candidates WHERE decision_status = 'pending_review'"),
        "date_findings_open": _scalar(
            connection,
            "SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open' AND finding_type = 'psr_invalid_or_future_date'",
        ),
        "duplicate_findings_open": _scalar(
            connection,
            "SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open' AND finding_type LIKE 'duplicate_%'",
        ),
        "quality_open": _scalar(connection, "SELECT COUNT(*) FROM data_quality_findings WHERE status = 'open'"),
    }


def _render_markdown(payload: dict) -> str:
    summary = payload["summary"]
    blockers = payload["blockers"]
    lines = [
        "# Macrociclo Operacional",
        "",
        f"Gerado em UTC: `{payload['generated_at']}`",
        "",
        "## Resumo",
        "",
        f"- Periodo: `{summary['cycle_start']}` a `{summary['cycle_end']}`",
        f"- Semanas: `{summary['weeks']}`",
        f"- Foco principal: `{summary['primary_focus']}`",
        f"- Carga de decisao: `{summary['decision_load']}`",
        f"- Episodios ativos: `{summary['active_episodes']}`",
        f"- Episodios de risco alto: `{summary['high_episodes']}`",
        f"- Alertas abertos: `{summary['open_alerts']}`",
        "",
        "## Bloqueios",
        "",
        f"- Identidades pendentes: `{blockers['identity_pending']}`",
        f"- Achados de data abertos: `{blockers['date_findings_open']}`",
        f"- Duplicatas abertas: `{blockers['duplicate_findings_open']}`",
        f"- Achados de qualidade abertos: `{blockers['quality_open']}`",
        "",
        "## Semanas Do Ciclo",
        "",
        "| Semana | Periodo | Fase | Objetivo | Decisoes | Episodios | Risco alto |",
        "|---:|---|---|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {row['week_index']} | {row['week_start']} a {row['week_end']} | {row['phase']} | {row['goal']} | {row['decision_load']} | {row['active_episodes']} | {row['high_episodes']} |"
        for row in payload["weeks"]
    )
    lines.extend(["", "## Alertas Dominantes", "", "| Tipo | Abertos |", "|---|---:|"])
    lines.extend(f"| {row['alert_type']} | {row['open_count']} |" for row in payload["top_alert_types"])
    lines.extend(["", "## Episodios Prioritarios", "", "| Atleta | Tipo | Severidade | Novidade | Prioridade | Ultimo sinal |", "|---|---|---|---|---:|---|"])
    lines.extend(
        f"| {row['athlete_name']} | {row['alert_type']} | {row['current_severity']} | {row['novelty_status']} | {row['priority_score']} | {row['last_seen_at']} |"
        for row in payload["priority_episodes"]
    )
    lines.extend(
        [
            "",
            "## Uso Recomendado",
            "",
            "1. Fechar bloqueios de identidade, datas e duplicatas antes de interpretar tendencias finas.",
            "2. Usar episodios prioritarios para orientar acompanhamento humano.",
            "3. Regerar o macrociclo apos revisoes humanas relevantes.",
            "",
        ]
    )
    return "\n".join(lines)


def _primary_focus(decision_load: int, high_episodes: int, open_alerts: int) -> str:
    if decision_load:
        return "saneamento de decisoes humanas"
    if high_episodes:
        return "controle de risco alto"
    if open_alerts:
        return "monitoramento de sinais abertos"
    return "manutencao e acompanhamento"


def _week_payload(index: int, week_start: date, blockers: dict[str, int], active_episodes: int, high_episodes: int) -> dict:
    phase, goal = PHASES[index % len(PHASES)]
    week_end = week_start + timedelta(days=6)
    if index == 0 and blockers["identity_pending"]:
        goal = "resolver identidades pendentes antes de analises por atleta"
    elif index == 1 and blockers["date_findings_open"]:
        goal = "corrigir datas que bloqueiam series temporais"
    elif index == 2 and blockers["duplicate_findings_open"]:
        goal = "fechar duplicatas e conflitos de nomes"
    return {
        "week_index": index + 1,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "phase": phase,
        "goal": goal,
        "decision_load": blockers["identity_pending"] + blockers["date_findings_open"] + blockers["duplicate_findings_open"],
        "active_episodes": active_episodes,
        "high_episodes": high_episodes,
    }


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def _rows(connection: sqlite3.Connection, query: str) -> list[dict]:
    return [dict(row) for row in connection.execute(query).fetchall()]
