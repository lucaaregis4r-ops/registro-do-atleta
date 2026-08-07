from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess
import sys
import time
from typing import Callable


PROFILES = ("core", "standard", "intelligence", "research")


@dataclass(frozen=True)
class NightlyStage:
    key: str
    block: str
    title: str
    command: tuple[str, ...]
    profiles: frozenset[str]
    critical: bool = False
    requires_llm: bool = False
    experimental: bool = False


@dataclass(frozen=True)
class NightlyStageResult:
    key: str
    block: str
    title: str
    command: list[str]
    status: str
    started_at: str | None
    finished_at: str | None
    seconds: float
    return_code: int | None
    artifacts: list[str]


@dataclass(frozen=True)
class NightlyIntelligenceResult:
    run_id: str
    profile: str
    status: str
    stages: tuple[NightlyStageResult, ...]
    summary_path: Path | None
    manifest_path: Path | None
    log_path: Path | None


def stage_catalog() -> tuple[NightlyStage, ...]:
    all_profiles = frozenset(PROFILES)
    reports = frozenset({"standard", "intelligence", "research"})
    return (
        NightlyStage("database", "01-fontes-banco", "Ler fontes e atualizar banco", ("run-pipeline",), all_profiles, critical=True),
        NightlyStage("readiness", "02-qualidade", "Verificar identidade, datas e qualidade", ("data-readiness-report",), all_profiles),
        NightlyStage("duplicates", "02-qualidade", "Detectar possiveis duplicidades", ("duplicate-alerts",), all_profiles),
        NightlyStage("reviews", "02-qualidade", "Consolidar revisoes humanas", ("review-progress-report",), all_profiles),
        NightlyStage("macrocycle", "03-analise-deterministica", "Calcular macrociclo operacional", ("macrocycle-report", "--weeks", "6"), reports),
        NightlyStage("weekly", "03-analise-deterministica", "Gerar estado semanal deterministico", ("weekly-report",), reports),
        NightlyStage("status", "03-analise-deterministica", "Gerar painel de status", ("status-panel",), reports),
        NightlyStage("approved-literature", "04-literatura", "Carregar literatura aprovada", ("approved-literature-report",), reports),
        NightlyStage(
            "literature-discovery",
            "04-literatura",
            "Pesquisar novos artigos candidatos",
            ("llm-research-report", "--max-queries", "5", "--results-per-query", "3"),
            frozenset({"research"}),
            requires_llm=True,
        ),
        NightlyStage(
            "weekly-intelligence",
            "05-interpretacao",
            "Relacionar mudancas da base e artigos",
            ("weekly-intelligence-report",),
            reports,
            critical=True,
        ),
        NightlyStage("dashboard", "06-publicacao", "Publicar dados do dashboard", ("export-dashboard-data",), reports),
        NightlyStage(
            "phase9-readiness",
            "07-experimental",
            "Verificar gate de modelos avancados",
            ("phase9-readiness",),
            reports,
            experimental=True,
        ),
        NightlyStage(
            "phase9-report",
            "07-experimental",
            "Gerar relatorio exploratorio avancado",
            ("build-phase9",),
            reports,
            experimental=True,
        ),
    )


def selected_stages(profile: str, include_experimental: bool = False) -> tuple[NightlyStage, ...]:
    if profile not in PROFILES:
        raise ValueError(f"profile deve ser um de: {', '.join(PROFILES)}")
    return tuple(
        stage
        for stage in stage_catalog()
        if profile in stage.profiles and (include_experimental or not stage.experimental)
    )


