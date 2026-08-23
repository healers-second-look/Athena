"""Criteria extraction: what it structures, and what it refuses to guess."""

import json

import pytest

from secondlook.tier1.criteria_extraction import (
    LlmAssistedExtractor,
    Predicate,
    RuleBasedExtractor,
    criteria_fingerprint,
    split_criteria,
)


@pytest.fixture
def extractor():
    return RuleBasedExtractor()


class TestSplitting:
    def test_headers_switch_section(self):
        pairs = split_criteria("Inclusion Criteria:\n* A\nExclusion Criteria:\n* B\n")
        assert pairs == [("inclusion", "A"), ("exclusion", "B")]

    def test_qualified_headers_are_recognised(self):
        """Sponsors qualify these freely. Requiring the line to end after
        'Criteria' left whole sections marked `unknown`, losing the sense that
        inverts every criterion's meaning."""
        pairs = split_criteria(
            "Inclusion Criteria for All Patients\n* A\nExclusion Criteria (Cohort B):\n* B\n"
        )
        assert [section for section, _ in pairs] == ["inclusion", "exclusion"]

    def test_text_before_any_header_is_unknown_not_assumed_inclusion(self):
        """Guessing here would invert every criterion from a sponsor who omits
        the headers."""
        assert split_criteria("* Something\n")[0][0] == "unknown"

    def test_registry_backslash_escapes_are_undone(self):
        """ClinicalTrials.gov escapes its own comparison operators; left in
        place they defeat every numeric pattern."""
        assert split_criteria(r"* Bilirubin \> 3.0")[0][1] == "Bilirubin > 3.0"

    @pytest.mark.parametrize("bullet", ["*", "-", "•", "1.", "2)"])
    def test_bullet_styles(self, bullet):
        assert split_criteria(f"{bullet} Age 18 years or older")[0][1] == "Age 18 years or older"


class TestAgeAndEcog:
    @pytest.mark.parametrize(
        "line",
        [
            "ECOG performance status 0-2",
            "ECOG <= 2",
            "ECOG performance status of 2",
            "ECOG 2",
        ],
    )
    def test_ecog_cap_variants(self, extractor, line):
        predicate = extractor._line_to_predicate("inclusion", line)
        assert predicate.type == "ECOG_MAX"
        assert predicate.value == 2.0

    def test_ecog_range_takes_the_upper_bound(self, extractor):
        """'0-2' also contains a bare '0'. Taking the lower bound as the cap
        would exclude exactly the patients the trial is most open to."""
        assert extractor._line_to_predicate("inclusion", "ECOG 0-2").value == 2.0

    def test_age_lower_bound(self, extractor):
        predicate = extractor._line_to_predicate("inclusion", "Age 18 years or older")
        assert predicate.type == "AGE_RANGE"
        assert predicate.value == "18-"


class TestRefusesToGuess:
    def test_biomarker_without_a_nameable_marker_is_unparseable(self, extractor):
        """Measured C1 failure: 'Subjects testing positive for HIV' in a
        transplant workup is not a tumour-biomarker criterion."""
        predicate = extractor._line_to_predicate(
            "exclusion", "Subjects testing positive for HIV may be rejected"
        )
        assert predicate.type == "UNPARSEABLE"

    def test_prior_therapy_without_a_nameable_agent_is_unparseable(self, extractor):
        predicate = extractor._line_to_predicate(
            "exclusion", "Received prior systemic therapy of any kind"
        )
        assert predicate.type == "UNPARSEABLE"
        assert "no agent could be named" in predicate.reason

    def test_named_agent_is_extracted(self, extractor):
        predicate = extractor._line_to_predicate(
            "exclusion", "Prior treatment with a PARP inhibitor"
        )
        assert predicate.type == "PRIOR_THERAPY_EXCLUDES"
        assert predicate.subject == "PARP inhibitor"
        assert predicate.comparison == "absent"

    def test_named_marker_is_extracted(self, extractor):
        predicate = extractor._line_to_predicate(
            "inclusion", "Tumor must show loss of INI1 by immunohistochemistry"
        )
        assert predicate.type == "BIOMARKER_REQUIRES"
        assert predicate.subject == "INI1"

    @pytest.mark.parametrize("token", ["HIV", "ECOG", "DLCO", "HLA", "MRI"])
    def test_non_gene_uppercase_tokens_are_not_treated_as_markers(self, extractor, token):
        predicate = extractor._line_to_predicate(
            "inclusion", f"Documented {token} mutation status required"
        )
        assert predicate.subject != token


class TestNothingIsDropped:
    def test_every_line_produces_exactly_one_predicate(self, extractor):
        """A criterion silently discarded reads downstream as one the patient
        satisfies."""
        text = "Inclusion Criteria:\n* A thing\n* Another thing\nExclusion Criteria:\n* A third\n"
        result = extractor.extract("NCT1", text)
        assert result.lines_seen == 3
        assert len(result.predicates) == 3

    def test_unrecognised_lines_become_unparseable_not_nothing(self, extractor):
        result = extractor.extract("NCT1", "* Entirely idiosyncratic sponsor prose\n")
        assert [p.type for p in result.predicates] == ["UNPARSEABLE"]


class TestLlmAssistedCaching:
    def test_cache_key_is_the_text_not_the_registry_id(self):
        """Registries edit records in place. Keying on the id would serve a
        cached parse of text that no longer exists."""
        assert criteria_fingerprint("a") != criteria_fingerprint("b")

    def test_model_is_called_once_then_served_from_cache(self, tmp_path):
        calls = []

        def model(text):
            calls.append(text)
            return [{"type": "ECOG_MAX", "source_text": text, "value": 1.0}]

        extractor = LlmAssistedExtractor(model, cache_dir=tmp_path)
        first = extractor.extract("NCT1", "ECOG <= 1")
        second = extractor.extract("NCT1", "ECOG <= 1")
        assert len(calls) == 1
        assert extractor.cache_hits == 1
        assert first.predicates[0].value == second.predicates[0].value == 1.0

    def test_a_model_returning_the_wrong_shape_falls_back_not_crashes(self, tmp_path):
        """A trial with rule-based predicates is worth more than no trial."""

        def broken(text):
            return [{"unexpected": "shape"}]

        extractor = LlmAssistedExtractor(broken, cache_dir=tmp_path)
        result = extractor.extract("NCT1", "* ECOG <= 1\n")
        assert extractor.fallbacks == 1
        assert result.extractor == "rule_based"
        assert result.predicates[0].type == "ECOG_MAX"

    def test_unreadable_cache_is_ignored_not_fatal(self, tmp_path):
        (tmp_path / f"{criteria_fingerprint('x')}.json").write_text("{not json")
        extractor = LlmAssistedExtractor(
            lambda t: [{"type": "UNPARSEABLE", "source_text": t}], cache_dir=tmp_path
        )
        assert extractor.extract("NCT1", "x").predicates


class TestPredicateRoundTrip:
    def test_to_dict_from_dict(self):
        predicate = Predicate(
            type="ECOG_MAX",
            source_text="ECOG <= 2",
            section="inclusion",
            subject="ECOG",
            comparison="at_most",
            value=2.0,
        )
        assert Predicate.from_dict(json.loads(json.dumps(predicate.to_dict()))) == predicate
