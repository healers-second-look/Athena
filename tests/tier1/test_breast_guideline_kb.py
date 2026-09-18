"""Shipped HR+/HER2- breast cancer guideline KB (issue #121).

The synthetic sarcoma fixture stays in guideline_kb/ and is still refused on
the default load of that directory. These tests isolate the unreviewed breast
file so we can assert it loads without allow_synthetic=True.
"""

from __future__ import annotations

import shutil

from secondlook.case.exhaustion import assess_exhaustion
from secondlook.case.state import CaseState
from secondlook.tier1.guideline_kb_loader import (
    GUIDELINE_KB_DIR,
    UNREVIEWED,
    load_guideline_kb,
    read_seed_file,
)

# Exact spelling used by exhaustion.py lookup and the eval set in
# tests/harness/eval_sets/synthesis_breast_cancer.py.
CANCER_TYPE = "HR+/HER2- breast cancer"

BREAST_KB = GUIDELINE_KB_DIR / "breast_hr_pos_her2_neg.yaml"


def test_shipped_breast_file_is_unreviewed_and_uses_eval_set_cancer_type():
    header, recs = read_seed_file(BREAST_KB)
    assert header["cancer_type"] == CANCER_TYPE
    assert header["cancer_type"] == "HR+/HER2- breast cancer"
    assert header["review_status"] == UNREVIEWED
    assert recs
    assert all(r.cancer_type == CANCER_TYPE for r in recs)
    assert all(r.review_status == UNREVIEWED for r in recs)


def test_breast_kb_loads_on_the_default_path_when_isolated(tmp_path):
    """allow_synthetic remains False — this is not a synthetic_placeholder file."""
    shutil.copy(BREAST_KB, tmp_path / BREAST_KB.name)
    kb, summary = load_guideline_kb(tmp_path, allow_synthetic=False)
    assert summary.rejected == []
    assert summary.synthetic_loaded == 0
    assert CANCER_TYPE in kb.by_cancer_type
    recs = kb.recommendations_for(CANCER_TYPE)
    assert recs
    regimens = {r.regimen for r in recs}
    assert "palbociclib + aromatase inhibitor" in regimens
    assert "alpelisib + fulvestrant" in regimens
    assert "olaparib" in regimens
    assert "elacestrant" in regimens
    assert "tamoxifen" in regimens


def test_exhaustion_lookup_uses_the_same_cancer_type_string(tmp_path):
    shutil.copy(BREAST_KB, tmp_path / BREAST_KB.name)
    kb, _ = load_guideline_kb(tmp_path, allow_synthetic=False)

    result = assess_exhaustion(CaseState(case_id="case-1"), CANCER_TYPE, kb)
    assert result.status == "not_exhausted"
    assert result.untried_standard_option is not None
    assert result.untried_standard_option.regimen == "palbociclib + aromatase inhibitor"
