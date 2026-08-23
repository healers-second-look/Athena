import pytest

from secondlook.alphafold import AlphaFoldError
from secondlook.mutation_validation import MutationValidationResult
from secondlook.rcsb import RcsbError
from secondlook.structure import (
    covers_residue,
    plddt_reliability,
    residue_b_factor_from_pdb,
    source_structure,
    structure_unavailable_message,
)

MINI_PDB = """\
ATOM      1  N   ARG A 175      0.000   0.000   0.000  1.00 10.00           N
ATOM      2  CA  ARG A 175      1.000   0.000   0.000  1.00 96.62           C
ATOM      3  C   ARG A 175      2.000   0.000   0.000  1.00 11.00           C
ATOM      4  CA  TYR A 176      3.000   0.000   0.000  1.00 40.00           C
"""

LOW_CONF_PDB = """\
ATOM      1  CA  ARG A 175      1.000   0.000   0.000  1.00 40.00           C
"""


def _valid_tp53(*, mutant: str = "H") -> MutationValidationResult:
    wt = "R" * 393
    mut = "R" * 174 + mutant + "R" * 218
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
        wildtype_sequence=wt,
        mutant_sequence=mut,
    )


class FakePdb:
    def __init__(self, hit=None) -> None:
        self.hit = hit
        self.calls: list[str] = []

    def search_by_uniprot(
        self,
        accession: str,
        preferred_ligands: tuple[str, ...] = (),
        covering_residue: int | None = None,
    ) -> dict | None:
        self.calls.append(accession)
        return self.hit


class FakeAlphaFold:
    def __init__(self, models: list[dict] | None = None) -> None:
        self.models = models or []
        self.calls: list[str] = []

    def fetch_models(self, accession: str) -> list[dict]:
        self.calls.append(accession)
        return self.models


class FakeEsm:
    def __init__(self, pdb_text: str | None = MINI_PDB, error: Exception | None = None) -> None:
        self.pdb_text = pdb_text
        self.error = error
        self.sequences: list[str] = []

    def fold_sequence(self, sequence: str) -> str:
        self.sequences.append(sequence)
        if self.error:
            raise self.error
        assert self.pdb_text is not None
        return self.pdb_text


def test_plddt_below_70_is_low_reliability_but_defined():
    assert plddt_reliability(69.9) == "low"
    assert plddt_reliability(70.0) == "high"
    assert plddt_reliability(96.62) == "high"


def test_reads_ca_b_factor_at_mutated_residue():
    assert residue_b_factor_from_pdb(MINI_PDB, 175) == 96.62
    assert residue_b_factor_from_pdb(MINI_PDB, 176) == 40.00
    assert residue_b_factor_from_pdb(MINI_PDB, 1) is None


def test_unavailable_message_matches_spec():
    assert structure_unavailable_message(40.0) == (
        "Structural analysis unavailable or low-confidence for this region "
        "(pLDDT = 40.0, below reliability threshold). No structure-based binding "
        "signal is reported. AlphaMissense functional score is shown as the only "
        "available computational signal."
    )


def test_prefers_experimental_pdb_over_alphafold():
    # `pdb_text` is required for a hit to count as usable — a PDB entry without
    # coordinates cannot be scored, so source_structure falls through to AlphaFold.
    pdb = FakePdb(
        {
            "pdb_id": "9C5S",
            "ligand_bound": True,
            "resolution": 1.01,
            "ligands": ("ZN",),
            "pdb_text": MINI_PDB,
        }
    )
    af = FakeAlphaFold(
        [
            {
                "entry_id": "AF-P04637-F1",
                "uniprot_start": 1,
                "uniprot_end": 393,
                "global_metric": 75.06,
                "pdb_text": MINI_PDB,
            }
        ]
    )
    esm = FakeEsm()
    result = source_structure(_valid_tp53(), pdb_client=pdb, alphafold_client=af, esm_client=esm)
    assert result.status == "found"
    assert result.source == "PDB"
    assert result.id == "9C5S"
    assert result.ligand_bound is True
    assert result.reliability_flag == "high"
    assert result.plddt_at_residue is None
    assert result.annotated_position == 175
    assert af.calls == []
    assert esm.sequences == []


