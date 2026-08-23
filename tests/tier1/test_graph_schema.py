import pytest

from secondlook.tier1.graph_schema import (
    ACCESS_PATHWAY,
    DISEASE,
    DRUG,
    EVIDENCE_ITEM,
    EVIDENCE_LEVELS,
    GENE,
    PRECEDENT_STRENGTHS,
    PUBLICATION,
    RESPONSE_DIRECTIONS,
    RESULT_EVIDENCE_LEVELS,
    RETRIEVAL_MODES,
    STRUCTURAL_SIGNAL,
    TRIAL,
    TRIAL_STATUSES,
    VARIANT,
    VARIANT_TYPES,
    assert_valid,
    predicts_response_to_properties,
    with_enrichment_provenance,
    with_provenance,
)


class TestWithProvenance:
    def test_merges_all_three_fields(self):
        out = with_provenance(
            {"symbol": "TP53"},
            source="CIViC",
            retrieved_at="2026-08-21T12:00:00Z",
            source_version="v2026-08",
        )
        assert out == {
            "symbol": "TP53",
            "source": "CIViC",
            "source_version": "v2026-08",
            "retrieved_at": "2026-08-21T12:00:00Z",
        }

    def test_source_version_defaults_to_none(self):
        out = with_provenance(
            {"symbol": "TP53"}, source="CIViC", retrieved_at="2026-08-21T12:00:00Z"
        )
        assert out["source_version"] is None

    def test_does_not_mutate_input_dict(self):
        original = {"symbol": "TP53"}
        with_provenance(original, source="CIViC", retrieved_at="2026-08-21T12:00:00Z")
        assert original == {"symbol": "TP53"}


class TestWithEnrichmentProvenance:
    """Confirms the bug that motivated this helper cannot happen with it:
    a second writer must never overwrite the node-level source/retrieved_at
    another source already set (see chembl_enrich.py, which triggered this
    -- a Drug node civic_loader.py wrote as source="CIViC" read back as
    source="ChEMBL" after enrichment, via with_provenance()'s node-level
    SET += overwrite)."""

    def test_sets_per_property_fields_not_node_level_fields(self):
        out = with_enrichment_provenance(
            {"drug_class": "Kinase inhibitor"},
            source="ChEMBL",
            retrieved_at="2026-08-21T13:00:00Z",
            source_version="ChEMBL_37",
        )
        assert out == {
            "drug_class": "Kinase inhibitor",
            "drug_class_source": "ChEMBL",
            "drug_class_retrieved_at": "2026-08-21T13:00:00Z",
            "drug_class_source_version": "ChEMBL_37",
        }

    def test_never_emits_bare_source_or_retrieved_at_keys(self):
        """The exact keys that, if present, would let `SET n += $props`
        clobber a node's existing top-level provenance."""
        out = with_enrichment_provenance({"drug_class": "X"}, source="ChEMBL", retrieved_at="t")
        assert "source" not in out
        assert "retrieved_at" not in out
        assert "source_version" not in out

    def test_source_version_defaults_to_none(self):
        out = with_enrichment_provenance({"drug_class": "X"}, source="ChEMBL", retrieved_at="t")
        assert out["drug_class_source_version"] is None

    def test_does_not_mutate_input_dict(self):
        original = {"drug_class": "X"}
        with_enrichment_provenance(original, source="ChEMBL", retrieved_at="t")
        assert original == {"drug_class": "X"}

    def test_handles_multiple_properties_in_one_call(self):
        out = with_enrichment_provenance(
            {"drug_class": "X", "some_other_field": "Y"}, source="ChEMBL", retrieved_at="t"
        )
        assert out["drug_class_source"] == "ChEMBL"
        assert out["some_other_field_source"] == "ChEMBL"

    def test_merging_result_onto_an_existing_node_preserves_its_own_provenance(self):
        """Simulates the real scenario: a node already has source/
        retrieved_at from its creator; merging this helper's output must
        leave those two keys completely absent from what gets merged in."""
        existing_node = {"name": "Larotrectinib", "source": "CIViC", "retrieved_at": "T1"}
        enrichment = with_enrichment_provenance(
            {"drug_class": "Kinase inhibitor"}, source="ChEMBL", retrieved_at="T2"
        )
        merged = {**existing_node, **enrichment}  # what `SET n += $props` does
        assert merged["source"] == "CIViC", "original creator's provenance must survive"
        assert merged["retrieved_at"] == "T1"
        assert merged["drug_class_source"] == "ChEMBL"
        assert merged["drug_class_retrieved_at"] == "T2"


