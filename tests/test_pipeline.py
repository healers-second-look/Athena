"""Step 7 pipeline orchestration and output assembly."""

import pytest

from secondlook.binding import BINDING_UNAVAILABLE_MESSAGE, BindingScore
from secondlook.candidates import ZERO_CANDIDATES_MESSAGE
from secondlook.graph import PIPELINE_VERSION
from secondlook.mutation_validation import OUT_OF_SCOPE_MESSAGE, ProteinSequence
from secondlook.pipeline import DISCLAIMER, run_tier2
from secondlook.tier1_contract import ActivationDecision, AlwaysRunTier2Policy, CollectingGraphSink

# TP53 R175H is the smoke-test case: values verified at each individual step in
# earlier reviews. Sequence below is padded so position 175 holds R.
_TP53_SEQ = "M" + "A" * 173 + "R" + "A" * 219
_TP53_PDB = (
    "ATOM      1  CA  ARG A 175      11.000  12.000  13.000  1.00 88.00           C  \n"
    "HETATM    2  C1  LIG A 500       9.000  10.000  11.000  1.00 20.00           C  \n"
    "END\n"
)


class FakeSequences:
    def fetch(self, identifier):
        return ProteinSequence(
            accession="P04637", sequence=_TP53_SEQ, gene="TP53", isoform_note="canonical"
        )


class FakeTranscripts:
    def resolve_mane_select(self, gene_symbol):
        return "ENST00000269305.9"

    def fetch_cds(self, transcript_id):
        # Codon 175 = CGT (Arg); pad the rest with GCT (Ala) to match _TP53_SEQ.
        return "ATG" + "GCT" * 173 + "CGT" + "GCT" * 219


class FakeVep:
    def lookup_hgvs(self, transcript_id, hgvs):
        return [
            {
                "transcript_consequences": [
                    {
                        "transcript_id": "ENST00000269305.9",
                        "alphamissense": {
                            "am_pathogenicity": 0.9999,
                            "am_class": "likely_pathogenic",
                        },
                    }
                ]
            }
        ]


class FakePdb:
    def __init__(self, hit=True):
        self.hit = hit

    def search_by_uniprot(self, accession, preferred_ligands=(), covering_residue=None):
        if not self.hit:
            return None
        return {"pdb_id": "1TUP", "ligand_bound": True, "pdb_text": _TP53_PDB}


_TP53_APO_PDB = (
    "ATOM      1  CA  ARG A 175      11.000  12.000  13.000  1.00 88.00           C  \n" "END\n"
)


class FakePdbApo:
    """Ligand-free structure: a delta is impossible and proximity unmeasurable."""

    def search_by_uniprot(self, accession, preferred_ligands=(), covering_residue=None):
        return {"pdb_id": "1APO", "ligand_bound": False, "pdb_text": _TP53_APO_PDB}


class FakeAlphaFold:
    def fetch_models(self, accession):
        return []


class FakeEsm:
    def fold_sequence(self, sequence):
        raise AssertionError("ESM must never be called on the default path")


class FakeDrugs:
    def __init__(self, rows):
        self.rows = rows

    def fetch_drugs(self, gene_symbol):
        return self.rows


class FakeEmpty:
    def fetch_drugs(self, gene_symbol):
        return []


class FakeSmiles:
    def fetch_smiles(self, drug_name):
        return "CCO"


class FakeMcsm:
    """Returns a fixed mCSM-lig-shaped result for every candidate."""

    def __init__(self, affinity_change=-2.056):
        self.affinity_change = affinity_change
        self.calls = []

    def submit(self, *, pdb_code, pdb_text, mutation, chain, lig_id):
        from secondlook.binding import McsmLigResult

        self.calls.append(mutation)
        return McsmLigResult(
            affinity_change=self.affinity_change,
            affinity_class="Destabilizing",
            wild_type="R",
            position=175,
            mutant_type="H",
            chain=chain,
            ligand_id=lig_id,
            distance_angstrom=4.2,
            duet_stability_kcal=-1.1,
        )


class FailingMcsm:
    def submit(self, *, pdb_code, pdb_text, mutation, chain, lig_id):
        from secondlook.binding import McsmNoHetCodeError

        raise McsmNoHetCodeError("no HET code")


class FakeVina:
    def __init__(self, delta=1.8):
        self.delta = delta

    def score(self, *, pdb_text, smiles, mutation, position):
        return BindingScore(
            status="scored",
            method="docking",
            delta_score=self.delta,
            affinity_class=None,
            distance_angstrom=None,
            ligand_id=None,
            chain=None,
        )