def test_alphafold_used_when_no_pdb_and_records_residue_plddt():
    af = FakeAlphaFold(
        [
            {
                "entry_id": "AF-P04637-2-F1",
                "uniprot_start": 1,
                "uniprot_end": 341,
                "global_metric": 76.94,
                "pdb_text": MINI_PDB,
            },
            {
                "entry_id": "AF-P04637-F1",
                "uniprot_start": 1,
                "uniprot_end": 393,
                "global_metric": 75.06,
                "pdb_text": MINI_PDB,
            },
        ]
    )
    result = source_structure(
        _valid_tp53(),
        pdb_client=FakePdb(None),
        alphafold_client=af,
        esm_client=FakeEsm(),
    )
    assert result.status == "found"
    assert result.source == "AlphaFoldDB"
    assert result.id == "AF-P04637-F1"
    assert result.plddt_global == 75.06
    assert result.plddt_at_residue == 96.62
    assert result.reliability_flag == "high"


def test_low_residue_plddt_is_flagged_but_not_suppressed():
    af = FakeAlphaFold(
        [
            {
                "entry_id": "AF-P04637-F1",
                "uniprot_start": 1,
                "uniprot_end": 393,
                "global_metric": 75.06,
                "pdb_text": LOW_CONF_PDB,
            }
        ]
    )
    result = source_structure(
        _valid_tp53(),
        pdb_client=FakePdb(None),
        alphafold_client=af,
        esm_client=FakeEsm(),
    )
    assert result.status == "found"
    assert result.plddt_at_residue == 40.0
    assert result.reliability_flag == "low"
    assert result.error_message is None


def test_esm_fold_is_gated_off_the_demo_path():
    esm = FakeEsm()
    result = source_structure(
        _valid_tp53(),
        pdb_client=FakePdb(None),
        alphafold_client=FakeAlphaFold([]),
        esm_client=esm,
        allow_de_novo_folding=False,
    )
    assert result.status == "unavailable"
    assert result.error_message == structure_unavailable_message(None)
    assert esm.sequences == []


def test_esm_fallback_folds_wildtype_not_mutant_sequence():
    esm = FakeEsm(MINI_PDB)
    validation = _valid_tp53()
    result = source_structure(
        validation,
        pdb_client=FakePdb(None),
        alphafold_client=FakeAlphaFold([]),
        esm_client=esm,
        allow_de_novo_folding=True,
    )
    assert result.status == "found"
    assert result.source == "ESMAtlas"
    assert esm.sequences == [validation.wildtype_sequence]
    assert validation.mutant_sequence not in esm.sequences


def test_esm_timeout_returns_explicit_unavailable_message():
    esm = FakeEsm(error=TimeoutError("hang"))
    result = source_structure(
        _valid_tp53(),
        pdb_client=FakePdb(None),
        alphafold_client=FakeAlphaFold([]),
        esm_client=esm,
        allow_de_novo_folding=True,
    )
    assert result.status == "unavailable"
    assert result.error_message == structure_unavailable_message(None)
    assert result.source is None


class FailingPdb:
    def search_by_uniprot(
        self,
        accession: str,
        preferred_ligands: tuple[str, ...] = (),
        covering_residue: int | None = None,
    ) -> dict | None:
        raise RcsbError("RCSB request failed (simulated)")


class FailingAlphaFold:
    def fetch_models(self, accession: str) -> list[dict]:
        raise AlphaFoldError("AlphaFold request failed (simulated)")


def test_rcsb_failure_falls_through_to_alphafold_not_a_crash():
    af = FakeAlphaFold(
        [
            {
                "entry_id": "AF-P04637-F1",
                "uniprot_start": 1,
                "uniprot_end": 393,
                "global_metric": 75.06,
                "pdb_text": MINI_PDB,
            }
        ]
    )
    result = source_structure(
        _valid_tp53(), pdb_client=FailingPdb(), alphafold_client=af, esm_client=FakeEsm()
    )
    assert result.status == "found"
    assert result.source == "AlphaFoldDB"


