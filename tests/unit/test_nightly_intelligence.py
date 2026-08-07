from pathlib import Path
import json
import subprocess

from registro_atleta.operations.nightly_intelligence import run_nightly_intelligence, selected_stages


class SuccessfulRunner:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="Etapa concluida.", stderr="")


class CriticalFailureRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, command, **kwargs):
        self.calls += 1
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Falha de banco")


def test_profiles_select_progressively_more_modules() -> None:
    core = selected_stages("core")
    standard = selected_stages("standard")
    intelligence = selected_stages("intelligence")
    research = selected_stages("research")

    assert len(core) == 4
    assert len(standard) == 10
    assert len(intelligence) == 10
    assert len(research) == 11
    assert "literature-discovery" not in {stage.key for stage in intelligence}
    assert "literature-discovery" in {stage.key for stage in research}
    assert all(not stage.experimental for stage in standard)
    assert len(selected_stages("standard", include_experimental=True)) == 12


def test_modular_run_writes_auditable_manifest_and_disables_llm_for_standard(tmp_path: Path) -> None:
    runner = SuccessfulRunner()

    result = run_nightly_intelligence(
        tmp_path,
        database_path=tmp_path / "club.db",
        profile="standard",
        reference_date="2026-07-18",
        runner=runner,
    )

    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.status == "success"
    assert payload["manual_execution"] is True
    assert payload["llm_enabled"] is False
    assert len(payload["stages"]) == 10
    assert runner.calls[0][1]["env"]["REGISTRO_ATLETA_LLM_ENABLED"] == "0"
    integrated_command = next(call[0] for call in runner.calls if "weekly-intelligence-report" in call[0])
    assert integrated_command[-4:] == ["--days", "7", "--reference-date", "2026-07-18"]
    assert "Nightly Intelligence Pipeline" in result.summary_path.read_text(encoding="utf-8")
    assert not (tmp_path / "data" / "locks" / "nightly-intelligence.lock").exists()


def test_critical_failure_stops_dependent_stages_and_is_audited(tmp_path: Path) -> None:
    runner = CriticalFailureRunner()

    result = run_nightly_intelligence(
        tmp_path,
        database_path=tmp_path / "club.db",
        profile="core",
        runner=runner,
    )

    assert result.status == "failed"
    assert runner.calls == 1
    assert result.stages[0].status == "failed"
    assert all(stage.status == "skipped" for stage in result.stages[1:])


def test_dry_run_lists_research_plan_without_creating_reports(tmp_path: Path) -> None:
    result = run_nightly_intelligence(
        tmp_path,
        database_path=tmp_path / "club.db",
        profile="research",
        dry_run=True,
    )

    assert result.status == "planned"
    assert all(stage.status == "planned" for stage in result.stages)
    assert result.manifest_path is None
    assert not (tmp_path / "data").exists()


def test_stale_lock_is_replaced(tmp_path: Path) -> None:
    lock = tmp_path / "data" / "locks" / "nightly-intelligence.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("not-a-pid", encoding="ascii")

    result = run_nightly_intelligence(
        tmp_path,
        database_path=tmp_path / "club.db",
        profile="core",
        runner=SuccessfulRunner(),
    )

    assert result.status == "success"
    assert not lock.exists()
