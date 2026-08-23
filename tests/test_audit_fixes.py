"""Fixes from the external scientific audit."""

import pytest

from secondlook.ligand_identity import (
    compare_inchikeys,
    connectivity_layer,
    inchikey_from_smiles,
    match_ligand,
)
from secondlook.vina_dock import (
    DEFAULT_EXHAUSTIVENESS,
    NATIVE_POSE_RMSD_LIMIT,
    NativePoseControl,
    pose_rmsd,
)

IMATINIB = "CC1=C(C=C(C=C1)NC(=O)C2=CC=C(C=C2)CN3CCN(CC3)C)NC4=NC=CC(=N4)C5=CN=CC=C5"
VEMURAFENIB = "CCCS(=O)(=O)NC1=C(C(=C(C=C1)F)C(=O)C2=CNC3=C2C=C(C=N3)C4=CC=C(C=C4)Cl)F"


# --- Vina exhaustiveness -----------------------------------------------------


def test_exhaustiveness_meets_vina_guidance():
    """Run-to-run variance lands directly in a delta, so consistency matters here."""
    assert DEFAULT_EXHAUSTIVENESS >= 32


# --- Ligand identity ---------------------------------------------------------


def test_inchikey_is_derived_from_structure_not_name():
    assert inchikey_from_smiles(IMATINIB) == "KTUFNOKKBVMGRW-UHFFFAOYSA-N"


def test_unparseable_smiles_yields_no_key_rather_than_raising():
    assert inchikey_from_smiles("not-a-smiles") is None


def test_exact_and_connectivity_matches_are_distinguished():
    key = inchikey_from_smiles(IMATINIB)
    assert compare_inchikeys(key, key) == "exact"
    assert compare_inchikeys(key, connectivity_layer(key) + "-ZZZZZZZZZZ-N") == "connectivity"
    assert compare_inchikeys(key, "AAAAAAAAAAAAAA-BBBBBBBBBB-C") == "none"


def test_different_drugs_do_not_match():
    assert (
        compare_inchikeys(inchikey_from_smiles(IMATINIB), inchikey_from_smiles(VEMURAFENIB))
        == "none"
    )


def test_exact_match_wins_over_a_connectivity_match():
    key = inchikey_from_smiles(IMATINIB)
    result = match_ligand(
        IMATINIB,
        {
            "AAA": connectivity_layer(key) + "-ZZZZZZZZZZ-N",
            "STI": key,
        },
    )
    assert result.kind == "exact"
    assert result.het_code == "STI"


def test_connectivity_match_is_flagged_not_silently_exact():
    key = inchikey_from_smiles(IMATINIB)
    result = match_ligand(IMATINIB, {"STI": connectivity_layer(key) + "-ZZZZZZZZZZ-N"})
    assert result.kind == "connectivity"
    assert result.is_exact is False
    assert "stereochemistry" in result.note


def test_no_match_returns_none_rather_than_a_guess():
    """The old substring resolver could match an unrelated three-letter code."""
    result = match_ligand(IMATINIB, {"KY9": "AAAAAAAAAAAAAA-BBBBBBBBBB-C"})
    assert result.matched is False
    assert result.het_code is None


def test_ky9_does_not_match_osimertinib_by_accident():
    """The concrete case: EGFR 8A27 holds KY9, which is not the candidate drug."""
    result = match_ligand(VEMURAFENIB, {"KY9": inchikey_from_smiles(IMATINIB)})
    assert result.matched is False


# --- Native-pose control -----------------------------------------------------


def test_rmsd_is_zero_for_an_identical_pose():
    pose = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert pose_rmsd(pose, pose) == pytest.approx(0.0)


def test_recovered_pose_passes_the_control():
    native = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    docked = ((0.5, 0.0, 0.0), (1.5, 0.0, 0.0))
    ok, rmsd = NativePoseControl().check(docked, native)
    assert ok is True
    assert rmsd == pytest.approx(0.5)


def test_misplaced_pose_fails_the_control():
    native = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    docked = ((9.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    ok, rmsd = NativePoseControl().check(docked, native)
    assert ok is False
    assert rmsd > NATIVE_POSE_RMSD_LIMIT


def test_unmeasurable_control_does_not_count_as_passed():
    """Silence must not read as success — the failure mode this whole audit is about."""
    ok, rmsd = NativePoseControl().check((), ())
    assert ok is False
    assert rmsd is None
    ok2, _ = NativePoseControl().check(((0.0, 0.0, 0.0),), ())
    assert ok2 is False


def test_rmsd_limit_is_the_conventional_threshold():
    assert NATIVE_POSE_RMSD_LIMIT == 2.0


# --- Minimization ------------------------------------------------------------


def test_minimization_degrades_gracefully_without_openmm(monkeypatch):
    """An unminimized receptor is noisier, not invalid — never lose the case."""
    from secondlook import vina_dock

    pdb = "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n"
    monkeypatch.setitem(__import__("sys").modules, "openmm", None)
    out = vina_dock.minimize_mutated_sidechain(pdb, 1, "A")
    assert isinstance(out, str) and out
