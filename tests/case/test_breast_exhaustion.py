"""Stage-handling choice for the shipped HR+/HER2- guideline KB.

Deliberate, not accidental: adjuvant-only recs carry applicable_stages;
advanced and molecular recs omit it so stage=None stays evaluable (#51).
"""

from __future__ import annotations

from secondlook.case.exhaustion import (
    NO_APPLICABLE_REASON,
    STAGE_UNKNOWN_REASON,
    assess_exhaustion,
)
from secondlook.case.state import Alteration, CaseState, TreatmentEntry
from secondlook.tier1.guideline_kb_loader import (
    GUIDELINE_KB_DIR,
    GuidelineKnowledgeBase,
    read_seed_file,
)

# Exact spelling used by exhaustion.py lookup and the eval set in
# tests/harness/eval_sets/synthesis_breast_cancer.py.
CANCER_TYPE = "HR+/HER2- breast cancer"

BREAST_KB = GUIDELINE_KB_DIR / "breast_hr_pos_her2_neg.yaml"


def _kb() -> GuidelineKnowledgeBase:
    _, recs = read_seed_file(BREAST_KB)
    return GuidelineKnowledgeBase(by_cancer_type={CANCER_TYPE: tuple(recs)})


def _case(*, treatments=(), alterations=()) -> CaseState:
    return CaseState(case_id="case-1", treatments=treatments, alterations=alterations)


def test_stage_none_is_evaluable_because_advanced_recs_omit_applicable_stages():
    """Pinned decision: unknown stage must not collapse the MVP loop to unknown."""
    result = assess_exhaustion(_case(), CANCER_TYPE, _kb(), stage=None)
    assert result.status == "not_exhausted"
    assert result.reason != STAGE_UNKNOWN_REASON
    assert result.untried_standard_option is not None
    assert result.untried_standard_option.applicable_stages == ()


def test_adjuvant_recs_are_stage_gated_and_unresolved_when_stage_is_omitted():
    recs = [r for r in _kb().recommendations_for(CANCER_TYPE) if r.applicable_stages]
    assert recs, "adjuvant entries must carry applicable_stages"
    assert {r.regimen for r in recs} >= {
        "tamoxifen",
        "adjuvant aromatase inhibitor",
        "adjuvant tamoxifen",
    }
    assert all(r.applicable_stages == ("I", "II", "III") for r in recs)

    only_adjuvant = GuidelineKnowledgeBase(by_cancer_type={CANCER_TYPE: tuple(recs)})
    result = assess_exhaustion(_case(), CANCER_TYPE, only_adjuvant, stage=None)
    assert result.status == "unknown"
    assert result.reason == STAGE_UNKNOWN_REASON


def test_early_stage_surfaces_adjuvant_option_once_stage_is_known():
    recs = [r for r in _kb().recommendations_for(CANCER_TYPE) if r.applicable_stages]
    only_adjuvant = GuidelineKnowledgeBase(by_cancer_type={CANCER_TYPE: tuple(recs)})
    result = assess_exhaustion(_case(), CANCER_TYPE, only_adjuvant, stage="II")
    assert result.status == "not_exhausted"
    assert result.untried_standard_option is not None
    assert result.untried_standard_option.regimen == "tamoxifen"


def test_stage_iv_skips_adjuvant_recs_rather_than_marking_unknown():
    recs = [r for r in _kb().recommendations_for(CANCER_TYPE) if r.applicable_stages]
    only_adjuvant = GuidelineKnowledgeBase(by_cancer_type={CANCER_TYPE: tuple(recs)})
    result = assess_exhaustion(_case(), CANCER_TYPE, only_adjuvant, stage="IV")
    assert result.status == "unknown"
    assert result.reason == NO_APPLICABLE_REASON


def test_tried_advanced_options_with_omitted_stage_remain_unknown_due_to_adjuvant_gate():
    """If every stage-agnostic rec is tried, leftover stage-gated recs must
    not be silently skipped when stage is missing."""
    kb = _kb()
    agnostic = [r.regimen for r in kb.recommendations_for(CANCER_TYPE) if not r.applicable_stages]
    treatments = tuple(
        TreatmentEntry(regimen=name, line=1, action="started", reason=None, event_id=f"tx-{i}")
        for i, name in enumerate(sorted(set(agnostic)))
    )
    result = assess_exhaustion(_case(treatments=treatments), CANCER_TYPE, kb, stage=None)
    assert result.status == "unknown"
    assert result.reason == STAGE_UNKNOWN_REASON


def test_pik3ca_requirement_is_exact_gene_and_variant():
    kb = _kb()
    case = _case(
        alterations=(
            Alteration(
                gene="PIK3CA",
                variant="H1047R",
                variant_type=None,
                assay=None,
                tested_on=None,
                event_id="alt-1",
            ),
        )
    )
    result = assess_exhaustion(case, CANCER_TYPE, kb)
    assert result.status == "not_exhausted"
    # First untried in file order is still CDK4/6, not alpelisib.
    assert result.untried_standard_option is not None
    assert result.untried_standard_option.regimen == "palbociclib + aromatase inhibitor"
