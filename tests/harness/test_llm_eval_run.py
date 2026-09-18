"""CLI tests for validation/llm_eval_run.py -- no live LLM."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_runner():
    path = Path(__file__).resolve().parents[2] / "validation" / "llm_eval_run.py"
    spec = importlib.util.spec_from_file_location("llm_eval_run", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_grounded_comparison_with_criteria_extraction_exits_with_clear_error(capsys, monkeypatch):
    runner = _load_runner()
    called: list[str] = []

    def boom(*args, **kwargs):
        called.append("ran")
        raise AssertionError("must not run criteria extraction when the flag is invalid")

    monkeypatch.setattr(runner, "run_criteria_extraction", boom)
    code = runner.main(["--subsystem", "criteria_extraction", "--grounded-comparison"])
    captured = capsys.readouterr()
    combined = (captured.err + captured.out).lower()
    assert code != 0
    assert called == []
    assert "grounded-comparison" in combined or "ungrounded" in combined
    assert "criteria_extraction" in combined


def test_grounded_comparison_with_intake_exits_with_clear_error(capsys, monkeypatch):
    runner = _load_runner()
    called: list[str] = []

    def boom(*args, **kwargs):
        called.append("ran")
        raise AssertionError("must not run intake when the flag is invalid")

    monkeypatch.setattr(runner, "run_intake_eval", boom)
    code = runner.main(["--subsystem", "intake", "--grounded-comparison"])
    captured = capsys.readouterr()
    combined = (captured.err + captured.out).lower()
    assert code != 0
    assert called == []
    assert "grounded-comparison" in combined or "ungrounded" in combined
    assert "intake" in combined


# --- issue #122: --cases flag ------------------------------------------------


def _fake_result(runner, subsystem: str):
    return runner.EvalResult(
        subsystem=subsystem,
        prompt_template_id="test-template",
        pass_rate=1.0,
        threshold=0.7,
        safety_violations=[],
        verdict="PASS",
    )


def test_cases_defaults_to_general_only(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "RESULTS_PATH", tmp_path / "results.md")
    seen: list[str] = []

    def fake_run_synthesis_eval(cases_key="general"):
        seen.append(cases_key)
        return _fake_result(runner, runner.SYNTHESIS_SUBSYSTEM)

    monkeypatch.setattr(runner, "run_synthesis_eval", fake_run_synthesis_eval)
    code = runner.main(["--subsystem", "synthesis"])
    assert code == 0
    assert seen == ["general"]


def test_cases_breast_cancer_runs_only_that_set(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "RESULTS_PATH", tmp_path / "results.md")
    seen: list[str] = []

    def fake_run_synthesis_eval(cases_key="general"):
        seen.append(cases_key)
        return _fake_result(runner, runner.SYNTHESIS_SUBSYSTEM)

    monkeypatch.setattr(runner, "run_synthesis_eval", fake_run_synthesis_eval)
    code = runner.main(["--subsystem", "synthesis", "--cases", "breast_cancer"])
    assert code == 0
    assert seen == ["breast_cancer"]


def test_cases_both_runs_general_then_breast_cancer_separately(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "RESULTS_PATH", tmp_path / "results.md")
    seen: list[str] = []

    def fake_run_synthesis_eval(cases_key="general"):
        seen.append(cases_key)
        return _fake_result(runner, runner.SYNTHESIS_SUBSYSTEM)

    monkeypatch.setattr(runner, "run_synthesis_eval", fake_run_synthesis_eval)
    code = runner.main(["--subsystem", "synthesis", "--cases", "both"])
    assert code == 0
    assert seen == ["general", "breast_cancer"]


def test_cases_flag_is_ignored_for_non_synthesis_subsystems(tmp_path, monkeypatch):
    """--cases only means something for synthesis -- passing it alongside
    --subsystem intake must not error or change intake's behavior.
    """
    runner = _load_runner()
    monkeypatch.setattr(runner, "RESULTS_PATH", tmp_path / "results.md")

    def fake_run_intake_eval():
        return _fake_result(runner, "intake")

    monkeypatch.setattr(runner, "run_intake_eval", fake_run_intake_eval)
    code = runner.main(["--subsystem", "intake", "--cases", "breast_cancer"])
    assert code == 0


def test_citation_acceptance_subsystem_runs_the_adapter(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "RESULTS_PATH", tmp_path / "results.md")
    called: list[str] = []

    def fake_run_citation_acceptance():
        called.append("ran")
        return _fake_result(runner, "synthesis.citation_acceptance")

    monkeypatch.setattr(runner, "run_citation_acceptance_eval", fake_run_citation_acceptance)
    code = runner.main(["--subsystem", "citation_acceptance"])
    assert code == 0
    assert called == ["ran"]
    report = (tmp_path / "results.md").read_text()
    assert "synthesis.citation_acceptance" in report


def test_all_includes_citation_acceptance(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "RESULTS_PATH", tmp_path / "results.md")
    called: list[str] = []

    monkeypatch.setattr(
        runner,
        "run_synthesis_eval",
        lambda cases_key="general": _fake_result(runner, "synthesis"),
    )
    monkeypatch.setattr(
        runner,
        "run_criteria_extraction",
        lambda: _fake_result(runner, "criteria_extraction"),
    )
    monkeypatch.setattr(
        runner,
        "run_intake_eval",
        lambda: _fake_result(runner, "intake"),
    )

    def fake_run_citation_acceptance():
        called.append("ran")
        return _fake_result(runner, "synthesis.citation_acceptance")

    monkeypatch.setattr(runner, "run_citation_acceptance_eval", fake_run_citation_acceptance)
    code = runner.main(["--subsystem", "all"])
    assert code == 0
    assert called == ["ran"]


def test_grounded_comparison_with_citation_acceptance_exits_with_clear_error(capsys, monkeypatch):
    runner = _load_runner()
    called: list[str] = []

    def boom(*args, **kwargs):
        called.append("ran")
        raise AssertionError("must not run citation acceptance when the flag is invalid")

    monkeypatch.setattr(runner, "run_citation_acceptance_eval", boom)
    code = runner.main(["--subsystem", "citation_acceptance", "--grounded-comparison"])
    captured = capsys.readouterr()
    combined = (captured.err + captured.out).lower()
    assert code != 0
    assert called == []
    assert "grounded-comparison" in combined or "ungrounded" in combined
    assert "citation_acceptance" in combined


def test_breast_cancer_subsystem_label_is_distinguishable_in_the_report(monkeypatch):
    """validation/llm_eval_results.md must say which eval set a result
    came from -- an auditable report that doesn't say what it evaluated
    is not auditable.
    """
    runner = _load_runner()

    class _FakeClient:
        def complete(self, *_a, **_k):
            raise AssertionError("should not be called -- run_eval_set uses completion_fn")

    monkeypatch.setattr(runner, "get_llm_client", lambda: _FakeClient())

    def fake_completion_fn(*_a, **_k):
        def complete(_case_input):
            return {"text": "ok", "cited_ids": [], "llm_used": True}

        return complete

    monkeypatch.setattr(runner, "grounded_completion_fn", fake_completion_fn)
    monkeypatch.setattr(runner, "score_synthesis", lambda expected, actual, tolerance: (True, []))

    result = runner.run_synthesis_eval("breast_cancer")
    assert "breast_cancer" in result.subsystem

    general_result = runner.run_synthesis_eval("general")
    assert "breast_cancer" not in general_result.subsystem