class FailingVina:
    def score(self, *, pdb_text, smiles, mutation, position):
        from secondlook.vina_dock import VinaError

        raise VinaError("docking failed")


class FakeHet:
    def __init__(self, code="LIG"):
        self.code = code

    def resolve(self, drug_name, structure):
        return self.code


def _run(**overrides):
    kwargs = dict(
        gene="TP53",
        mutation="R175H",
        sequence_provider=FakeSequences(),
        transcript_resolver=FakeTranscripts(),
        vep_client=FakeVep(),
        pdb_client=FakePdb(),
        alphafold_client=FakeAlphaFold(),
        esm_client=FakeEsm(),
        dgidb_client=FakeDrugs([{"name": "Oxaliplatin", "approved": True, "score": 1.0}]),
        opentargets_client=FakeEmpty(),
        chembl_client=FakeEmpty(),
        pubchem_client=FakeSmiles(),
        mcsm_client=FakeMcsm(),
        vina_client=FakeVina(),
        het_resolver=FakeHet(),
        min_delay_seconds=0.0,
        sleeper=lambda _s: None,
    )
    gene = overrides.pop("gene", kwargs["gene"])
    mutation = overrides.pop("mutation", kwargs["mutation"])
    kwargs.update(overrides)
    kwargs.pop("gene", None)
    kwargs.pop("mutation", None)
    return run_tier2(gene, mutation, **kwargs)


# --- Happy path ---------------------------------------------------------------


def test_end_to_end_produces_a_scored_result_item():
    out = _run()
    assert out.status == "complete"
    assert len(out.results) == 1
    item = out.results[0]
    assert item.type == "computational_signal"
    assert item.drug == "Oxaliplatin"
    assert item.method == "mCSM-lig"
    assert item.delta_score == -2.056
    assert item.label == "likely_reduced_binding"


def test_result_item_matches_the_api_contract_field_for_field():
    """api-contracts.md 'Tier 2 result item' — every documented field present."""
    item = _run().results[0].to_dict()
    required = {
        "type",
        "mutation_validated",
        "alphamissense",
        "structure",
        "drug",
        "smiles_source",
        "method",
        "delta_score",
        "label",
        "binding_site_distance_angstrom",
        "disclaimer",
    }
    assert required <= set(item)
    assert set(item["alphamissense"]) == {"score", "class"}
    assert set(item["structure"]) == {"source", "id", "plddt_at_residue", "reliability_flag"}


def test_disclaimer_is_the_shared_constant_not_a_retyped_copy():
    item = _run().results[0]
    assert item.disclaimer == DISCLAIMER
    assert item.disclaimer is DISCLAIMER


def test_disclaimer_matches_the_spec_text_verbatim():
    """Guards against drift from tier2-structural-prediction.md §10."""
    assert DISCLAIMER.startswith("This is a computational plausibility signal")
    assert DISCLAIMER.endswith("Do not use this output to start, stop, or change any treatment.")
    assert "not clinical evidence" in DISCLAIMER


def test_every_result_item_carries_a_disclaimer():
    out = _run(
        dgidb_client=FakeDrugs(
            [
                {"name": "DrugA", "approved": True, "score": 1.0},
                {"name": "DrugB", "approved": True, "score": 0.9},
            ]
        )
    )
    assert len(out.results) == 2
    assert all(r.disclaimer == DISCLAIMER for r in out.results)


# --- §8 failure paths ---------------------------------------------------------


def test_out_of_scope_mutation_returns_the_exact_message():
    out = _run(mutation="V600delins")
    assert out.status == "failed"
    assert out.results == []
    assert len(out.failures) == 1
    assert out.failures[0].reason == OUT_OF_SCOPE_MESSAGE
    assert out.failures[0].retryable is False


def test_reference_mismatch_returns_the_exact_message_and_stops():
    out = _run(mutation="A175H")  # position 175 is R, not A
    assert out.status == "failed"
    assert "Reference residue mismatch" in out.failures[0].reason
    assert out.failures[0].retryable is False
    assert out.results == []


def test_structure_unavailable_still_reports_alphamissense():
    """§8 promises AlphaMissense as 'the only available computational signal'."""
    out = _run(pdb_client=FakePdb(hit=False))
    assert out.status == "partial"
    assert "Structural analysis unavailable" in out.failures[0].reason
    assert out.failures[0].retryable is True
    assert out.alphamissense is not None
    assert out.alphamissense.am_pathogenicity == pytest.approx(0.9999)