def run_nightly_intelligence(
    root: Path,
    database_path: Path,
    profile: str = "standard",
    days: int = 7,
    reference_date: str | None = None,
    include_experimental: bool = False,
    dry_run: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> NightlyIntelligenceResult:
    if not 1 <= days <= 31:
        raise ValueError("days deve estar entre 1 e 31")
    stages = selected_stages(profile, include_experimental=include_experimental)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if dry_run:
        planned = tuple(_planned_result(stage, root, database_path, days, reference_date) for stage in stages)
        return NightlyIntelligenceResult(run_id, profile, "planned", planned, None, None, None)

    report_dir = root / "data" / "reports" / "nightly-intelligence"
    report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = report_dir / f"nightly-intelligence-{run_id}.md"
    manifest_path = report_dir / f"nightly-intelligence-{run_id}.json"
    log_path = report_dir / f"nightly-intelligence-{run_id}.log"
    env = _execution_environment(root, profile)
    results: list[NightlyStageResult] = []
    overall_status = "success"

    with _NightlyLock(root / "data" / "locks" / "nightly-intelligence.lock"):
        for index, stage in enumerate(stages):
            command = _stage_command(stage, root, database_path, days, reference_date)
            started = datetime.now(timezone.utc)
            started_clock = time.monotonic()
            completed = runner(
                command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            finished = datetime.now(timezone.utc)
            output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
            _append_log(log_path, stage, command, output)
            stage_status = "success" if completed.returncode == 0 else "failed"
            results.append(
                NightlyStageResult(
                    key=stage.key,
                    block=stage.block,
                    title=stage.title,
                    command=command,
                    status=stage_status,
                    started_at=started.isoformat(),
                    finished_at=finished.isoformat(),
                    seconds=round(time.monotonic() - started_clock, 2),
                    return_code=completed.returncode,
                    artifacts=_extract_artifacts(output, root),
                )
            )
            if completed.returncode != 0:
                overall_status = "failed" if stage.critical else "degraded"
                if stage.critical:
                    results.extend(_skipped_results(stages[index + 1 :], root, database_path, days, reference_date))
                    break

    payload = {
        "run_id": run_id,
        "profile": profile,
        "status": overall_status,
        "manual_execution": True,
        "llm_enabled": profile in {"intelligence", "research"},
        "experimental_enabled": include_experimental,
        "stages": [asdict(result) for result in results],
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(_render_summary(payload, manifest_path, log_path), encoding="utf-8")
    return NightlyIntelligenceResult(
        run_id,
        profile,
        overall_status,
        tuple(results),
        summary_path,
        manifest_path,
        log_path,
    )


def _execution_environment(root: Path, profile: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["REGISTRO_ATLETA_LLM_ENABLED"] = "1" if profile in {"intelligence", "research"} else "0"
    if env["REGISTRO_ATLETA_LLM_ENABLED"] == "1":
        env.setdefault("REGISTRO_ATLETA_LLM_PROVIDER", "ollama")
    return env


def _stage_command(
    stage: NightlyStage,
    root: Path,
    database_path: Path,
    days: int,
    reference_date: str | None,
) -> list[str]:
    command = [sys.executable, "-m", "registro_atleta.cli", *stage.command, "--database", str(database_path)]
    if stage.key == "weekly-intelligence":
        command.extend(["--days", str(days)])
        if reference_date:
            command.extend(["--reference-date", reference_date])
    return command


def _planned_result(stage: NightlyStage, root: Path, database_path: Path, days: int, reference_date: str | None) -> NightlyStageResult:
    return NightlyStageResult(
        stage.key,
        stage.block,
        stage.title,
        _stage_command(stage, root, database_path, days, reference_date),
        "planned",
        None,
        None,
        0.0,
        None,
        [],
    )


def _skipped_results(stages, root: Path, database_path: Path, days: int, reference_date: str | None) -> list[NightlyStageResult]:
    return [
        NightlyStageResult(
            stage.key,
            stage.block,
            stage.title,
            _stage_command(stage, root, database_path, days, reference_date),
            "skipped",
            None,
            None,
            0.0,
            None,
            [],
        )
        for stage in stages
    ]


def _append_log(log_path: Path, stage: NightlyStage, command: list[str], output: str) -> None:
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(f"\n## {stage.block} / {stage.title}\n")
        stream.write("COMMAND: " + subprocess.list2cmdline(command) + "\n")
        stream.write(output + "\n")


def _extract_artifacts(output: str, root: Path) -> list[str]:
    artifacts = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        candidate = line.split(":", 1)[1].strip()
        path = Path(candidate)
        if not path.is_absolute():
            path = root / path
        if path.is_file():
            artifacts.append(str(path.resolve()))
    return sorted(set(artifacts))


def _render_summary(payload: dict, manifest_path: Path, log_path: Path) -> str:
    lines = [
        "# Nightly Intelligence Pipeline",
        "",
        f"- run_id: `{payload['run_id']}`",
        f"- perfil: `{payload['profile']}`",
        f"- status: `{payload['status']}`",
        f"- execucao: `manual`",
        f"- LLM habilitado: `{payload['llm_enabled']}`",
        "",
        "## Blocos Executados",
        "",
        "| Bloco | Etapa | Status | Segundos |",
        "|---|---|---|---:|",
    ]
    for stage in payload["stages"]:
        lines.append(f"| {stage['block']} | {stage['title']} | {stage['status']} | {stage['seconds']} |")
    lines.extend(
        [
            "",
            "## Artefatos",
            "",
            f"- Manifesto auditavel: `{manifest_path}`",
            f"- Log tecnico: `{log_path}`",
        ]
    )
    for stage in payload["stages"]:
        for artifact in stage["artifacts"]:
            lines.append(f"- {stage['title']}: `{artifact}`")
    lines.extend(
        [
            "",
            "## Governanca",
            "",
            "- Numeros e mudancas da base sao calculados deterministicamente.",
            "- O LLM interpreta somente o payload preparado e nao altera dados criticos.",
            "- Literatura candidata exige revisao humana antes de ser tratada como aprovada.",
            "- Falha em etapa critica interrompe os blocos posteriores e permanece registrada.",
        ]
    )
    return "\n".join(lines) + "\n"


class _NightlyLock:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raw_pid = self.path.read_text(encoding="ascii", errors="ignore").strip()
            if raw_pid.isdigit() and _pid_is_alive(int(raw_pid)):
                raise RuntimeError(f"Rotina noturna ja esta em execucao pelo PID {raw_pid}: {self.path}")
            self.path.unlink()
        self.path.write_text(str(os.getpid()), encoding="ascii")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.path.exists():
            self.path.unlink()


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
