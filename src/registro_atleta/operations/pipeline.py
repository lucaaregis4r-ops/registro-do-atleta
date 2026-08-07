from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import traceback

from registro_atleta.alerts.pipeline import build_alerts
from registro_atleta.identity.pipeline import build_identity
from registro_atleta.ingestion.pipeline import sync
from registro_atleta.domains.pipeline import build_domains
from registro_atleta.ingestion.snapshots import utc_now
from registro_atleta.operations.backup import backup_database
from registro_atleta.operations.lock import PipelineLock
from registro_atleta.reports.briefing import build_nightly_briefing


@dataclass
class StepResult:
    name: str
    status: str
    detail: str


@dataclass
class OperationalRunResult:
    status: str
    backup_path: Path | None
    report_path: Path
    steps: list[StepResult] = field(default_factory=list)


def run_operational_pipeline(root: Path, database_path: Path | None = None) -> OperationalRunResult:
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    lock_path = root / "data" / "locks" / "nightly.lock"
    steps: list[StepResult] = []
    backup_path: Path | None = None
    status = "success"

    with PipelineLock(lock_path):
        try:
            backup_path = backup_database(database_path, root)
            steps.append(StepResult("backup", "success", str(backup_path) if backup_path else "sem banco previo"))

            sync_result = sync(root, database_path=database_path)
            sync_status = "success" if sync_result.errors == 0 else "degraded"
            steps.append(
                StepResult(
                    "sync",
                    sync_status,
                    f"snapshots={sync_result.snapshots_saved}; novos={sync_result.records_created}; alterados={sync_result.records_updated}; erros={sync_result.errors}",
                )
            )
            if sync_result.errors:
                status = "degraded"

            identity_result = build_identity(root, database_path=database_path)
            steps.append(
                StepResult(
                    "identity",
                    "success",
                    f"auto={identity_result.auto_matched}; pendentes={identity_result.pending_review}",
                )
            )

            domain_result = build_domains(root, database_path=database_path)
            steps.append(
                StepResult(
                    "domains",
                    "success",
                    f"psr={domain_result.psr_created + domain_result.psr_updated}; fisio_events={domain_result.physio_events_created + domain_result.physio_events_updated}; avaliacoes={domain_result.assessments_created + domain_result.assessments_updated}",
                )
            )

            alert_result = build_alerts(root, database_path=database_path)
            steps.append(
                StepResult(
                    "alerts",
                    "success",
                    f"baselines={alert_result.baselines_created}; alertas={alert_result.alerts_created}; qualidade={alert_result.quality_findings_created}",
                )
            )
            briefing_result = build_nightly_briefing(root, database_path=database_path)
            steps.append(
                StepResult(
                    "briefing",
                    briefing_result.status,
                    f"principal={briefing_result.main_items}; apendice={briefing_result.appendix_items}; relatorio={briefing_result.markdown_path}",
                )
            )
            if briefing_result.status == "degraded":
                status = "degraded"
            elif briefing_result.status == "success_with_warnings" and status == "success":
                status = "success_with_warnings"
        except Exception as exc:  # noqa: BLE001 - operational command must write a failure report.
            status = "failed"
            steps.append(StepResult("pipeline", "failed", f"{type(exc).__name__}: {exc}"))
            steps.append(StepResult("traceback", "failed", traceback.format_exc()))

    report_path = _write_report(root, status, backup_path, steps)
    return OperationalRunResult(status=status, backup_path=backup_path, report_path=report_path, steps=steps)


def _write_report(root: Path, status: str, backup_path: Path | None, steps: list[StepResult]) -> Path:
    report_dir = root / "data" / "reports" / "operations"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now().replace(":", "").replace("+", "Z")
    report_path = report_dir / f"operation-{timestamp}.md"
    lines = [
        "# Relatorio Operacional",
        "",
        f"- status: `{status}`",
        f"- backup: `{backup_path}`",
        "",
        "## Etapas",
        "",
        "| Etapa | Status | Detalhe |",
        "|---|---|---|",
    ]
    for step in steps:
        detail = step.detail.replace("\n", "<br>")
        lines.append(f"| {step.name} | {step.status} | {detail} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