def test_zero_candidates_returns_the_exact_message():
    out = _run(dgidb_client=FakeEmpty())
    assert out.status == "partial"
    assert out.failures[0].reason == ZERO_CANDIDATES_MESSAGE
    assert out.failures[0].retryable is False


def test_binding_failure_uses_the_binding_message_not_the_plddt_one():
    """Regression guard for the bug fixed in binding.py review.

    An unscoreable candidate on a perfectly good structure must not claim the
    structure was unreliable.
    """
    out = _run(pdb_client=FakePdbApo(), mcsm_client=FailingMcsm(), vina_client=FailingVina())
    assert out.results == []
    assert len(out.failures) == 1
    assert out.failures[0].reason == BINDING_UNAVAILABLE_MESSAGE
    # The structure itself was fine; only binding scoring came up empty.
    assert "pLDDT" not in out.failures[0].reason


def test_failure_object_matches_the_api_contract():
    payload = _run(mutation="V600delins").failures[0].to_dict()
    assert payload == {
        "type": "failure",
        "tier": "2",
        "reason": OUT_OF_SCOPE_MESSAGE,
        "retryable": False,
    }


def test_every_outcome_produces_a_result_or_a_failure_never_silence():
    """The §8 rule: a doctor must never face an unexplained empty screen.

    Since the proximity fallback landed, an unscoreable candidate yields a
    `proximity_only` *result* rather than a failure — so the invariant is
    "something is always rendered", not "a failure is always rendered".
    """
    for kwargs in (
        {"mutation": "V600delins"},
        {"mutation": "A175H"},
        {"pdb_client": FakePdb(hit=False)},
        {"dgidb_client": FakeEmpty()},
        {"mcsm_client": FailingMcsm(), "vina_client": FailingVina()},
    ):
        out = _run(**kwargs)
        assert out.results or out.failures, f"silent outcome for {kwargs}"


# --- Partial results ----------------------------------------------------------


def test_one_unscoreable_candidate_does_not_drop_the_others():
    class OneBadHet:
        def resolve(self, drug_name, structure):
            return None if drug_name == "DrugB" else "LIG"

    out = _run(
        dgidb_client=FakeDrugs(
            [
                {"name": "DrugA", "approved": True, "score": 1.0},
                {"name": "DrugB", "approved": True, "score": 0.9},
            ]
        ),
        het_resolver=OneBadHet(),
        vina_client=FailingVina(),
    )
    # Both drugs are reported: one with a binding delta, one proximity-only.
    assert sorted(r.drug for r in out.results) == ["DrugA", "DrugB"]
    kinds = {r.drug: r.signal_type for r in out.results}
    assert kinds["DrugA"] == "binding_delta"
    assert kinds["DrugB"] == "proximity_only"
    assert out.failures == []


def test_vina_fallback_is_used_when_mcsm_cannot_run():
    out = _run(mcsm_client=FailingMcsm(), vina_client=FakeVina(delta=1.8))
    assert len(out.results) == 1
    item = out.results[0]
    assert item.method == "docking"
    assert item.delta_score == 1.8
    # Positive docking delta means the mutant binds worse.
    assert item.label == "likely_reduced_binding"


def test_method_split_is_reported_for_the_coverage_gap_note():
    """tier2-implementation-spec.md §5 deliverable 5 needs this ratio."""
    out = _run()
    assert out.scored_by_method == {"mCSM-lig": 1}
    out2 = _run(mcsm_client=FailingMcsm(), vina_client=FakeVina())
    assert out2.scored_by_method == {"docking": 1}


# --- Graph emission (§4) ------------------------------------------------------


def test_emits_one_structural_signal_per_scored_candidate():
    out = _run()
    assert len(out.signals) == 1
    signal = out.signals[0]
    assert signal.gene == "TP53"
    assert signal.drug == "Oxaliplatin"
    assert signal.method == "mCSM-lig"
    assert signal.label == "likely_reduced_binding"


def test_signal_carries_mandatory_provenance():
    """§4: without computed_at/pipeline_version a stale cached signal is undetectable."""
    signal = _run().signals[0]
    assert signal.computed_at
    assert signal.pipeline_version == PIPELINE_VERSION
    assert signal.labeling_version
    assert signal.computed_at.endswith("+00:00")


def test_signal_is_not_shaped_like_documented_evidence():
    """§4: a StructuralSignal must never be mistakable for an EvidenceItem."""
    signal = _run().signals[0]
    props = signal.node_properties()
    assert "citation_url" not in props
    assert "evidence_level" not in props
    assert props["method"] in {"mCSM-lig", "docking"}


