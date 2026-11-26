"""The study chat's opening briefing in each arm."""

from __future__ import annotations

from secondlook.study.cases import DEFAULT_CASE_SET_DIR, load_case_set
from secondlook.study.chat import briefing_text

AVU_002 = next(
    c
    for c in load_case_set(DEFAULT_CASE_SET_DIR / "athena_vs_usual_v1.yaml").cases
    if c.case_id == "avu-002"
)


def _current_section(text: str) -> str:
    return text.split("My current findings:")[1].split("No longer current")[0]


def test_athena_full_briefing_does_not_list_a_superseded_finding_as_current():
    text = briefing_text(AVU_002, show_supersessions=True)
    superseded = AVU_002.system_output.reported_supersessions[0]
    claim = next(f.claim for f in AVU_002.system_output.findings if f.id == superseded.finding_id)
    assert claim not in _current_section(text)
    assert "No longer current" in text
    assert f"(superseded): {claim} [1] -- {superseded.note}" in text
    # The other findings stay current, keeping their citation numbers.
    assert "Finding 2: " in _current_section(text)
    assert "Finding 3: " in _current_section(text)


def test_default_briefing_is_unchanged_for_the_three_arm_chat():
    # The diff-first study's chat arm is deliberately not given the change report.
    text = briefing_text(AVU_002)
    assert "superseded" not in text.lower()
    for finding in AVU_002.system_output.findings:
        assert finding.claim in _current_section(text)


def test_briefing_uses_only_the_systems_report_not_ground_truth():
    text = briefing_text(AVU_002, show_supersessions=True)
    for finding in AVU_002.system_output.findings:
        if finding.invalidated_by:
            assert finding.invalidated_by not in text
    for issue in AVU_002.seeded_issues:
        assert issue.description not in text
