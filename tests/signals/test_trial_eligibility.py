"""Trial matching: bucketing, and the refusal to treat absence as satisfaction."""

import pytest

from secondlook.case.state import Alteration, BiomarkerValue, CaseState, TreatmentEntry
from secondlook.signals.trial_eligibility import match_trial, match_trials
from secondlook.tier1.criteria_extraction import Predicate


def age(years: float) -> BiomarkerValue:
    return BiomarkerValue("age", years, "years", None, "e1")


def ecog(score: float) -> BiomarkerValue:
    return BiomarkerValue("ECOG", score, None, None, "e2")


AGE_18_PLUS = Predicate(
    type="AGE_RANGE",
    source_text="Age 18 years or older",
    section="inclusion",
    subject="age",
    comparison="at_least",
    value="18-",
)
ECOG_MAX_2 = Predicate(
    type="ECOG_MAX",
    source_text="ECOG 0-2",
    section="inclusion",
    subject="ECOG",
    comparison="at_most",
    value=2.0,
)
NO_PRIOR_PARP = Predicate(
    type="PRIOR_THERAPY_EXCLUDES",
    source_text="Prior PARP inhibitor",
    section="exclusion",
    subject="PARP inhibitor",
    comparison="absent",
)


class TestAbsenceIsNeverSatisfaction:
    def test_missing_age_is_unresolved_not_matched(self):
        """An unrecorded age is not an eligible age."""
        result = match_trial("NCT1", [AGE_18_PLUS], CaseState(case_id="c"))
        assert result.bucket == "needs_verification"
        assert result.unresolved_criteria == ["Age 18 years or older"]

    def test_missing_ecog_is_unresolved_not_zero(self):
        result = match_trial("NCT1", [ECOG_MAX_2], CaseState(case_id="c"))
        assert result.outcomes[0].outcome == "unresolved"
        assert "not a score of 0" in result.outcomes[0].explanation

    def test_empty_treatment_history_does_not_satisfy_an_exclusion(self):
        """Absent history is not an absence of treatment."""
        result = match_trial("NCT1", [NO_PRIOR_PARP], CaseState(case_id="c"))
        assert result.outcomes[0].outcome == "unresolved"

    def test_untested_biomarker_is_unresolved_not_negative(self):
        predicate = Predicate(
            type="BIOMARKER_REQUIRES",
            source_text="INI1 loss",
            section="inclusion",
            subject="INI1",
            comparison="present",
        )
        result = match_trial("NCT1", [predicate], CaseState(case_id="c"))
        assert result.outcomes[0].outcome == "unresolved"
        assert "not the same as testing negative" in result.outcomes[0].explanation


class TestBucketing:
    def test_all_matched_is_highly_compatible(self):
        case = CaseState(
            case_id="c",
            biomarkers={"age": age(52), "ECOG": ecog(1)},
            treatments=(TreatmentEntry("carboplatin", 1, "started", None, "e3"),),
        )
        result = match_trial("NCT1", [AGE_18_PLUS, ECOG_MAX_2, NO_PRIOR_PARP], case)
        assert result.bucket == "highly_compatible"
        assert len(result.matched_criteria) == 3

    def test_one_violation_is_probably_incompatible(self):
        case = CaseState(case_id="c", biomarkers={"age": age(12), "ECOG": ecog(1)})
        result = match_trial("NCT1", [AGE_18_PLUS, ECOG_MAX_2], case)
        assert result.bucket == "probably_incompatible"
        assert result.violated_criteria == ["Age 18 years or older"]

    def test_violation_beats_unresolved(self):
        """A criterion the case definitively fails is not made uncertain by
        another criterion being unknown."""
        case = CaseState(case_id="c", biomarkers={"age": age(12)})
        result = match_trial("NCT1", [AGE_18_PLUS, ECOG_MAX_2], case)
        assert result.bucket == "probably_incompatible"

    def test_a_trial_with_no_predicates_is_not_highly_compatible(self):
        """'Every criterion passed' is vacuously true of an empty list, and
        bucketing an unread trial as a strong match is the worst error here."""
        assert match_trial("NCT1", [], CaseState(case_id="c")).bucket == "needs_verification"

    def test_prior_therapy_present_violates_an_exclusion(self):
        case = CaseState(
            case_id="c",
            treatments=(TreatmentEntry("PARP inhibitor maintenance", 2, "started", None, "e"),),
        )
        result = match_trial("NCT1", [NO_PRIOR_PARP], case)
        assert result.bucket == "probably_incompatible"

    def test_alterations_satisfy_a_biomarker_requirement(self):
        case = CaseState(
            case_id="c",
            alterations=(Alteration("EGFR", "T790M", "missense", "NGS", None, "e"),),
        )
        predicate = Predicate(
            type="BIOMARKER_REQUIRES",
            source_text="EGFR mutation",
            section="inclusion",
            subject="EGFR",
            comparison="present",
        )
        assert match_trial("NCT1", [predicate], case).bucket == "highly_compatible"


