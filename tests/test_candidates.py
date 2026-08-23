import pytest

from secondlook.candidates import (
    ZERO_CANDIDATES_MESSAGE,
    generate_candidates,
)
from secondlook.chembl import ChemblError
from secondlook.dgidb import DgidbError
from secondlook.mutation_validation import MutationValidationResult
from secondlook.opentargets import OpenTargetsError
from secondlook.pubchem import PubChemError


def _valid_tp53() -> MutationValidationResult:
    return MutationValidationResult(
        status="valid",
        gene="TP53",
        hgvs_normalized="p.Arg175His",
        uniprot_accession="P04637",
        isoform_note="P04637 (canonical)",
        position=175,
        reference_residue_expected="R",
        reference_residue_actual="R",
        mutation_type="missense",
        error_message=None,
        wildtype_sequence="R" * 393,
        mutant_sequence="R" * 174 + "H" + "R" * 218,
    )


class FakeDgidb:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.calls: list[str] = []

    def fetch_drugs(self, gene_symbol: str) -> list[dict]:
        self.calls.append(gene_symbol)
        if self.error:
            raise self.error
        return list(self.rows or [])


class FakeOpenTargets:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.calls: list[str] = []

    def fetch_drugs(self, gene_symbol: str) -> list[dict]:
        self.calls.append(gene_symbol)
        if self.error:
            raise self.error
        return list(self.rows or [])


class FakeChembl:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.calls: list[str] = []

    def fetch_drugs(self, gene_symbol: str) -> list[dict]:
        self.calls.append(gene_symbol)
        if self.error:
            raise self.error
        return list(self.rows or [])


class FakePubChem:
    def __init__(
        self, smiles_by_name: dict[str, str] | None = None, failing: set[str] | None = None
    ) -> None:
        self.smiles_by_name = smiles_by_name or {}
        self.failing = failing or set()
        self.calls: list[str] = []

    def fetch_smiles(self, drug_name: str) -> str:
        self.calls.append(drug_name)
        if drug_name in self.failing:
            raise PubChemError(f"PubChem failed for {drug_name}")
        if drug_name not in self.smiles_by_name:
            raise PubChemError(f"No SMILES for {drug_name}")
        return self.smiles_by_name[drug_name]


def test_zero_candidates_returns_exact_message_when_all_sources_empty():
    result = generate_candidates(
        _valid_tp53(),
        dgidb_client=FakeDgidb([]),
        opentargets_client=FakeOpenTargets([]),
        chembl_client=FakeChembl([]),
        pubchem_client=FakePubChem(),
    )
    assert result.status == "none"
    assert result.candidates == []
    assert result.error_message == ZERO_CANDIDATES_MESSAGE


def test_uses_dgidb_hits_and_does_not_call_later_sources():
    pubchem = FakePubChem({"OXALIPLATIN": "C1CCC1", "SIREMADLIN": "CC"})
    ot = FakeOpenTargets([{"name": "SHOULD_NOT_APPEAR", "approved": True}])
    chembl = FakeChembl([{"name": "ALSO_NO", "approved": False}])
    result = generate_candidates(
        _valid_tp53(),
        dgidb_client=FakeDgidb(
            [
                {"name": "SIREMADLIN", "approved": False, "score": 0.058},
                {"name": "OXALIPLATIN", "approved": True, "score": 0.011},
            ]
        ),
        opentargets_client=ot,
        chembl_client=chembl,
        pubchem_client=pubchem,
    )
    assert result.status == "found"
    assert [c.name for c in result.candidates] == ["OXALIPLATIN", "SIREMADLIN"]
    assert result.candidates[0].approved is True
    assert result.candidates[0].target_tier == "exact_protein"
    assert result.candidates[0].source == "DGIdb"
    assert result.candidates[0].smiles == "C1CCC1"
    assert ot.calls == []
    assert chembl.calls == []


def test_dgidb_error_falls_through_to_open_targets():
    ot = FakeOpenTargets([{"name": "IDASANUTLIN", "approved": False, "max_stage": "PHASE_3"}])
    chembl = FakeChembl([{"name": "SHOULD_NOT_APPEAR", "approved": False}])
    result = generate_candidates(
        _valid_tp53(),
        dgidb_client=FakeDgidb(error=DgidbError("DGIdb down")),
        opentargets_client=ot,
        chembl_client=chembl,
        pubchem_client=FakePubChem({"IDASANUTLIN": "CN"}),
    )
    assert result.status == "found"
    assert [c.name for c in result.candidates] == ["IDASANUTLIN"]
    assert result.candidates[0].source == "OpenTargets"
    assert result.candidates[0].target_tier == "same_family"
    assert chembl.calls == []