def test_rcsb_and_alphafold_failure_returns_unavailable_not_a_crash():
    result = source_structure(
        _valid_tp53(),
        pdb_client=FailingPdb(),
        alphafold_client=FailingAlphaFold(),
        esm_client=FakeEsm(),
        allow_de_novo_folding=False,
    )
    assert result.status == "unavailable"
    assert result.error_message == structure_unavailable_message(None)


@pytest.mark.integration
def test_live_alphafold_p04637_canonical_model():
    from secondlook.alphafold import AlphaFoldDbClient

    client = AlphaFoldDbClient()
    models = client.fetch_models("P04637")
    f1 = next(model for model in models if model["entry_id"] == "AF-P04637-F1")
    assert f1["global_metric"] == pytest.approx(75.06, abs=0.01)
    pdb_text = client.fetch_pdb(f1)
    assert residue_b_factor_from_pdb(pdb_text, 175) == pytest.approx(96.62, abs=0.05)


@pytest.mark.integration
def test_live_rcsb_p04637_returns_ligand_bound_experimental_structure():
    from secondlook.rcsb import RcsbPdbClient

    hit = RcsbPdbClient().search_by_uniprot("P04637")
    assert hit is not None
    assert hit["pdb_id"]
    assert hit["ligand_bound"] is True


@pytest.mark.integration
def test_live_source_structure_prefers_pdb_for_tp53():
    result = source_structure(_valid_tp53(), allow_de_novo_folding=False)
    assert result.status == "found"
    assert result.source == "PDB"
    assert result.annotated_position == 175
    assert result.reliability_flag == "high"


# --- Regression: a PDB hit without coordinates must not be reported "found" ----
# RcsbPdbClient._entry_hit returned entry metadata only and never downloaded the
# structure file, so every PDB-sourced StructureResult carried pdb_text=None.
# source_structure still reported status="found" with reliability_flag="high",
# which silently disabled binding scoring for the primary structure source —
# and made the resulting failure look like a binding-method problem rather than
# a missing structure. Caught by the first real end-to-end run (BRAF V600E).


def test_pdb_hit_without_coordinates_falls_through_to_alphafold():
    pdb = FakePdb({"pdb_id": "8VSO", "ligand_bound": True, "resolution": 2.1, "ligands": ("LIG",)})
    af = FakeAlphaFold(
        [
            {
                "entry_id": "AF-P04637-F1",
                "uniprot_start": 1,
                "uniprot_end": 393,
                "global_metric": 75.06,
                "pdb_text": MINI_PDB,
            }
        ]
    )
    result = source_structure(
        _valid_tp53(), pdb_client=pdb, alphafold_client=af, esm_client=FakeEsm()
    )
    assert result.source == "AlphaFoldDB"
    assert result.pdb_text


def test_pdb_hit_with_empty_coordinates_falls_through_to_alphafold():
    pdb = FakePdb({"pdb_id": "8VSO", "ligand_bound": True, "pdb_text": "   \n  "})
    af = FakeAlphaFold(
        [
            {
                "entry_id": "AF-P04637-F1",
                "uniprot_start": 1,
                "uniprot_end": 393,
                "global_metric": 75.06,
                "pdb_text": MINI_PDB,
            }
        ]
    )
    result = source_structure(
        _valid_tp53(), pdb_client=pdb, alphafold_client=af, esm_client=FakeEsm()
    )
    assert result.source == "AlphaFoldDB"


def test_any_found_structure_always_carries_coordinates():
    """The invariant the bug violated: found implies scoreable."""
    for pdb_hit in (
        {"pdb_id": "8VSO", "ligand_bound": True},  # no coordinates
        {"pdb_id": "8VSO", "ligand_bound": True, "pdb_text": ""},  # empty
        {"pdb_id": "8VSO", "ligand_bound": True, "pdb_text": MINI_PDB},
    ):
        result = source_structure(
            _valid_tp53(),
            pdb_client=FakePdb(pdb_hit),
            alphafold_client=FakeAlphaFold(
                [
                    {
                        "entry_id": "AF-P04637-F1",
                        "uniprot_start": 1,
                        "uniprot_end": 393,
                        "global_metric": 75.06,
                        "pdb_text": MINI_PDB,
                    }
                ]
            ),
            esm_client=FakeEsm(),
        )
        if result.status == "found":
            assert result.pdb_text, f"found structure without coordinates for {pdb_hit}"


