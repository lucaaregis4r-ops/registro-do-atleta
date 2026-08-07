from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile

from registro_atleta.ingestion.snapshots import utc_now
from registro_atleta.operations.backup import (
    list_backups,
    restore_database,
    verify_database_integrity,
)


@dataclass(frozen=True)
class OperationalCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class OperationalReadinessResult:
    status: str
    report_path: Path
    checks: tuple[OperationalCheck, ...]


SchedulerProbe = Callable[[str], tuple[bool, str]]


def build_operational_readiness_report(
    root: Path,
    database_path: Path | None = None,
    retention_limit: int = 10,
    task_name: str = "Registro do Atleta Nightly",
    scheduler_probe: SchedulerProbe | None = None,
    scheduler_required: bool = True,
) -> OperationalReadinessResult:
    if retention_limit < 1:
        raise ValueError("retention_limit deve ser >= 1")
    database_path = database_path or root / "data" / "database" / "registro_atleta.db"
    checks: list[OperationalCheck] = []

    database_report = verify_database_integrity(database_path)
    checks.append(
        OperationalCheck(
            "database_integrity",
            "ready" if database_report.ok else "failed",
            _integrity_detail(database_report),
        )
    )

    backups = list_backups(root)
    if not backups:
        checks.append(OperationalCheck("latest_backup", "failed", "nenhum backup encontrado"))
        checks.append(OperationalCheck("restore_rehearsal", "failed", "ensaio impossivel sem backup"))
    else:
        latest = backups[0]
        backup_report = verify_database_integrity(latest)
        checks.append(
            OperationalCheck(
                "latest_backup",
                "ready" if backup_report.ok else "failed",
                f"{latest.name}; {_integrity_detail(backup_report)}",
            )
        )
        checks.append(_restore_rehearsal(root, latest))

    retention_status = "ready" if len(backups) <= retention_limit else "warning"
    retention_detail = f"{len(backups)} backups; limite oficial={retention_limit}"
    if retention_status == "warning":
        retention_detail += f"; excedentes={len(backups) - retention_limit} (nenhum arquivo removido)"
    checks.append(OperationalCheck("backup_retention", retention_status, retention_detail))

    if scheduler_required:
        probe = scheduler_probe or _probe_windows_scheduler
        task_exists, task_detail = probe(task_name)
        checks.append(
            OperationalCheck(
                "windows_scheduler",
                "ready" if task_exists else "warning",
                task_detail,
            )
        )
    else:
        checks.append(
            OperationalCheck(
                "windows_scheduler",
                "ready",
                "rotina manual por decisao operacional; tarefa automatica nao requerida",
            )
        )

    status = _overall_status(checks)
    report_path = _write_report(root, status, task_name, checks)
    return OperationalReadinessResult(status=status, report_path=report_path, checks=tuple(checks))


def _restore_rehearsal(root: Path, backup_path: Path) -> OperationalCheck:
    rehearsal_root = root / "data" / "restore-tests"
    rehearsal_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="registro_atleta-restore-", dir=rehearsal_root) as temp_dir:
            restored_path = Path(temp_dir) / "registro_atleta.db"
            report = restore_database(backup_path, restored_path)
            status = "ready" if report.ok else "failed"
            return OperationalCheck("restore_rehearsal", status, _integrity_detail(report))
    except (OSError, shutil.Error) as exc:
        return OperationalCheck("restore_rehearsal", "failed", f"{type(exc).__name__}: {exc}")


def _probe_windows_scheduler(task_name: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        return False, f"Agendador indisponivel: {exc}"
    if result.returncode == 0:
        return True, f"tarefa encontrada: {task_name}"
    detail = (result.stderr or result.stdout or "tarefa nao encontrada").strip()
    return False, f"tarefa ausente: {task_name}; {detail}"


def _integrity_detail(report) -> str:
    detail = f"integrity={report.integrity_check}; tabelas_ausentes={len(report.missing_tables)}"
    if report.error_message:
        detail += f"; erro={report.error_message}"
    return detail


def _overall_status(checks: list[OperationalCheck]) -> str:
    if any(check.status == "failed" for check in checks):
        return "failed"
    if any(check.status == "warning" for check in checks):
        return "degraded"
    return "success"


def _write_report(
    root: Path,
    status: str,
    task_name: str,
    checks: list[OperationalCheck],
) -> Path:
    report_dir = root / "data" / "reports" / "operations"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("+", "Z")
    report_path = report_dir / f"operational-readiness-{stamp}.md"
    lines = [
        "# Prontidao Operacional",
        "",
        f"- status: `{status}`",
        f"- tarefa esperada: `{task_name}`",
        "",
        "| Verificacao | Estado | Detalhe |",
        "|---|---|---|",
    ]
    for check in checks:
        lines.append(f"| {check.name} | {check.status} | {check.detail.replace('|', '/')} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