def test_graph_sink_receives_the_signals():
    sink = CollectingGraphSink()
    out = _run(graph_sink=sink)
    assert sink.signals == out.signals


def test_proximity_only_candidate_still_emits_a_graph_signal():
    """A signal with measured proximity and no delta is valid graph content.

    tier2-implementation-spec.md §6 explicitly anticipates candidates with an
    evidence trail and no computable binding delta.
    """
    sink = CollectingGraphSink()
    _run(mcsm_client=FailingMcsm(), vina_client=FailingVina(), graph_sink=sink)
    assert len(sink.signals) == 1
    assert sink.signals[0].delta_score is None
    assert sink.signals[0].label is None
    assert sink.signals[0].binding_site_distance_angstrom is not None


def test_no_signal_emitted_when_nothing_could_be_measured():
    """An apo structure yields neither a delta nor proximity — a real failure."""
    sink = CollectingGraphSink()
    out = _run(
        pdb_client=FakePdbApo(),
        mcsm_client=FailingMcsm(),
        vina_client=FailingVina(),
        graph_sink=sink,
    )
    assert sink.signals == []
    assert out.results == []
    assert out.failures


# --- Tier 1 activation seam ---------------------------------------------------


def test_placeholder_policy_runs_tier2_and_claims_no_evidence():
    out = _run(activation_policy=AlwaysRunTier2Policy())
    assert out.activation is not None
    assert out.activation.is_placeholder is True
    assert out.activation.state == "no_hit"
    assert out.activation.tier1_results == []
    assert out.status == "complete"


def test_strong_tier1_hit_skips_tier2_without_running_anything():
    class StrongHit:
        def decide(self, *, gene, mutation, cancer_type):
            return ActivationDecision(
                state="strong_hit", should_run_tier2=False, reason="CIViC level A"
            )

    class ExplodingSequences:
        def fetch(self, identifier):
            raise AssertionError("Tier 2 must not run on a strong Tier 1 hit")

    out = _run(activation_policy=StrongHit(), sequence_provider=ExplodingSequences())
    assert out.status == "not_run"
    assert out.results == []
    assert out.activation.state == "strong_hit"


def test_no_activation_policy_means_tier2_runs():
    """Tier 2 does not implement §6 activation; absent a policy it simply runs."""
    out = _run()
    assert out.activation is None
    assert out.status == "complete"


# --- Honesty metadata ---------------------------------------------------------


def test_docking_results_carry_lower_confidence_than_mcsm_results():
    mcsm_item = _run().results[0]
    docking_item = _run(mcsm_client=FailingMcsm(), vina_client=FakeVina()).results[0]
    assert mcsm_item.confidence != docking_item.confidence
    assert docking_item.confidence == "low"


def test_results_disclose_provisional_calibration():
    item = _run().results[0]
    assert item.calibration_status == "provisional"
    assert "not a validated clinical threshold" in item.heuristic_note


def test_delta_score_unit_is_recorded_so_methods_are_not_compared_naively():
    mcsm_item = _run().results[0]
    docking_item = _run(mcsm_client=FailingMcsm(), vina_client=FakeVina()).results[0]
    assert mcsm_item.delta_score_unit != docking_item.delta_score_unit


def test_label_derives_only_from_the_threshold_constant():
    """api-contracts.md: never a hardcoded per-case decision.

    Swapping the calibration must change the label for the identical input.
    """
    from secondlook.labeling import MethodCalibration

    strict = {
        "mCSM-lig": MethodCalibration(
            method="mCSM-lig",
            unit="log(affinity fold change)",
            orientation=1,
            reduced_at_or_below=-99.0,
            increased_at_or_above=99.0,
            confidence="moderate",
            accuracy_note="swept",
        )
    }
    assert _run().results[0].label == "likely_reduced_binding"
    assert _run(calibrations=strict).results[0].label == "uncertain"


# --- Live end-to-end smoke test ----------------------------------------------


