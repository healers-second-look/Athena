"""Access pathways: the claims this loader refuses to write.

Stricter than the other loaders on purpose. A malformed CIViC record produces a
missing evidence item; a malformed access pathway produces a confident,
citable-looking claim that a legal route exists when it does not.
"""

import pytest
import yaml

from secondlook.tier1.access_pathway_loader import (
    UNREVIEWED,
    AccessPathwayConfigError,
    pathway_id,
    read_seed_file,
    run_load,
    validate_pathway,
)


def entry(**overrides):
    base = {
        "pathway_type": "compassionate_use",
        "instrument": "CDSCO New Drugs and Clinical Trials Rules, 2019 — Rule 36",
        "description": "Compassionate use for life-threatening conditions.",
        "source_url": "https://cdsco.gov.in/opencms/opencms/en/Home/",
        "precedent_strength": "theoretical",
        "precedent_examples": [],
    }
    base.update(overrides)
    return base


def seed_file(tmp_path, name="india.yaml", **overrides):
    payload = {
        "config_version": "test.1",
        "country": "IN",
        "regulator": "CDSCO",
        "review_status": UNREVIEWED,
        "pathways": [entry()],
    }
    payload.update(overrides)
    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload, allow_unicode=True))
    return path


class TestRequiredCitations:
    @pytest.mark.parametrize("field", ["instrument", "source_url", "description", "pathway_type"])
    def test_a_pathway_without_its_citation_is_refused(self, field, tmp_path):
        """A route with no citation is not usable by the person who has to file
        the application."""
        with pytest.raises(AccessPathwayConfigError, match=field):
            validate_pathway(entry(**{field: ""}), country="IN", path=tmp_path / "x.yaml")

    def test_unknown_pathway_type_is_refused(self):
        with pytest.raises(ValueError, match="pathway_type"):
            validate_pathway(entry(pathway_type="vibes"), country="IN", path=None)


class TestPrecedentStrength:
    def test_granted_before_without_a_precedent_is_refused(self):
        """The distinction the issue calls out: 'has been granted before' is a
        materially different claim from 'a pathway theoretically exists', and
        must not be assertable without evidence."""
        with pytest.raises(AccessPathwayConfigError, match="precedent_examples"):
            validate_pathway(entry(precedent_strength="granted_before"), country="IN", path=None)

    def test_granted_before_with_a_precedent_is_accepted(self):
        parsed = validate_pathway(
            entry(precedent_strength="granted_before", precedent_examples=["Case X, 2024"]),
            country="IN",
            path=None,
        )
        assert parsed["precedent_strength"] == "granted_before"
        assert parsed["precedent_examples"] == ["Case X, 2024"]

    def test_theoretical_is_the_default(self):
        parsed = validate_pathway(
            {k: v for k, v in entry().items() if k != "precedent_strength"},
            country="IN",
            path=None,
        )
        assert parsed["precedent_strength"] == "theoretical"

    def test_unknown_strength_is_refused(self):
        with pytest.raises(ValueError, match="precedent_strength"):
            validate_pathway(entry(precedent_strength="probably"), country="IN", path=None)


class TestSeedFiles:
    def test_reads_a_well_formed_file(self, tmp_path):
        header, pathways = read_seed_file(seed_file(tmp_path))
        assert header["country"] == "IN"
        assert header["review_status"] == UNREVIEWED
        assert len(pathways) == 1

    def test_file_without_country_or_regulator_is_refused(self, tmp_path):
        path = seed_file(tmp_path)
        path.write_text(yaml.safe_dump({"pathways": [entry()]}))
        with pytest.raises(AccessPathwayConfigError, match="country"):
            read_seed_file(path)

    def test_review_status_defaults_to_unreviewed_when_absent(self, tmp_path):
        path = tmp_path / "x.yaml"
        path.write_text(
            yaml.safe_dump({"country": "IN", "regulator": "CDSCO", "pathways": [entry()]})
        )
        header, _ = read_seed_file(path)
        assert header["review_status"] == UNREVIEWED

    def test_a_malformed_file_is_rejected_whole_not_partially_loaded(self, tmp_path):
        """A half-loaded country is worse than an absent one."""
        # Written for its side effect: a valid file alongside the malformed one.
        seed_file(tmp_path, "us.yaml", country="US", regulator="FDA")
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            yaml.safe_dump(
                {"country": "XX", "regulator": "R", "pathways": [entry(), entry(source_url="")]}
            )
        )
        summary = run_load(None, pathways_dir=tmp_path, dry_run=True)
        assert summary.files_read == 1
        assert summary.pathways_written == 1
        assert len(summary.rejected) == 1


class TestIdentity:
    def test_id_includes_the_instrument(self):
        """One country can offer the same pathway_type under two different legal
        instruments; collapsing them would silently drop one."""
        a = pathway_id("IN", "compassionate_use", "Rule 36")
        b = pathway_id("IN", "compassionate_use", "Rule 37")
        assert a != b


class TestShippedSeeds:
    def test_they_validate(self):
        summary = run_load(None, dry_run=True)
        assert summary.rejected == []
        assert summary.pathways_written >= 4

    def test_every_shipped_entry_is_flagged_unreviewed(self):
        """These were transcribed from the issue, not verified against the
        primary source by anyone with regulatory-affairs training."""
        summary = run_load(None, dry_run=True)
        assert summary.unreviewed == summary.pathways_written

    def test_no_shipped_entry_claims_a_precedent(self):
        """An invented precedent is the most damaging thing that could be added
        to these files."""
        from secondlook.tier1.access_pathway_loader import PATHWAYS_DIR

        for path in PATHWAYS_DIR.glob("*.yaml"):
            _, pathways = read_seed_file(path)
            for pathway in pathways:
                assert pathway["precedent_strength"] == "theoretical"
                assert pathway["precedent_examples"] == []
