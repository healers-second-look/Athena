"""ClinicalTrials.gov loader: parsing, refusals, and scope derivation."""

import pytest
import yaml

from secondlook.tier1.ctgov_loader import (
    CtgovApiError,
    LoadSummary,
    parse_study,
    run_load,
    scope_conditions,
)


def study(**overrides):
    """A well-formed v2 record, shaped from a real API response."""
    protocol = {
        "identificationModule": {"nctId": "NCT05407441", "briefTitle": "A trial"},
        "statusModule": {
            "overallStatus": "RECRUITING",
            "expandedAccessInfo": {"hasExpandedAccess": False},
            "lastUpdatePostDateStruct": {"date": "2026-04-13"},
        },
        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE1", "PHASE2"]},
        "conditionsModule": {"conditions": ["Chordoma"]},
        "eligibilityModule": {
            "eligibilityCriteria": "Inclusion Criteria:\n* Age 18 or older",
            "minimumAge": "18 Years",
            "maximumAge": "65 Years",
            "sex": "ALL",
        },
        "contactsLocationsModule": {
            "locations": [{"facility": "Site", "city": "Boston", "country": "United States"}]
        },
    }
    for module, patch in overrides.items():
        if patch is None:
            protocol.pop(module, None)
        else:
            protocol.setdefault(module, {}).update(patch)
    return {"protocolSection": protocol}


class TestParse:
    def test_parses_a_well_formed_record(self):
        summary = LoadSummary()
        parsed = parse_study(study(), summary)
        assert parsed["registry_id"] == "NCT05407441"
        assert parsed["status"] == "RECRUITING"
        assert parsed["phase"] == "PHASE1, PHASE2"
        assert parsed["country_codes"] == ["United States"]
        assert parsed["eligibility_url"] == "https://clinicaltrials.gov/study/NCT05407441"
        assert parsed["has_expanded_access"] is False
        assert summary.dropped == {}

    def test_expanded_access_flag_is_carried_through(self):
        """Cross-referenced by the Access Pathway Registry: a trial with an
        expanded-access programme IS an access route."""
        parsed = parse_study(
            study(statusModule={"expandedAccessInfo": {"hasExpandedAccess": True}}),
            LoadSummary(),
        )
        assert parsed["has_expanded_access"] is True

    def test_missing_nct_id_is_dropped_with_a_reason(self):
        summary = LoadSummary()
        assert parse_study(study(identificationModule={"nctId": None}), summary) is None
        assert summary.dropped == {"no nctId": 1}

    def test_missing_eligibility_criteria_is_dropped(self):
        """A trial with no criteria would bucket as compatible for everyone --
        the worst failure available to the matcher."""
        summary = LoadSummary()
        assert parse_study(study(eligibilityModule={"eligibilityCriteria": ""}), summary) is None
        assert summary.dropped == {"no eligibilityCriteria": 1}

    def test_unrecognised_status_is_refused_and_counted_not_guessed(self):
        """An unknown status means the registry changed its vocabulary. Mapping
        it to UNKNOWN would hide that; guessing would be worse."""
        summary = LoadSummary()
        assert parse_study(study(statusModule={"overallStatus": "TELEPORTED"}), summary) is None
        assert summary.unmapped_statuses == {"TELEPORTED": 1}
        assert summary.dropped == {"unmapped status TELEPORTED": 1}

    def test_absent_modules_do_not_raise(self):
        """Optional modules are genuinely absent on some records."""
        parsed = parse_study(study(contactsLocationsModule=None, designModule=None), LoadSummary())
        assert parsed["locations"] == []
        assert parsed["phase"] is None


class TestScope:
    def test_derived_from_civic_scope_so_the_two_cannot_drift(self, tmp_path):
        civic = tmp_path / "civic.yaml"
        civic.write_text(yaml.safe_dump({"diseases": [{"doid": "3369", "name": "Ewing Sarcoma"}]}))
        terms = scope_conditions({"synonyms": {}}, civic_scope_path=civic)
        assert terms == ["Ewing Sarcoma"]

    def test_synonyms_are_keyed_by_doid_not_name(self, tmp_path):
        """Keyed by DOID so an entry cannot silently attach to the wrong disease."""
        civic = tmp_path / "civic.yaml"
        civic.write_text(yaml.safe_dump({"diseases": [{"doid": "3369", "name": "Ewing Sarcoma"}]}))
        terms = scope_conditions(
            {"synonyms": {"3369": ["Ewing's Sarcoma"]}}, civic_scope_path=civic
        )
        assert terms == ["Ewing Sarcoma", "Ewing's Sarcoma"]

    def test_duplicates_are_removed_case_insensitively_and_order_is_stable(self, tmp_path):
        civic = tmp_path / "civic.yaml"
        civic.write_text(
            yaml.safe_dump(
                {"diseases": [{"doid": "1", "name": "Sarcoma"}, {"doid": "2", "name": "sarcoma"}]}
            )
        )
        assert scope_conditions({"synonyms": {}}, civic_scope_path=civic) == ["Sarcoma"]

    def test_missing_civic_scope_raises_rather_than_querying_nothing(self, tmp_path):
        with pytest.raises(CtgovApiError, match="civic scope not found"):
            scope_conditions({}, civic_scope_path=tmp_path / "absent.yaml")

    def test_shipped_scope_derives_a_non_empty_term_list(self):
        assert len(scope_conditions()) > 10


class TestRunLoad:
    def test_the_same_trial_matching_two_conditions_is_written_once(self, monkeypatch):
        import secondlook.tier1.ctgov_loader as loader

        # The same study comes back for both scope terms, as it does live.
        monkeypatch.setattr(loader, "fetch_studies", lambda c, **kw: [study()])
        monkeypatch.setattr(loader, "scope_conditions", lambda cfg: ["Chordoma", "Sarcoma"])
        summary = run_load(None, {"config_version": "t"}, dry_run=True)
        assert summary.trials_written == 1
        assert summary.dropped == {"duplicate across conditions": 1}
        assert summary.conditions_queried == 2