@pytest.mark.integration
def test_live_end_to_end_tp53_r175h():
    """Full pipeline against real services on TP53 R175H.

    Values at each individual step were verified in earlier reviews; this checks
    that composing them produces a contract-shaped result. Capped at one
    candidate to keep a real docking run bounded.
    """
    out = run_tier2("TP53", "R175H", max_candidates=1, min_delay_seconds=1.0)

    # The run must never crash and must never be silent about an outcome.
    assert out.status in {"complete", "partial"}
    assert out.results or out.failures

    assert out.validation is not None
    assert out.validation.status == "valid"
    assert out.validation.uniprot_accession == "P04637"
    assert out.validation.position == 175
    assert out.validation.reference_residue_expected == "R"

    # AlphaMissense is reported regardless of what happens downstream.
    assert out.alphamissense is not None

    assert out.computed_at
    assert out.pipeline_version == PIPELINE_VERSION

    # Two result shapes are contract-valid, and each must be internally
    # complete. This test originally asserted every item carries a label,
    # method and delta — true before the proximity fallback existed, and
    # wrong after it: a `proximity_only` item deliberately has none of the
    # three. Asserting the discriminator agrees with the fields is the
    # stronger check anyway, because it catches a half-populated item that
    # the old assertion would have passed.
    for item in out.results:
        assert item.disclaimer == DISCLAIMER
        assert item.signal_type in {"binding_delta", "proximity_only"}

        if item.signal_type == "binding_delta":
            assert item.label in {
                "likely_reduced_binding",
                "likely_retained_or_increased_binding",
                "uncertain",
            }
            assert item.method in {"mCSM-lig", "docking"}
            assert isinstance(item.delta_score, float)
        else:
            # No delta means no label, no method and no score — a
            # proximity_only item carrying any of them would be presenting a
            # binding prediction the pipeline explicitly declined to make.
            assert item.label is None
            assert item.method is None
            assert item.delta_score is None
            # ...and it must still say something measured, or it is an empty
            # result masquerading as an answer.
            assert item.proximity

    for signal in out.signals:
        assert signal.computed_at
        assert signal.pipeline_version == PIPELINE_VERSION


# --- The result item carries the contract shape, and nothing bulkier ----------
# MutationValidationResult also holds wildtype_sequence/mutant_sequence as
# internal working state. Those are not in api-contracts.md's validator schema,
# and embedding them in every result item ships two full protein sequences per
# candidate to the UI, which has no use for them.


def test_mutation_validated_matches_the_contract_fields_exactly():
    item = _run().results[0].to_dict()
    assert set(item["mutation_validated"]) == {
        "status",
        "gene",
        "hgvs_normalized",
        "uniprot_accession",
        "isoform_note",
        "position",
        "reference_residue_expected",
        "reference_residue_actual",
        "mutation_type",
        "error_message",
    }


def test_result_items_do_not_carry_protein_sequences():
    item = _run().results[0].to_dict()
    assert "wildtype_sequence" not in item["mutation_validated"]
    assert "mutant_sequence" not in item["mutation_validated"]


def test_sequences_appear_nowhere_in_the_serialized_payload():
    """One candidate leaks two sequences; twenty candidates leak forty."""
    import json

    from secondlook.cache import to_payload

    out = _run(
        dgidb_client=FakeDrugs(
            [
                {"name": "DrugA", "approved": True, "score": 1.0},
                {"name": "DrugB", "approved": True, "score": 0.9},
            ]
        )
    )
    blob = json.dumps(to_payload(out, gene="TP53", mutation="R175H"))
    assert len(out.results) == 2
    assert "wildtype_sequence" not in blob
    assert "mutant_sequence" not in blob
    # The padded fake sequence itself must not appear either.
    assert "A" * 60 not in blob


def test_mutation_validated_still_carries_the_useful_provenance():
    """Trimming must not drop what the UI actually needs to show."""
    validated = _run().results[0].to_dict()["mutation_validated"]
    assert validated["uniprot_accession"] == "P04637"
    assert validated["isoform_note"] == "canonical"
    assert validated["hgvs_normalized"] == "p.Arg175His"
    assert validated["position"] == 175
    assert validated["status"] == "valid"


# --- Network failures become structured results, not exceptions ---------------
# The four Steps 1-3 clients wrapped only raise_for_status() in their try block,
# while the httpx call itself sat outside it. So HTTP status errors were caught
# but connection resets and timeouts escaped as raw httpx exceptions — and
# UniProt has no fallback source, so one escaped all the way out of run_tier2.
# Reachable in normal operation: RCSB resets connections under sustained load.


def test_uniprot_connection_failure_returns_a_structured_failure():
    from secondlook.pipeline import PIPELINE_ERROR_MESSAGE
    from secondlook.uniprot import UniProtLookupError

    class DeadUniProt:
        def fetch(self, identifier):
            raise UniProtLookupError("UniProt request failed (simulated reset)")

    out = _run(sequence_provider=DeadUniProt())
    assert out.status == "failed"
    assert out.results == []
    assert len(out.failures) == 1
    assert out.failures[0].reason == PIPELINE_ERROR_MESSAGE
    assert out.failures[0].retryable is True