class TestUnevaluableTypes:
    def test_stage_cannot_be_evaluated_and_says_so(self):
        """CaseState has no stage field. The gap is surfaced, not hidden."""
        predicate = Predicate(
            type="DISEASE_STAGE_REQUIRES",
            source_text="Stage IV disease",
            section="inclusion",
            subject="stage",
            comparison="equals",
            value="IV",
        )
        result = match_trial("NCT1", [predicate], CaseState(case_id="c"))
        assert result.outcomes[0].outcome == "unresolved"
        assert result.unresolvable_predicate_types() == {"DISEASE_STAGE_REQUIRES": 1}

    def test_unparseable_carries_its_reason_forward(self):
        predicate = Predicate(
            type="UNPARSEABLE",
            source_text="Sponsor prose",
            section="inclusion",
            reason="no rule matched this line",
        )
        result = match_trial("NCT1", [predicate], CaseState(case_id="c"))
        assert result.outcomes[0].explanation == "no rule matched this line"


class TestOrdering:
    def test_most_compatible_first_and_ties_are_stable(self):
        case = CaseState(case_id="c", biomarkers={"age": age(52), "ECOG": ecog(1)})
        results = match_trials(
            {
                "NCT_B": [AGE_18_PLUS, ECOG_MAX_2],
                "NCT_A": [
                    Predicate(
                        type="AGE_RANGE",
                        source_text="Age 65 or older",
                        section="inclusion",
                        subject="age",
                        comparison="at_least",
                        value="65-",
                    )
                ],
                "NCT_C": [AGE_18_PLUS, ECOG_MAX_2],
            },
            case,
        )
        assert [r.trial_id for r in results] == ["NCT_B", "NCT_C", "NCT_A"]
        assert results[-1].bucket == "probably_incompatible"


class TestEveryOutcomeIsExplained:
    def test_no_outcome_lacks_an_explanation(self):
        """A bucket a clinician cannot interrogate is not usable."""
        case = CaseState(case_id="c", biomarkers={"age": age(52)})
        result = match_trial("NCT1", [AGE_18_PLUS, ECOG_MAX_2, NO_PRIOR_PARP], case)
        assert all(o.explanation.strip() for o in result.outcomes)


class TestAgainstTheAnnotatedCorpus:
    def test_real_fixture_end_to_end(self):
        """Extraction and matching over real registry text, not a fabricated
        string -- the failure modes that matter are the ones sponsors produce."""
        import json
        from pathlib import Path

        from secondlook.tier1.criteria_extraction import RuleBasedExtractor

        fixtures = sorted(
            (Path(__file__).resolve().parents[1] / "trials" / "fixtures").glob("*.json")
        )
        if not fixtures:
            pytest.skip("no fixtures present")
        payload = json.loads(fixtures[0].read_text(encoding="utf-8"))
        predicates = (
            RuleBasedExtractor()
            .extract(payload["registry_id"], payload["criteria_text"])
            .predicates
        )
        result = match_trial(payload["registry_id"], predicates, CaseState(case_id="c"))
        # A case with no recorded data can never be a confident match.
        assert result.bucket in ("needs_verification", "probably_incompatible")
