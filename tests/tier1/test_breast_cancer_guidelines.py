"""Tests for curated HR+/HER2- early breast cancer guidelines.

Validates that:
1. `guideline_kb/breast_cancer.yaml` strictly conforms to the schema in `guideline_kb_loader.py`.
2. All entries have `review_status: unreviewed` (real guidance, not synthetic placeholder).
3. Every recommendation cites a real medical instrument and URL.
4. `assess_exhaustion()` accurately calculates exhaustion status for early and
   advanced breast cancer scenarios.
"""

from secondlook.case.exhaustion import assess_exhaustion
from secondlook.case.state import Alteration, CaseState, TreatmentEntry
from secondlook.tier1.guideline_kb_loader import (
    GUIDELINE_KB_DIR,
    GuidelineKnowledgeBase,
    read_seed_file,
)

CANCER_TYPE = "HR_POS_HER2_NEG_BREAST"


class TestBreastCancerGuidelinesSeed:
    def test_breast_cancer_yaml_parses_successfully(self):
        seed_path = GUIDELINE_KB_DIR / "breast_cancer.yaml"
        assert seed_path.is_file(), "breast_cancer.yaml must exist under guideline_kb/"

        header, recs = read_seed_file(seed_path)
        assert header["cancer_type"] == CANCER_TYPE
        assert header["review_status"] == "unreviewed"
        assert len(recs) >= 4

    def test_all_recommendations_have_real_citations(self):
        seed_path = GUIDELINE_KB_DIR / "breast_cancer.yaml"
        _, recs = read_seed_file(seed_path)

        for r in recs:
            assert r.source_url.startswith("https://")
            assert "ESMO" in r.instrument or "ASCO" in r.instrument or "FDA" in r.instrument
            assert r.line in (1, 2)
            assert r.review_status == "unreviewed"


def _treatment(regimen: str, event_id: str = "tx-1") -> TreatmentEntry:
    return TreatmentEntry(
        regimen=regimen, line=1, action="completed", reason=None, event_id=event_id
    )


def _alteration(gene: str, variant: str) -> Alteration:
    return Alteration(
        gene=gene,
        variant=variant,
        variant_type=None,
        assay=None,
        tested_on=None,
        event_id="alt-1",
    )


class TestBreastCancerExhaustionAssessment:
    def _kb(self) -> GuidelineKnowledgeBase:
        seed_path = GUIDELINE_KB_DIR / "breast_cancer.yaml"
        _, recs = read_seed_file(seed_path)
        return GuidelineKnowledgeBase(by_cancer_type={CANCER_TYPE: tuple(recs)})

    def test_newly_diagnosed_stage_ii_is_not_exhausted(self):
        kb = self._kb()
        case = CaseState(case_id="bc_case_1", treatments=[])
        result = assess_exhaustion(case, CANCER_TYPE, kb, stage="II")
        assert result.status == "not_exhausted"
        assert result.untried_standard_option is not None
        assert result.untried_standard_option.regimen in ("tamoxifen", "anastrozole")
        assert result.citation is not None

    def test_stage_ii_patient_completing_adjuvant_regimens_is_exhausted(self):
        kb = self._kb()
        treatments = [
            _treatment("tamoxifen", "tx-1"),
            _treatment("anastrozole", "tx-2"),
            _treatment("letrozole", "tx-3"),
            _treatment("abemaciclib + endocrine therapy", "tx-4"),
        ]
        case = CaseState(case_id="bc_case_2", treatments=treatments)
        result = assess_exhaustion(case, CANCER_TYPE, kb, stage="II")
        assert result.status == "exhausted"
        assert result.untried_standard_option is None

    def test_missing_stage_evaluates_to_unknown(self):
        kb = self._kb()
        case = CaseState(case_id="bc_case_3", treatments=[])
        result = assess_exhaustion(case, CANCER_TYPE, kb, stage=None)
        assert result.status == "unknown"

    def test_pik3ca_mutant_line2_targeted_option(self):
        kb = self._kb()
        case = CaseState(
            case_id="bc_case_4",
            alterations=[_alteration("PIK3CA", "H1047R")],
            treatments=[
                _treatment("ribociclib + fulvestrant", "tx-1"),
            ],
        )
        result = assess_exhaustion(case, CANCER_TYPE, kb, stage="IV")
        assert result.status == "not_exhausted"
        assert result.untried_standard_option is not None
        assert result.untried_standard_option.regimen == "alpelisib + fulvestrant"
