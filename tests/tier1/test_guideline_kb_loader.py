"""Guideline KB loader: what this loader refuses to write.

Stricter than a warning on purpose. A malformed recommendation, or a
synthetic placeholder loaded on the default path, must not become citable
guidance.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from secondlook.tier1.guideline_kb_loader import (
    ALLOWED_REVIEW_STATUSES,
    GUIDELINE_KB_DIR,
    SYNTHETIC_PLACEHOLDER,
    GuidelineConfigError,
    load_guideline_kb,
    read_seed_file,
    validate_recommendation,
)

SYNTHETIC_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "guideline_kb"

CANCER = "TEST_SARCOMA_SYNTHETIC"
INSTRUMENT = "[SYNTHETIC EXAMPLE — NOT REAL GUIDANCE] Example Oncology Society Guidelines v0"
SOURCE_URL = "https://example.invalid/synthetic-guideline"


def entry(**overrides):
    base = {
        "regimen": "synthetic-agent-alpha",
        "line": 1,
        "applicable_stages": [],
        "instrument": INSTRUMENT,
        "source_url": SOURCE_URL,
    }
    base.update(overrides)
    return base


def seed_payload(**overrides):
    payload = {
        "config_version": "test.1",
        "cancer_type": CANCER,
        "review_status": SYNTHETIC_PLACEHOLDER,
        "recommendations": [entry()],
    }
    payload.update(overrides)
    return payload


def seed_file(tmp_path, name="seed.yaml", **overrides):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(seed_payload(**overrides), allow_unicode=True), encoding="utf-8")
    return path


class TestRequiredCitations:
    @pytest.mark.parametrize("field", ["regimen", "instrument", "source_url"])
    def test_a_recommendation_without_its_citation_is_refused(self, field, tmp_path):
        with pytest.raises(GuidelineConfigError, match=field):
            validate_recommendation(
                entry(**{field: ""}),
                cancer_type=CANCER,
                review_status=SYNTHETIC_PLACEHOLDER,
                path=tmp_path / "x.yaml",
            )


class TestSeedFiles:
    def test_reads_a_well_formed_file(self, tmp_path):
        header, recs = read_seed_file(seed_file(tmp_path))
        assert header["cancer_type"] == CANCER
        assert header["review_status"] == SYNTHETIC_PLACEHOLDER
        assert len(recs) == 1
        assert recs[0].regimen == "synthetic-agent-alpha"
        assert recs[0].instrument == INSTRUMENT

    def test_file_without_cancer_type_is_refused(self, tmp_path):
        path = seed_file(tmp_path)
        path.write_text(
            yaml.safe_dump(
                {
                    "config_version": "test.1",
                    "review_status": SYNTHETIC_PLACEHOLDER,
                    "recommendations": [entry()],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(GuidelineConfigError, match="cancer_type"):
            read_seed_file(path)

    def test_unknown_review_status_is_refused(self, tmp_path):
        path = seed_file(tmp_path, review_status="looks_legit")
        with pytest.raises(GuidelineConfigError, match="review_status"):
            read_seed_file(path)
        assert "looks_legit" not in ALLOWED_REVIEW_STATUSES

    def test_a_malformed_file_is_rejected_whole_not_partially_loaded(self, tmp_path):
        """A half-loaded cancer type is worse than an absent one."""
        seed_file(
            tmp_path,
            "good.yaml",
            review_status="reviewed",
            cancer_type="TEST_OTHER_SYNTHETIC",
        )
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            yaml.safe_dump(
                seed_payload(
                    review_status="reviewed",
                    recommendations=[entry(), entry(source_url="")],
                )
            ),
            encoding="utf-8",
        )
        kb, summary = load_guideline_kb(tmp_path, allow_synthetic=False)
        assert summary.files_read == 1
        assert summary.recommendations_loaded == 1
        assert len(summary.rejected) == 1
        assert kb.recommendations_for("TEST_OTHER_SYNTHETIC")
        assert not kb.recommendations_for(CANCER)


class TestSyntheticSafetyGate:
    def test_synthetic_placeholder_refused_without_allow_synthetic(self, tmp_path):
        seed_file(tmp_path)
        with pytest.raises(GuidelineConfigError, match=SYNTHETIC_PLACEHOLDER):
            load_guideline_kb(tmp_path, allow_synthetic=False)

    def test_synthetic_placeholder_accepted_with_allow_synthetic(self, tmp_path):
        seed_file(tmp_path)
        kb, summary = load_guideline_kb(tmp_path, allow_synthetic=True)
        assert summary.files_read == 1
        assert summary.recommendations_loaded == 1
        assert summary.synthetic_loaded == 1
        assert "synthetic_placeholder" in summary.render()
        assert kb.recommendations_for(CANCER)[0].regimen == "synthetic-agent-alpha"

    def test_synthetic_fixture_on_disk_still_trips_the_gate(self):
        """The shipped synthetic file lives under tests/ so it cannot poison
        the production directory, but it is still a real file on disk and the
        gate must reject it exactly as it rejects a generated one."""
        with pytest.raises(GuidelineConfigError, match=SYNTHETIC_PLACEHOLDER):
            load_guideline_kb(SYNTHETIC_FIXTURE_DIR, allow_synthetic=False)

    def test_synthetic_fixture_on_disk_loads_with_allow_synthetic(self):
        kb, summary = load_guideline_kb(SYNTHETIC_FIXTURE_DIR, allow_synthetic=True)
        assert summary.rejected == []
        recs = kb.recommendations_for(CANCER)
        assert recs
        assert all(r.review_status == SYNTHETIC_PLACEHOLDER for r in recs)
        assert all("[SYNTHETIC EXAMPLE" in r.instrument for r in recs)


class TestShippedKnowledgeBase:
    def test_shipped_kb_loads_on_the_default_path(self):
        """guideline_kb/ holds only real, reviewable content. A synthetic file
        placed there would fail this test rather than being silently tolerated
        — that is the point of keeping the fixture under tests/."""
        kb, summary = load_guideline_kb(GUIDELINE_KB_DIR, allow_synthetic=False)
        assert summary.rejected == []
        assert summary.synthetic_loaded == 0
        assert summary.recommendations_loaded > 0
        assert kb.by_cancer_type