def test_rcsb_client_exposes_a_coordinate_fetcher():
    """Guards the root cause: metadata-only clients silently break binding."""
    from secondlook.rcsb import RcsbPdbClient

    assert hasattr(RcsbPdbClient, "fetch_pdb_text")


# --- Regression: the chosen PDB entry must contain the mutated residue --------
# The RCSB search matches any entry linked to the UniProt accession, including
# complexes that contain only a short peptide from the protein. For BRAF V600E
# the top hit was 8VSO — a 14-3-3 sigma / BRAF-phosphopeptide ternary complex
# whose BRAF chain spans residues 255-263 and whose only atom numbered 600 is a
# water. It was reported as a high-reliability experimental structure, and the
# resulting failure was blamed on the binding methods.

PEPTIDE_ONLY_PDB = """\
ATOM      1  CA  SER P 259      0.000   0.000   0.000  1.00 20.00           C
ATOM      2  CA  PRO P 260      1.000   0.000   0.000  1.00 20.00           C
HETATM    3  O   HOH B 600      9.000   9.000   9.000  1.00 30.00           O
"""


def test_covers_residue_ignores_hetatm_waters_and_ligands():
    assert covers_residue(PEPTIDE_ONLY_PDB, 259) is True
    # Numbered 600, but it is a water on a HETATM line — not coverage.
    assert covers_residue(PEPTIDE_ONLY_PDB, 600) is False
    assert covers_residue(MINI_PDB, 175) is True
    assert covers_residue(MINI_PDB, 999) is False


def test_pdb_entry_not_covering_the_residue_falls_through_to_alphafold():
    """The BRAF V600E / 8VSO case, reduced to a unit test."""
    pdb = FakePdb({"pdb_id": "8VSO", "ligand_bound": True, "pdb_text": PEPTIDE_ONLY_PDB})
    af = FakeAlphaFold(
        [
            {
                "entry_id": "AF-P04637-F1",
                "uniprot_start": 1,
                "uniprot_end": 393,
                "global_metric": 75.06,
                "pdb_text": MINI_PDB,
            }
        ]
    )
    result = source_structure(
        _valid_tp53(), pdb_client=pdb, alphafold_client=af, esm_client=FakeEsm()
    )
    assert result.source == "AlphaFoldDB"
    assert result.status == "found"


def test_source_structure_asks_the_client_to_cover_the_mutated_residue():
    """The filter belongs in the search, not only in a post-hoc check.

    Otherwise the client returns the first accession match and a covering entry
    further down the candidate list is never considered.
    """

    class RecordingPdb:
        def __init__(self):
            self.kwargs = None

        def search_by_uniprot(self, accession, preferred_ligands=(), covering_residue=None):
            self.kwargs = {
                "preferred_ligands": preferred_ligands,
                "covering_residue": covering_residue,
            }
            return None

    pdb = RecordingPdb()
    source_structure(
        _valid_tp53(),
        pdb_client=pdb,
        alphafold_client=FakeAlphaFold([]),
        esm_client=FakeEsm(),
    )
    assert pdb.kwargs["covering_residue"] == 175


def test_a_found_pdb_structure_always_contains_the_mutated_residue():
    """Invariant: source=PDB implies the residue is present in ATOM records."""
    for pdb_text in (PEPTIDE_ONLY_PDB, "", MINI_PDB):
        result = source_structure(
            _valid_tp53(),
            pdb_client=FakePdb({"pdb_id": "XXXX", "ligand_bound": True, "pdb_text": pdb_text}),
            alphafold_client=FakeAlphaFold([]),
            esm_client=FakeEsm(),
        )
        if result.source == "PDB":
            assert covers_residue(result.pdb_text, 175)
