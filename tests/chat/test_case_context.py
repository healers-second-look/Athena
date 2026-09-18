"""Tests for chat/case_context.describe_case -- pure CaseSnapshot rendering."""

from secondlook.case.state import (
    Alteration,
    BiomarkerValue,
    CaseState,
    DiseaseAssessment,
    TreatmentEntry,
)
from secondlook.chat.case_context import CaseSnapshot, Diagnosis, describe_case


def _full_state() -> CaseState:
    return CaseState(
        case_id="case-nsclc-1",
        alterations=(
            Alteration(
                gene="EGFR",
                variant="T790M",
                variant_type="missense",
                assay="NGS panel",
                tested_on="2026-01-15",
                event_id="e1",
            ),
            Alteration(
                gene="EGFR",
                variant="L858R",
                variant_type=None,
                assay=None,
                tested_on=None,
                event_id="e2",
            ),
        ),
        biomarkers={
            "PD-L1": BiomarkerValue(
                name="PD-L1",
                value=62.0,
                unit="%",
                measured_on="2026-02-01",
                event_id="e3",
            ),
        },
        treatments=(
            TreatmentEntry(
                regimen="osimertinib",
                line=1,
                action="started",
                reason="first-line EGFR TKI",
                event_id="e4",
            ),
            TreatmentEntry(
                regimen="osimertinib",
                line=1,
                action="stopped",
                reason="progression",
                event_id="e5",
            ),
        ),
        assessments=(
            DiseaseAssessment(
                status="stable",
                sites=["lung"],
                assessed_on="2026-03-01",
                event_id="e6",
            ),
            DiseaseAssessment(
                status="progression",
                sites=["lung", "liver"],
                assessed_on="2026-06-01",
                event_id="e7",
            ),
        ),
        clinical_questions=("next-line options after osimertinib?", "trial eligibility?"),
    )


def test_describe_case_renders_headline_fields_from_state():
    lines = describe_case(CaseSnapshot(state=_full_state()))
    text = "\n".join(lines)
    assert "EGFR" in text and "T790M" in text
    assert "L858R" in text
    assert "osimertinib" in text
    assert "started" in text
    assert "stopped" in text
    assert "progression" in text
    assert "trial eligibility?" in text
    assert "lung" in text
    assert "liver" in text


def test_describe_case_uses_not_recorded_for_missing_headline_fields():
    lines = describe_case(CaseSnapshot(state=CaseState(case_id="empty")))
    text = "\n".join(lines).lower()
    assert "not recorded" in text
    assert "cancer" in text or "diagnosis" in text
    assert "alteration" in text
    assert "treatment" in text
    assert "assessment" in text
    assert "question" in text


def test_describe_case_omits_biomarker_section_when_empty():
    lines = describe_case(CaseSnapshot(state=CaseState(case_id="empty")))
    text = "\n".join(lines).lower()
    assert "biomarker" not in text
    assert "pd-l1" not in text


def test_describe_case_is_deterministic():
    state = _full_state()
    snapshot = CaseSnapshot(state=state, diagnosis=Diagnosis(cancer_type="NSCLC"))
    assert describe_case(snapshot) == describe_case(snapshot)


def test_diagnosis_reaches_the_headline_line():
    """The static half of the case is P0 and must not read "not recorded"."""
    lines = describe_case(
        CaseSnapshot(
            state=CaseState(case_id="c1"),
            diagnosis=Diagnosis(
                cancer_type="infantile fibrosarcoma",
                primary_site="soft tissue, thigh",
                histology="spindle cell",
                stage="locally advanced",
            ),
        )
    )
    headline = lines[0]
    assert "infantile fibrosarcoma" in headline
    assert "spindle cell" in headline
    assert "primary site soft tissue, thigh" in headline
    assert "stage locally advanced" in headline
    assert "not recorded" not in headline


def test_diagnosis_absent_still_says_not_recorded():
    lines = describe_case(CaseSnapshot(state=CaseState(case_id="c1"), diagnosis=None))
    assert lines[0] == "Cancer type / diagnosis: not recorded"
    empty = describe_case(CaseSnapshot(state=CaseState(case_id="c1"), diagnosis=Diagnosis()))
    assert empty[0] == "Cancer type / diagnosis: not recorded"