def test_run_tier2_never_raises_a_raw_network_error():
    """The pipeline's contract: every outcome is a returned object."""
    import httpx

    from secondlook.uniprot import UniProtLookupError

    class ResettingUniProt:
        def fetch(self, identifier):
            raise UniProtLookupError("reset") from httpx.ConnectError("reset by peer")

    out = _run(sequence_provider=ResettingUniProt())
    assert out.status == "failed"
    assert out.failures


@pytest.mark.parametrize(
    "module_name,error_name",
    [
        ("uniprot", "UniProtLookupError"),
        ("ensembl", "EnsemblError"),
        ("rcsb", "RcsbError"),
        ("alphafold", "AlphaFoldError"),
    ],
)
def test_transport_errors_are_wrapped_in_the_module_error_type(module_name, error_name):
    """A connection-level failure must surface as the module's own exception.

    Guards the specific shape of the bug: the httpx call must be inside the try,
    not merely the status check.
    """
    import importlib

    import httpx

    module = importlib.import_module(f"secondlook.{module_name}")
    expected = getattr(module, error_name)

    class ResettingTransport(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ConnectError("reset by peer", request=request)

    client = httpx.Client(transport=ResettingTransport())
    with pytest.raises(expected):
        if module_name == "uniprot":
            module.UniProtSequenceProvider(client=client).fetch("TP53")
        elif module_name == "ensembl":
            module.EnsemblTranscriptResolver(client=client).resolve_mane_select("TP53")
        elif module_name == "rcsb":
            module.RcsbPdbClient(client=client).search_by_uniprot("P04637")
        else:
            module.AlphaFoldDbClient(client=client).fetch_models("P04637")


# --- restrict_to_drugs (used by the gold-standard harness) --------------------


def _two_drugs():
    return FakeDrugs(
        [
            {"name": "Vemurafenib", "approved": True, "score": 1.0},
            {"name": "Dabrafenib", "approved": True, "score": 0.9},
        ]
    )


def test_restrict_to_drugs_scores_only_the_named_drug():
    out = _run(dgidb_client=_two_drugs(), restrict_to_drugs=("vemurafenib",))
    assert [r.drug for r in out.results] == ["Vemurafenib"]


def test_restrict_to_drugs_is_case_insensitive():
    out = _run(dgidb_client=_two_drugs(), restrict_to_drugs=("VEMURAFENIB",))
    assert [r.drug for r in out.results] == ["Vemurafenib"]


def test_restrict_to_drugs_can_keep_several():
    out = _run(dgidb_client=_two_drugs(), restrict_to_drugs=("vemurafenib", "dabrafenib"))
    assert sorted(r.drug for r in out.results) == ["Dabrafenib", "Vemurafenib"]


def test_restrict_to_drugs_narrows_rather_than_bypasses_candidate_generation():
    """A drug Step 4 never produced cannot be conjured by asking for it."""
    out = _run(dgidb_client=_two_drugs(), restrict_to_drugs=("imatinib",))
    assert out.results == []
    assert out.failures[0].reason == ZERO_CANDIDATES_MESSAGE


def test_no_restriction_scores_the_whole_shortlist():
    out = _run(dgidb_client=_two_drugs())
    assert len(out.results) == 2


# --- retryable must reflect whether a retry could change anything -------------


def test_out_of_pocket_failure_is_not_retryable():
    """The mutation will be the same distance from the pocket on every retry."""
    from secondlook.binding import BindingScore

    class OutsidePocketVina:
        def score(self, *, pdb_text, smiles, mutation, position):
            return BindingScore(
                status="unavailable",
                method=None,
                delta_score=None,
                affinity_class=None,
                distance_angstrom=16.6,
                ligand_id=None,
                chain=None,
                error_message="This mutation lies 16.6 A from the drug-binding site…",
                reason_code="outside_pocket",
            )

    out = _run(pdb_client=FakePdbApo(), mcsm_client=FailingMcsm(), vina_client=OutsidePocketVina())
    assert out.results == []
    assert len(out.failures) == 1
    assert out.failures[0].retryable is False


def test_transient_binding_failure_stays_retryable():
    out = _run(pdb_client=FakePdbApo(), mcsm_client=FailingMcsm(), vina_client=FailingVina())
    assert out.failures[0].retryable is True
