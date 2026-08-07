from __future__ import annotations

from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class LiteratureTopic:
    topic: str
    source_alert_type: str | None
    source_count: int
    priority: int
    reason_selected: str


TOPIC_MAP = {
    "psr_high_pain": "dor autorrelatada e risco de lesao em atletas jovens",
    "psr_multi_wellness_flag": "questionarios de bem-estar e carga interna no esporte de base",
    "psr_fatigue_above_individual_baseline": "fadiga acima do baseline individual e monitoramento de carga",
    "psr_no_recent_response": "adesao a questionarios de bem-estar em equipes esportivas",
    "physio_training_restriction": "retorno ao esporte e restricoes de treino na reabilitacao",
}


def generate_literature_topics(connection: sqlite3.Connection) -> list[LiteratureTopic]:
    rows = connection.execute(
        """
        SELECT alert_type, COUNT(*) count
        FROM alerts
        WHERE status = 'open'
        GROUP BY alert_type
        ORDER BY count DESC
        """
    ).fetchall()
    topics: list[LiteratureTopic] = []
    for index, row in enumerate(rows, start=1):
        alert_type = row["alert_type"]
        topic = TOPIC_MAP.get(alert_type, f"evidencias cientificas relacionadas a {alert_type}")
        topics.append(
            LiteratureTopic(
                topic=topic,
                source_alert_type=alert_type,
                source_count=row["count"],
                priority=index,
                reason_selected=f"{row['count']} alertas abertos do tipo {alert_type}.",
            )
        )
    return topics
