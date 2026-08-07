from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from registro_atleta.database.schema import connect_database, initialize_database
from registro_atleta.domains.assessments.normalizer import build_physical_assessments
from registro_atleta.domains.physio.normalizer import build_physio_records
from registro_atleta.domains.psr.normalizer import build_psr_responses
from registro_atleta.ingestion.snapshots import utc_now


@dataclass
class DomainBuildResult:
    psr_created: int = 0
    psr_updated: int = 0
    psr_skipped_without_identity: int = 0
    weekly_physio_created: int = 0
    weekly_physio_updated: int = 0
    physio_events_created: int = 0
    physio_events_updated: int = 0
    physio_skipped_without_identity: int = 0
    assessments_created: int = 0
    assessments_updated: int = 0
    assessment_metrics_created: int = 0
    assessment_metrics_replaced: int = 0
    assessments_skipped_without_identity: int = 0
    report_path: Path | None = None


def build_domains(root: Path, database_path: Path | None = None) -> DomainBuildResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    connection = connect_database(database_path)
    initialize_database(connection)
    result = DomainBuildResult()
    with connection:
        _reset_domain_tables(connection)
        psr = build_psr_responses(connection)
        physio = build_physio_records(connection)
        assessments = build_physical_assessments(connection)
    result.psr_created = psr.created
    result.psr_updated = psr.updated
    result.psr_skipped_without_identity = psr.skipped_without_identity
    result.weekly_physio_created = physio.weekly_created
    result.weekly_physio_updated = physio.weekly_updated
    result.physio_events_created = physio.events_created
    result.physio_events_updated = physio.events_updated
    result.physio_skipped_without_identity = physio.skipped_without_identity
    result.assessments_created = assessments.assessments_created
    result.assessments_updated = assessments.assessments_updated
    result.assessment_metrics_created = assessments.metrics_created
    result.assessment_metrics_replaced = assessments.metrics_replaced
    result.assessments_skipped_without_identity = assessments.skipped_without_identity
    result.report_path = _write_report(root, result)
    connection.close()
    return result


def _reset_domain_tables(connection) -> None:
    for table in (
        "physical_assessment_metrics",
        "physical_assessments",
        "weekly_physio_reports",
        "physio_case_events",
        "physio_cases",
        "psr_responses",
    ):
        connection.execute(f"DELETE FROM {table}")


def _write_report(root: Path, result: DomainBuildResult) -> Path:
    report_dir = root / "data" / "reports" / "domains"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"domains-{utc_now().replace(':', '').replace('+', 'Z')}.md"
    lines = [
        "# Relatorio De Dominios",
        "",
        f"- psr_criados: `{result.psr_created}`",
        f"- psr_atualizados: `{result.psr_updated}`",
        f"- psr_sem_identidade: `{result.psr_skipped_without_identity}`",
        f"- weekly_physio_criados: `{result.weekly_physio_created}`",
        f"- weekly_physio_atualizados: `{result.weekly_physio_updated}`",
        f"- physio_events_criados: `{result.physio_events_created}`",
        f"- physio_events_atualizados: `{result.physio_events_updated}`",
        f"- physio_sem_identidade: `{result.physio_skipped_without_identity}`",
        f"- avaliacoes_criadas: `{result.assessments_created}`",
        f"- avaliacoes_atualizadas: `{result.assessments_updated}`",
        f"- metricas_avaliacao_criadas: `{result.assessment_metrics_created}`",
        f"- metricas_avaliacao_substituidas: `{result.assessment_metrics_replaced}`",
        f"- avaliacoes_sem_identidade: `{result.assessments_skipped_without_identity}`",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