def test_dgidb_and_open_targets_errors_fall_through_to_chembl():
    result = generate_candidates(
        _valid_tp53(),
        dgidb_client=FakeDgidb(error=DgidbError("DGIdb down")),
        opentargets_client=FakeOpenTargets(error=OpenTargetsError("OT down")),
        chembl_client=FakeChembl([{"name": "CONTUSUGENE LADENOVEC", "approved": False}]),
        pubchem_client=FakePubChem({"CONTUSUGENE LADENOVEC": "N"}),
    )
    assert result.status == "found"
    assert result.candidates[0].name == "CONTUSUGENE LADENOVEC"
    assert result.candidates[0].source == "ChEMBL"
    assert result.candidates[0].target_tier == "same_pathway"


def test_all_three_source_errors_return_zero_candidates_message_not_raise():
    result = generate_candidates(
        _valid_tp53(),
        dgidb_client=FakeDgidb(error=DgidbError("DGIdb down")),
        opentargets_client=FakeOpenTargets(error=OpenTargetsError("OT down")),
        chembl_client=FakeChembl(error=ChemblError("ChEMBL down")),
        pubchem_client=FakePubChem(),
    )
    assert result.status == "none"
    assert result.error_message == ZERO_CANDIDATES_MESSAGE
    assert result.candidates == []


def test_pubchem_failure_on_one_candidate_does_not_abort_the_list():
    result = generate_candidates(
        _valid_tp53(),
        dgidb_client=FakeDgidb(
            [
                {"name": "OXALIPLATIN", "approved": True, "score": 0.1},
                {"name": "BADDRUG", "approved": True, "score": 0.09},
                {"name": "CARBOPLATIN", "approved": True, "score": 0.08},
            ]
        ),
        opentargets_client=FakeOpenTargets(error=OpenTargetsError("should not be called")),
        chembl_client=FakeChembl(error=ChemblError("should not be called")),
        pubchem_client=FakePubChem(
            {"OXALIPLATIN": "C1", "CARBOPLATIN": "C2"},
            failing={"BADDRUG"},
        ),
    )
    assert result.status == "found"
    assert [c.name for c in result.candidates] == ["OXALIPLATIN", "BADDRUG", "CARBOPLATIN"]
    smiles = {c.name: c.smiles for c in result.candidates}
    assert smiles["OXALIPLATIN"] == "C1"
    assert smiles["CARBOPLATIN"] == "C2"
    assert smiles["BADDRUG"] is None


def test_caps_shortlist_at_twenty_approved_first():
    rows = [{"name": f"DRUG{i}", "approved": i >= 10, "score": i} for i in range(25)]
    pubchem = FakePubChem({f"DRUG{i}": f"C{i}" for i in range(25)})
    result = generate_candidates(
        _valid_tp53(),
        dgidb_client=FakeDgidb(rows),
        opentargets_client=FakeOpenTargets([]),
        chembl_client=FakeChembl([]),
        pubchem_client=pubchem,
        max_candidates=20,
    )
    names = [c.name for c in result.candidates]
    assert len(names) == 20
    assert all(c.approved for c in result.candidates[:10])
    assert names[0] == "DRUG24"


def test_token_bucket_sleeps_when_empty():
    from secondlook.pubchem import TokenBucket

    clock = {"t": 0.0}
    sleeps: list[float] = []

    def now() -> float:
        return clock["t"]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    bucket = TokenBucket(rate_per_sec=5.0, capacity=1.0, clock=now, sleeper=sleep)
    bucket.acquire()
    bucket.acquire()
    assert sleeps
    assert sleeps[0] == pytest.approx(0.2, abs=0.001)


def test_chembl_picks_human_single_protein_with_matching_gene_symbol():
    from secondlook.chembl import _best_target_id

    targets = [
        {
            "target_chembl_id": "CHEMBL2424509",
            "organism": "Homo sapiens",
            "score": 15.0,
            "pref_name": "TP53-binding protein 1",
            "target_components": [
                {
                    "target_component_synonyms": [
                        {"component_synonym": "TP53BP1", "syn_type": "GENE_SYMBOL"}
                    ]
                }
            ],
        },
        {
            "target_chembl_id": "CHEMBL4096",
            "organism": "Homo sapiens",
            "score": 12.0,
            "pref_name": "Cellular tumor antigen p53",
            "target_components": [
                {
                    "target_component_synonyms": [
                        {"component_synonym": "TP53", "syn_type": "GENE_SYMBOL"}
                    ]
                }
            ],
        },
    ]
    assert _best_target_id(targets, "TP53") == "CHEMBL4096"


@pytest.mark.integration
def test_live_dgidb_tp53_includes_verified_drugs():
    from secondlook.dgidb import DgidbClient

    rows = DgidbClient().fetch_drugs("TP53")
    names = {row["name"].upper() for row in rows}
    assert {"PIRARUBICIN", "OXALIPLATIN", "CARBOPLATIN"} <= names
    assert any(row["approved"] for row in rows)


@pytest.mark.integration
def test_live_pubchem_oxaliplatin_smiles():
    from secondlook.pubchem import PubChemClient, TokenBucket

    smiles = PubChemClient(limiter=TokenBucket(rate_per_sec=5, capacity=5)).fetch_smiles(
        "OXALIPLATIN"
    )
    assert smiles
    assert "C" in smiles
