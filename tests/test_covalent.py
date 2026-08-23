"""Covalent mechanism gate."""

import pytest

from secondlook.covalent import (
    COVALENT_DRUGS,
    classify_covalent,
    detect_warhead,
)

IMATINIB = "CC1=C(C=C(C=C1)NC(=O)C2=CC=C(C=C2)CN3CCN(CC3)C)NC4=NC=CC(=N4)C5=CN=CC=C5"
VEMURAFENIB = "CCCS(=O)(=O)NC1=C(C(=C(C=C1)F)C(=O)C2=CNC3=C2C=C(C=N3)C4=CC=C(C=C4)Cl)F"


@pytest.mark.parametrize("name", ["OSIMERTINIB", "osimertinib", "Afatinib", "IBRUTINIB"])
def test_curated_covalent_drugs_are_gated(name):
    verdict = classify_covalent(name)
    assert verdict.is_covalent is True
    assert verdict.evidence == "curated"


@pytest.mark.parametrize("name,smiles", [("imatinib", IMATINIB), ("vemurafenib", VEMURAFENIB)])
def test_reversible_inhibitors_are_not_gated(name, smiles):
    assert classify_covalent(name, smiles).is_covalent is False


def test_unlisted_covalent_drug_is_caught_by_its_warhead():
    """The list will never be complete, and a miss fails in the dangerous direction."""
    verdict = classify_covalent("experimental-compound-7", "C=CC(=O)Nc1ccccc1")
    assert verdict.is_covalent is True
    assert verdict.evidence == "warhead:acrylamide"


def test_nitrile_alone_does_not_gate():
    """A nitrile is a common non-reactive substituent; gating on it would be noise."""
    assert detect_warhead("N#Cc1ccccc1") is None
    assert classify_covalent("benzonitrile-like", "N#Cc1ccccc1").is_covalent is False


def test_osimertinib_message_names_the_residue_and_the_reason():
    verdict = classify_covalent("osimertinib")
    text = verdict.message("osimertinib")
    assert "Cys797" in text
    assert "non-covalent" in text
    assert "retained binding when binding is in fact abolished" in text


def test_message_never_implies_a_score_was_computed():
    text = classify_covalent("osimertinib").message("osimertinib")
    assert "No binding-affinity estimate is reported" in text


def test_curated_list_carries_target_residues():
    assert COVALENT_DRUGS["OSIMERTINIB"] == "EGFR Cys797"
    assert all(isinstance(v, str) for v in COVALENT_DRUGS.values())


def test_scoring_gates_before_touching_the_structure():
    """No structure makes a non-covalent score valid, so the gate runs first."""
    from secondlook.binding import score_binding
    from secondlook.candidates import DrugCandidate
    from secondlook.mutation_validation import MutationValidationResult
    from secondlook.structure import StructureResult

    class ExplodingMcsm:
        def submit(self, **kw):
            raise AssertionError("must not reach mCSM-lig for a covalent drug")

    class ExplodingVina:
        def score(self, **kw):
            raise AssertionError("must not reach docking for a covalent drug")

    validation = MutationValidationResult(
        status="valid",
        gene="EGFR",
        hgvs_normalized="p.Cys797Ser",
        uniprot_accession="P00533",
        isoform_note=None,
        position=797,
        reference_residue_expected="C",
        reference_residue_actual="C",
        mutation_type="missense",
        error_message=None,
        wildtype_sequence="C" * 800,
        mutant_sequence="C" * 796 + "S" + "C" * 203,
    )
    structure = StructureResult(
        status="found",
        source="PDB",
        id="8A27",
        plddt_at_residue=None,
        plddt_global=None,
        reliability_flag="high",
        ligand_bound=True,
        annotated_position=797,
        pdb_text="ATOM      1  CA  CYS A 797       0.0   0.0   0.0\n",
    )
    candidate = DrugCandidate(
        name="OSIMERTINIB",
        source="DGIdb",
        target_tier="exact_protein",
        approved=True,
        smiles="CCO",
        smiles_source="PubChem",
    )
    result = score_binding(
        validation,
        structure,
        candidate,
        mcsm_client=ExplodingMcsm(),
        vina_client=ExplodingVina(),
        het_resolver=None,
        min_delay_seconds=0.0,
        sleeper=lambda _s: None,
    )
    assert result.status == "unavailable"
    assert result.reason_code == "mechanism_invalidated"
    assert "covalent" in result.error_message


def test_mechanism_invalidated_is_not_retryable():
    """Retrying will not make a non-covalent method covalent-aware."""
    import sys

    sys.path.insert(0, "tests")
    from test_pipeline import FailingMcsm, FakeDrugs, _run

    out = _run(
        dgidb_client=FakeDrugs([{"name": "Osimertinib", "approved": True, "score": 1.0}]),
        mcsm_client=FailingMcsm(),
    )
    failures = [f for f in out.failures if "covalent" in f.reason]
    results = [r for r in out.results if r.drug.upper() == "OSIMERTINIB"]
    assert failures or results, "covalent drug must produce an explicit outcome"
    if failures:
        assert failures[0].retryable is False