class TestPredictsResponseToProperties:
    def test_missing_direction_raises(self):
        with pytest.raises(TypeError):
            predicts_response_to_properties()  # type: ignore[call-arg]

    def test_invalid_direction_raises_value_error(self):
        with pytest.raises(ValueError, match="direction"):
            predicts_response_to_properties("unclear")

    def test_none_direction_raises_value_error(self):
        with pytest.raises(ValueError):
            predicts_response_to_properties(None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("direction", ["sensitive", "resistant"])
    def test_valid_direction_returns_property_dict(self, direction):
        assert predicts_response_to_properties(direction) == {"direction": direction}


class TestAssertValid:
    def test_raises_for_value_outside_allowed_set(self):
        with pytest.raises(ValueError, match="evidence_level"):
            assert_valid("Z", EVIDENCE_LEVELS, "evidence_level")

    def test_passes_silently_for_value_in_allowed_set(self):
        assert assert_valid("A", EVIDENCE_LEVELS, "evidence_level") is None

    def test_raises_for_variant_type_outside_allowed_set(self):
        with pytest.raises(ValueError):
            assert_valid("nonsense", VARIANT_TYPES, "variant_type")

    def test_passes_for_variant_type_in_allowed_set(self):
        assert assert_valid("missense", VARIANT_TYPES, "variant_type") is None

    def test_raises_for_retrieval_mode_outside_allowed_set(self):
        with pytest.raises(ValueError):
            assert_valid("fuzzy", RETRIEVAL_MODES, "retrieval_mode")


class TestNodeTypeProperties:
    """Pins each NodeType's property tuple to the spec so a typo'd or
    drifted property name is caught here rather than surfacing later as a
    loader silently writing the wrong shape."""

    def test_gene(self):
        assert GENE.label == "Gene"
        assert GENE.properties == ("symbol", "ensembl_id", "uniprot_accession", "hgnc_id")

    def test_variant(self):
        assert VARIANT.label == "Variant"
        assert VARIANT.properties == (
            "hgvs_p",
            "hgvs_c",
            "protein_position",
            "ref_aa",
            "alt_aa",
            "variant_type",
            "civic_variant_id",
        )

    def test_disease(self):
        assert DISEASE.label == "Disease"
        assert DISEASE.properties == ("name", "doid", "is_in_scope_cancer_type")

    def test_drug(self):
        assert DRUG.label == "Drug"
        assert DRUG.properties == (
            "name",
            "chembl_id",
            "approval_status",
            "smiles",
            "india_availability",
            "drug_class",
        )

    def test_evidence_item(self):
        assert EVIDENCE_ITEM.label == "EvidenceItem"
        assert EVIDENCE_ITEM.properties == (
            "civic_id",
            "evidence_level",
            "evidence_type",
            "clinical_significance",
            "direction",
            "summary",
            "citation_url",
            "summary_embedding",
        )

    def test_trial(self):
        assert TRIAL.label == "Trial"
        assert TRIAL.properties == (
            "registry_id",
            "registry",
            "status",
            "phase",
            "locations",
            "country_codes",
            "eligibility_url",
            # Added with the ClinicalTrials.gov loader (Subsystem F). The raw
            # criteria text is stored so extraction can be re-run against a
            # fixed corpus rather than a registry that edits its own records.
            "brief_title",
            "conditions",
            "eligibility_criteria",
            "minimum_age",
            "maximum_age",
            "sex",
            "study_type",
            "has_expanded_access",
            "last_update_posted",
        )

    def test_access_pathway(self):
        assert ACCESS_PATHWAY.label == "AccessPathway"
        assert ACCESS_PATHWAY.properties == (
            "pathway_id",
            "pathway_type",
            "country",
            "regulator",
            "instrument",
            "description",
            "source_url",
            "precedent_strength",
            "precedent_examples",
            "config_version",
        )

    def test_precedent_strength_has_exactly_two_states(self):
        """ "A pathway theoretically exists" and "a grant has happened before"
        are materially different claims and must never collapse together."""
        assert PRECEDENT_STRENGTHS == frozenset({"theoretical", "granted_before"})

    def test_trial_statuses_cover_the_registry_vocabulary(self):
        for expected in ("RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED", "WITHDRAWN"):
            assert expected in TRIAL_STATUSES

    def test_publication(self):
        assert PUBLICATION.label == "Publication"
        assert PUBLICATION.properties == (
            "pmid",
            "title",
            "journal",
            "year",
            "pub_type",
            "mesh_terms",
            "abstract",
            "abstract_embedding",
        )

    def test_structural_signal(self):
        assert STRUCTURAL_SIGNAL.label == "StructuralSignal"
        assert STRUCTURAL_SIGNAL.properties == (
            "alphamissense_score",
            "alphamissense_class",
            "structure_source",
            "structure_id",
            "plddt_at_residue",
            "reliability_flag",
            "method",
            "binding_site_distance_angstrom",
            "confidence",
            "calibration_status",
            "computed_at",
            "pipeline_version",
            "labeling_version",
        )

    def test_structural_signal_matches_what_tier2_actually_emits(self):
        """The literal tuple above is a snapshot; THIS is the real invariant.

        StructuralSignal is the one node type Tier 1 does not write -- Tier 2
        computes it and Tier 1 stores and queries it. So the property list here
        is a *reader-side* declaration of someone else's output, and the only
        thing that makes it correct is agreement with the writer.

        That agreement drifted once already: Tier 2 emitted six fields this
        schema never declared, including binding_site_distance_angstrom, which
        is the sole output of every case in Tier 2's current gold-standard run.
        Nothing failed, because NodeType is documentation rather than an ORM --
        a query built from the declared list would simply never have read the
        field. A snapshot test cannot catch that; only comparing against the
        writer can.

        Skipped rather than failed when Tier 2 is absent: this repo is
        installable without it (see README), and a missing optional peer is not
        a schema violation.
        """
        graph = pytest.importorskip(
            "secondlook.graph",
            reason="Tier 2 (secondlook.graph) not installed; cross-repo check not applicable",
        )
        import inspect
        import re

        emitted = set(
            re.findall(r'"(\w+)":', inspect.getsource(graph.StructuralSignal.node_properties))
        )
        declared = set(STRUCTURAL_SIGNAL.properties)

        assert not (emitted - declared), (
            "Tier 2 emits StructuralSignal properties this schema does not declare: "
            f"{sorted(emitted - declared)}. Add them to STRUCTURAL_SIGNAL.properties."
        )
        assert not (declared - emitted), (
            "This schema declares StructuralSignal properties Tier 2 never emits: "
            f"{sorted(declared - emitted)}. Remove them, or fix Tier 2's node_properties()."
        )

    def test_no_node_type_property_list_includes_provenance_fields(self):
        """Provenance is added separately by with_provenance() at write
        time -- it must never be baked into a NodeType's own property tuple,
        or with_provenance() would silently overwrite/duplicate it."""
        from secondlook.tier1.graph_schema import ALL_NODE_TYPES, PROVENANCE_PROPERTIES

        for node_type in ALL_NODE_TYPES:
            overlap = set(node_type.properties) & set(PROVENANCE_PROPERTIES)
            assert not overlap, f"{node_type.label} properties overlap provenance fields: {overlap}"


class TestAllowedValueSets:
    def test_evidence_levels(self):
        assert EVIDENCE_LEVELS == frozenset("ABCDE")

    def test_result_evidence_levels_adds_literature_without_touching_evidence_levels(self):
        """The constant that would let a future accidental merge of the two
        allowed sets go unnoticed -- see graph_schema.RESULT_EVIDENCE_LEVELS
        docstring for why they must stay separate."""
        assert "literature" in RESULT_EVIDENCE_LEVELS
        assert "literature" not in EVIDENCE_LEVELS
        assert RESULT_EVIDENCE_LEVELS == EVIDENCE_LEVELS | {"literature"}

    def test_variant_types(self):
        assert VARIANT_TYPES == frozenset({"missense", "indel", "fusion", "splice"})

    def test_retrieval_modes(self):
        assert RETRIEVAL_MODES == frozenset({"exact", "relaxed", "semantic"})

    def test_response_directions(self):
        assert RESPONSE_DIRECTIONS == frozenset({"sensitive", "resistant"})
