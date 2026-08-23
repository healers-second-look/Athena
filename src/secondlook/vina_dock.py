"""AutoDock Vina docking fallback — WT vs mutant delta, separate from mCSM-lig."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Protocol

from secondlook.binding import BindingScore, McsmPageError, chain_for_residue

#: Per-dock wall clock. 120s is enough for a tiny ligand at exhaustiveness=1;
#: a kinase inhibitor at exhaustiveness=32 is not (ABL1 T315I / imatinib timed
#: out at 120s and scored in ~320s total for WT+mutant at 300s per dock).
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_SEED = 1
#: Vina's documentation recommends >=32 for consistent scores between runs; the
#: default of 8 trades reproducibility for speed. Since the quantity we read is a
#: *difference* between two runs, run-to-run variance lands directly in the signal,
#: so consistency matters more here than in ordinary virtual screening.
DEFAULT_EXHAUSTIVENESS = 32
DEFAULT_PADDING_ANGSTROM = 5.0
PHYSIOLOGICAL_PH = 7.4

#: Maximum distance from the mutated residue to the ligand for a docking delta to
#: be reported. An internal heuristic, not a validated cutoff — see the gold-standard
#: run in `validation/results.md`, where every case beyond this range produced a
#: delta indistinguishable from noise (|delta| < 0.06 kcal/mol) regardless of the
#: known clinical direction, while the one case inside it (EGFR T790M, 3.5 A)
#: produced the largest delta and the correct direction. Docking measures direct
#: contact; allosteric and conformational resistance act well beyond this range and
#: are outside what the method can represent at all.
MUTATION_CONTACT_MAX_ANGSTROM = 8.0

_MUTATION = re.compile(r"^([A-Z])(\d+)([A-Z])$")
_SKIP_HET = frozenset(
    {"HOH", "WAT", "DOD", "NA", "CL", "SO4", "PO4", "GOL", "EDO", "ACE", "NH2", "NME"}
)

ONE_TO_THREE = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "K": "LYS",
    "L": "LEU",
    "M": "MET",
    "N": "ASN",
    "P": "PRO",
    "Q": "GLN",
    "R": "ARG",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
    "Y": "TYR",
}


class VinaError(RuntimeError):
    """Vina/smina could not produce a WT-vs-mutant docking delta for this candidate."""


class ReceptorPrepError(VinaError):
    """Receptor protonation or PDBQT conversion failed."""


class MutantPlacementError(VinaError):
    """In-place side-chain mutation could not be applied defensibly."""


class LigandPrepError(VinaError):
    """SMILES could not be converted to a 3D PDBQT ligand."""


class MutationOutsidePocketError(VinaError):
    """The mutation is too far from the ligand for a docking delta to mean anything.

    Deliberately not a "failure": the pipeline worked correctly and produced an
    informative negative result.
    """


class NoBindingSiteError(VinaError):
    """No co-crystallized ligand coordinates to center a docking box."""


class VinaTimeoutError(VinaError):
    """A Vina run exceeded the configured timeout."""


class VinaRunError(VinaError):
    """Vina itself failed on the WT or mutant docking run."""


@dataclass(frozen=True)
class GridBox:
    center: tuple[float, float, float]
    size: tuple[float, float, float]


class ReceptorPreparer(Protocol):
    def to_pdbqt(self, pdb_text: str) -> str: ...


class MutantBuilder(Protocol):
    def place_sidechain(self, pdb_text: str, mutation: str, position: int) -> str: ...


class LigandPreparer(Protocol):
    def to_pdbqt(self, smiles: str) -> str: ...


class DockEngine(Protocol):
    def dock(
        self,
        receptor_pdbqt: str,
        ligand_pdbqt: str,
        box: GridBox,
        timeout_seconds: float,
        seed: int,
    ) -> float: ...


class Protonator(Protocol):
    def protonate(self, pdb_text: str) -> str: ...


def parse_mutation_shorthand(mutation: str) -> tuple[str, int, str]:
    match = _MUTATION.match(mutation.strip())
    if match is None:
        raise MutantPlacementError(f"Cannot parse mutation shorthand: {mutation}")
    return match.group(1), int(match.group(2)), match.group(3)


def is_primary_altloc(line: str) -> bool:
    """True for atoms in the primary conformation.

    Crystal structures often model side chains in two or more alternate
    conformations, each atom repeated with an altLoc code (column 17). Passing
    all of them to a receptor preparer presents the same atom twice, and RDKit
    reports the resulting over-bonded atom as ``Explicit valence for atom # 2 C,
    5, is greater than permitted``. 8C7X (BRAF) carries 72 such atoms in each of
    two conformations and fails meeko prep outright; 3OG7 has none and prepares
    cleanly — which is why this only surfaced on some structures.

    Keeps the blank altLoc (single conformation) and 'A' (conventionally the
    highest-occupancy alternate), the standard convention for structure prep.
    """
    if len(line) < 17:
        return True
    return line[16] in (" ", "A")


def strip_alternate_conformations(pdb_text: str) -> str:
    """Drop non-primary altLoc atoms and blank the altLoc column."""
    kept = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            if not is_primary_altloc(line):
                continue
            if len(line) >= 17 and line[16] != " ":
                line = line[:16] + " " + line[17:]
        kept.append(line)
    return "\n".join(kept) + "\n"


def chains_with_residue(pdb_text: str, position: int) -> list[str]:
    """Chains whose ATOM records resolve `position`, in file order.

    A residue can be unresolved (disordered) in one chain of a multi-copy entry
    and present in another — 3OG7 resolves BRAF 600 in chain B but not chain A.
    """
    found: list[str] = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        try:
            if int(line[22:26]) != position:
                continue
        except ValueError:
            continue
        chain = line[21].strip() or "A"
        if chain not in found:
            found.append(chain)
    return found


def chains_with_ligand(pdb_text: str) -> dict[str, int]:
    """Chain → atom count of its largest non-trivial HET group.

    Waters, ions, and cryoprotectants are excluded via `_SKIP_HET`; they are not
    binding-site markers and would drag a grid box off the real pocket.
    """
    groups: dict[tuple[str, str, str], int] = {}
    for line in pdb_text.splitlines():
        if not line.startswith("HETATM") or len(line) < 54:
            continue
        resname = line[17:20].strip().upper()
        if resname in _SKIP_HET:
            continue
        key = (line[21].strip() or "A", line[22:26], resname)
        groups[key] = groups.get(key, 0) + 1
    best: dict[str, int] = {}
    for (chain, _resseq, _resname), count in groups.items():
        if count > best.get(chain, 0):
            best[chain] = count
    return best


def select_docking_chain(pdb_text: str, position: int) -> str:
    """Pick the chain to dock against: it must hold the residue *and* a ligand.

    Three separate failures made this necessary, all seen on real structures:

    1. **meeko cannot prepare a multi-chain receptor.** `Polymer.from_pdb_string`
       raises on the full asymmetric unit ("Explicit valence for atom # 2 C, 5")
       while succeeding on a single protonated chain.
    2. **The grid box could be centered on another chain's ligand.**
       `ligand_hetatm_coords` takes the largest HET group anywhere in the file,
       so on a two-copy entry the box could sit on chain A's pocket while the
       mutation being scored is in chain B — docking a real ligand into a site
       the mutation cannot influence, and reporting the delta as meaningful.
    3. **The mutated residue and the ligand may live in different chains.**
       3OG7 resolves BRAF 600 only in chain B, and binds its ligand only in
       chain A, so neither chain alone can support the analysis.

    Raises `NoBindingSiteError` when no single chain has both, rather than
    silently docking against a site the mutation does not touch.
    """
    residue_chains = chains_with_residue(pdb_text, position)
    if not residue_chains:
        raise NoBindingSiteError(f"No chain in the structure resolves residue {position}")
    ligand_chains = chains_with_ligand(pdb_text)
    usable = [chain for chain in residue_chains if chain in ligand_chains]
    if not usable:
        raise NoBindingSiteError(
            f"No chain holds both residue {position} and a co-crystallized ligand "
            f"(residue in {sorted(residue_chains)}, ligand in {sorted(ligand_chains) or 'none'}); "
            "cannot place a grid box on a pocket this mutation could affect"
        )
    # Largest ligand wins — the biggest non-trivial HET group is the likeliest
    # real drug-binding site rather than a buffer component that escaped _SKIP_HET.
    return max(usable, key=lambda chain: ligand_chains[chain])


def extract_chain(pdb_text: str, chain: str) -> str:
    """Keep only `chain`'s ATOM/HETATM records, plus terminators."""
    kept = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            if (line[21].strip() or "A") == chain:
                kept.append(line)
        elif line.startswith("END"):
            kept.append(line)
    if not any(line.startswith("ATOM") for line in kept):
        raise ReceptorPrepError(f"Chain {chain} has no ATOM records")
    return "\n".join(kept) + "\n"


def ligand_hetatm_coords(pdb_text: str) -> tuple[tuple[float, float, float], ...]:
    groups: dict[tuple[str, str, str], list[tuple[float, float, float]]] = {}
    for line in pdb_text.splitlines():
        if not line.startswith("HETATM") or len(line) < 54:
            continue
        resname = line[17:20].strip().upper()
        if resname in _SKIP_HET or not is_primary_altloc(line):
            continue
        try:
            x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
        except ValueError:
            continue
        key = (line[21], line[22:26], resname)
        groups.setdefault(key, []).append((x, y, z))
    if not groups:
        return ()
    largest = max(groups.values(), key=len)
    return tuple(largest)


def grid_box_from_pdb(pdb_text: str, padding: float = DEFAULT_PADDING_ANGSTROM) -> GridBox:
    coords = ligand_hetatm_coords(pdb_text)
    if not coords:
        raise NoBindingSiteError(
            "No co-crystallized ligand coordinates in the structure; cannot center a Vina grid box"
        )
    xs, ys, zs = zip(*coords, strict=True)
    center = (
        (min(xs) + max(xs)) / 2.0,
        (min(ys) + max(ys)) / 2.0,
        (min(zs) + max(zs)) / 2.0,
    )
    size = (
        (max(xs) - min(xs)) + 2.0 * padding,
        (max(ys) - min(ys)) + 2.0 * padding,
        (max(zs) - min(zs)) + 2.0 * padding,
    )
    return GridBox(center=center, size=size)


def protein_atoms_only(pdb_text: str) -> str:
    """Polymer atoms only, in a single conformation.

    Alternate conformations are dropped here rather than in the caller: every
    receptor-prep path goes through this function, and a duplicated atom breaks
    meeko regardless of which path reached it.
    """
    kept = [
        line
        for line in pdb_text.splitlines()
        if line.startswith(("ATOM", "TER", "END")) and is_primary_altloc(line)
    ]
    if not any(line.startswith("ATOM") for line in kept):
        raise ReceptorPrepError("PDB text has no ATOM records for receptor prep")
    blanked = [
        line[:16] + " " + line[17:] if line.startswith("ATOM") and len(line) >= 17 else line
        for line in kept
    ]
    return "\n".join(blanked) + "\n"


class PdbFixerProtonator:
    def protonate(self, pdb_text: str) -> str:
        try:
            return _pdbfixer_complete(pdb_text, mutations=None, chain=None)
        except (ReceptorPrepError, MutantPlacementError):
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ReceptorPrepError(f"Receptor protonation failed: {exc}") from exc


class PdbFixerMutantBuilder:
    """In-place side-chain swap via OpenMM PDBFixer templates; backbone kept, no re-fold."""

    def place_sidechain(self, pdb_text: str, mutation: str, position: int) -> str:
        wt, pos, mut = parse_mutation_shorthand(mutation)
        if pos != position:
            raise MutantPlacementError(f"Mutation {mutation} does not match position {position}")
        try:
            chain = chain_for_residue(pdb_text, position)
        except McsmPageError as exc:
            raise MutantPlacementError(
                f"Cannot resolve chain for residue {position}: {exc}"
            ) from exc
        expected = ONE_TO_THREE.get(wt)
        target = ONE_TO_THREE.get(mut)
        if expected is None or target is None:
            raise MutantPlacementError(f"Non-standard residue in mutation {mutation}")
        actual = _residue_name_at(pdb_text, chain, position)
        if actual != expected:
            raise MutantPlacementError(
                f"PDB residue {chain}:{position} is {actual}, not {expected} from {mutation}"
            )
        try:
            placed = _pdbfixer_complete(
                pdb_text,
                mutations=[f"{expected}-{position}-{target}"],
                chain=chain,
            )
            return minimize_mutated_sidechain(placed, position, chain)
        except MutantPlacementError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise MutantPlacementError(f"PDBFixer could not place {mutation}: {exc}") from exc


def strip_terminal_oxt(pdb_text: str) -> str:
    """Remove C-terminal OXT oxygens before RDKit-based receptor prep.

    PDBFixer caps each chain terminus with an OXT carboxylate oxygen. The bond
    lengths it produces are chemically sound (C-OXT 1.27 A on 8C7X) but the
    CA-C-OXT angle is tight enough that CA and OXT end up ~1.83 A apart — inside
    RDKit's `proximityBonding` cutoff. RDKit therefore bonds OXT to CA *as well
    as* to C, giving a five-bonded alpha carbon, and meeko's receptor prep dies
    in `Chem.SanitizeMol` with ``Explicit valence for atom # 2 C, 5, is greater
    than permitted``.

    Dropping OXT is safe for docking: it is a single peripheral oxygen at a chain
    terminus, essentially always far from the drug pocket the grid box covers,
    and its absence does not alter the binding site. Chain termini are the only
    place OXT appears, so nothing inside the pocket is touched.

    Only structures whose terminal geometry happens to land inside the cutoff hit
    this, which is why 3OG7 prepared cleanly while 8C7X did not.
    """
    kept = [
        line
        for line in pdb_text.splitlines()
        if not (line.startswith(("ATOM", "HETATM")) and line[12:16].strip().upper() == "OXT")
    ]
    return "\n".join(kept) + "\n"


def largest_ligand_group(
    pdb_text: str,
) -> tuple[str | None, tuple[tuple[float, float, float], ...]]:
    """The biggest non-trivial HET group, with its residue name.

    Returning the name matters for honest reporting: the distance is measured to
    *this* ligand, which is whatever was co-crystallized, not necessarily the drug
    being evaluated.
    """
    groups: dict[tuple[str, str, str], list[tuple[float, float, float]]] = {}
    for line in pdb_text.splitlines():
        if not line.startswith("HETATM") or len(line) < 54:
            continue
        resname = line[17:20].strip().upper()
        if resname in _SKIP_HET or not is_primary_altloc(line):
            continue
        try:
            coords = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            continue
        groups.setdefault((line[21], line[22:26], resname), []).append(coords)
    if not groups:
        return None, ()
    key = max(groups, key=lambda k: len(groups[k]))
    return key[2], tuple(groups[key])


def residue_ligand_distance(pdb_text: str, position: int) -> tuple[float | None, str | None]:
    """Shortest distance from residue `position` to the co-crystallized ligand.

    Returns ``(distance, ligand_het_code)``. The ligand code is part of the
    answer, not decoration — see `residue_min_distance_to_ligand`.
    """
    ligand_id, ligand = largest_ligand_group(pdb_text)
    if not ligand:
        return None, None
    residue: list[tuple[float, float, float]] = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or len(line) < 54:
            continue
        try:
            if int(line[22:26]) != position:
                continue
            residue.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
        except ValueError:
            continue
    if not residue:
        return None, ligand_id
    return min(math.dist(a, b) for a in residue for b in ligand), ligand_id


def residue_min_distance_to_ligand(pdb_text: str, position: int) -> float | None:
    """Shortest distance (A) from any atom of `position` to any ligand atom.

    Reported so a docking delta can be read in context. A mutation far from the
    pocket cannot change binding by direct contact, and any delta computed for it
    is docking noise rather than signal — KIT D816V sits >20 A from imatinib in
    8PQD because its resistance is allosteric (activation-loop stabilization),
    a mechanism docking cannot represent at all. Returns None when either the
    residue or a ligand is absent.
    """
    distance, _ligand_id = residue_ligand_distance(pdb_text, position)
    return distance


def resolve_overvalence(pdb_text: str) -> str:
    """Drop excess hydrogens from atoms RDKit reads as over-bonded.

    RDKit infers receptor bonds by proximity, so two side chains packed close
    together acquire a bond that chemistry does not support: in 8PQD it bonds
    LYS761:NZ to PHE763:CZ, leaving NZ with CE + three hydrogens + that contact
    and failing sanitization with ``Explicit valence for atom # 9 C, 5``. The
    OXT case handled in `strip_terminal_oxt` is one instance of the same class;
    this handles the general one.

    Removing a hydrogen rather than a heavy atom keeps the side chain intact and
    the geometry unchanged. It under-protonates one residue, which is a real but
    small approximation — and it is applied identically to the wild-type and
    mutant receptors, so it largely cancels in the delta, which is what the
    pipeline actually reports.

    A no-op when RDKit is unavailable or the structure already sanitizes.
    """
    try:
        from rdkit import Chem
    except ImportError:
        return pdb_text

    mol = Chem.MolFromPDBBlock(pdb_text, sanitize=False, removeHs=False, proximityBonding=True)
    if mol is None:
        return pdb_text

    max_valence = {1: 1, 6: 4, 7: 4, 8: 2, 16: 6}
    drop_serials: set[int] = set()
    for atom in mol.GetAtoms():
        limit = max_valence.get(atom.GetAtomicNum())
        if limit is None or atom.GetDegree() <= limit:
            continue
        hydrogens = [n for n in atom.GetNeighbors() if n.GetAtomicNum() == 1]
        # Drop the fewest hydrogens that bring the atom back within its valence.
        for neighbour in hydrogens[: atom.GetDegree() - limit]:
            info = neighbour.GetPDBResidueInfo()
            if info is not None:
                drop_serials.add(info.GetSerialNumber())

    if not drop_serials:
        return pdb_text

    kept = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            try:
                if int(line[6:11]) in drop_serials:
                    continue
            except ValueError:
                pass
        kept.append(line)
    return "\n".join(kept) + "\n"


class OpenBabelReceptorPreparer:
    """Receptor PDBQT via the Open Babel CLI — drop-in for MeekoReceptorPreparer.

    meeko's ``update_H_positions`` fails on some PDBFixer-mutated side chains
    (ISSUES.md §2). Open Babel does not use meeko residue templates, so it is the
    first candidate workaround. Invoked as the ``obabel`` binary, not a Python
    binding, matching how ``VinaEngine`` shells out to its own tool.
    """

    def __init__(self, *, binary: str | None = None, timeout_seconds: float = 60.0) -> None:
        self._binary = binary
        self.timeout_seconds = timeout_seconds

    def to_pdbqt(self, pdb_text: str) -> str:
        pdb_text = resolve_overvalence(strip_terminal_oxt(pdb_text))
        binary = self._binary or shutil.which("obabel")
        if not binary:
            raise ReceptorPrepError("open babel is not installed (obabel not on PATH)")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "receptor.pdb"
            dst = Path(tmp) / "receptor.pdbqt"
            src.write_text(pdb_text)
            try:
                completed = subprocess.run(
                    [binary, "-ipdb", str(src), "-opdbqt", "-xr", "-O", str(dst)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ReceptorPrepError(
                    f"open babel receptor prep exceeded {self.timeout_seconds}s"
                ) from exc
            pdbqt = dst.read_text() if dst.exists() else ""
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown obabel error").strip()
            raise ReceptorPrepError(f"open babel receptor prep failed: {detail}")
        if not pdbqt.strip() or not any(line.startswith("ATOM") for line in pdbqt.splitlines()):
            raise ReceptorPrepError("open babel produced an empty receptor PDBQT")
        return pdbqt


class MeekoReceptorPreparer:
    def to_pdbqt(self, pdb_text: str) -> str:
        pdb_text = resolve_overvalence(strip_terminal_oxt(pdb_text))
        try:
            from meeko import MoleculePreparation, PDBQTWriterLegacy, Polymer, ResidueChemTemplates
            from meeko.polymer import PolymerCreationError
        except ImportError as exc:
            raise ReceptorPrepError("meeko is not installed") from exc
        try:
            templates = ResidueChemTemplates.create_from_defaults()
            mk_prep = MoleculePreparation()
            polymer = Polymer.from_pdb_string(pdb_text, templates, mk_prep, allow_bad_res=True)
            rigid, _flex = PDBQTWriterLegacy.write_string_from_polymer(polymer)
        except (PolymerCreationError, RuntimeError, ValueError, KeyError) as exc:
            raise ReceptorPrepError(f"meeko receptor prep failed: {exc}") from exc
        if not rigid.strip():
            raise ReceptorPrepError("meeko produced an empty receptor PDBQT")
        return rigid


def _largest_fragment(mol):
    """Drop salt counter-ions (e.g. "...hydrochloride" SMILES = drug + Cl-).

    PubChem's canonical SMILES for a salt-form drug name is multi-fragment;
    meeko's MoleculePreparation.prepare() raises ValueError("RDKit molecule
    has N fragments") on those rather than silently picking one, and that
    ValueError previously wasn't caught here at all (aborted the whole
    mutation, not just this candidate). The active pharmaceutical ingredient
    for docking purposes is the largest fragment by atom count; keep it and
    proceed instead of just failing when the input happens to be a salt.
    """
    from rdkit import Chem

    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    if len(frags) <= 1:
        return mol
    return max(frags, key=lambda frag: frag.GetNumAtoms())


class MeekoLigandPreparer:
    def to_pdbqt(self, smiles: str) -> str:
        try:
            from meeko import MoleculePreparation, PDBQTWriterLegacy
            from rdkit import Chem
            from rdkit.Chem import AllChem
        except ImportError as exc:
            raise LigandPrepError("rdkit/meeko is not installed") from exc
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise LigandPrepError(f"Cannot parse SMILES: {smiles}")
        mol = _largest_fragment(mol)
        try:
            mol = Chem.AddHs(mol)
            embed = AllChem.EmbedMolecule(mol, randomSeed=DEFAULT_SEED)
            if embed != 0:
                raise LigandPrepError(f"Cannot generate a 3D conformer from SMILES: {smiles}")
            AllChem.UFFOptimizeMolecule(mol)
            setups = MoleculePreparation().prepare(mol)
            if not setups:
                raise LigandPrepError("meeko produced no ligand setup")
            pdbqt, ok, error_msg = PDBQTWriterLegacy.write_string(setups[0])
        except LigandPrepError:
            raise
        except (ValueError, RuntimeError, KeyError, IndexError) as exc:
            raise LigandPrepError(f"meeko/RDKit ligand prep failed for {smiles}: {exc}") from exc
        if not ok or not pdbqt.strip():
            raise LigandPrepError(error_msg or "meeko failed to write ligand PDBQT")
        return pdbqt


class VinaEngine:
    def __init__(self, exhaustiveness: int = DEFAULT_EXHAUSTIVENESS) -> None:
        self.exhaustiveness = exhaustiveness

    def dock(
        self,
        receptor_pdbqt: str,
        ligand_pdbqt: str,
        box: GridBox,
        timeout_seconds: float,
        seed: int,
    ) -> float:
        src_root = str(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as tmp:
            rec = Path(tmp) / "receptor.pdbqt"
            lig = Path(tmp) / "ligand.pdbqt"
            rec.write_text(receptor_pdbqt)
            lig.write_text(ligand_pdbqt)
            payload = json.dumps(
                {
                    "receptor_path": str(rec),
                    "ligand_path": str(lig),
                    "center": list(box.center),
                    "size": list(box.size),
                    "seed": seed,
                    "exhaustiveness": self.exhaustiveness,
                }
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = src_root + os.pathsep + env.get("PYTHONPATH", "")
            try:
                completed = subprocess.run(
                    [sys.executable, "-c", _VINA_SUBPROCESS, payload],
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise VinaTimeoutError(f"Vina docking exceeded {timeout_seconds}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown Vina error").strip()
            raise VinaRunError(detail)
        try:
            return float(completed.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise VinaRunError(f"Vina returned no score: {completed.stdout!r}") from exc


#: Maximum RMSD (Å) between the redocked native ligand and its crystal pose for
#: the docking setup to be trusted. 2.0 Å is the field's conventional threshold
#: for "correct pose recovered" — not a value tuned here.
NATIVE_POSE_RMSD_LIMIT = 2.0


def pose_rmsd(
    a: tuple[tuple[float, float, float], ...],
    b: tuple[tuple[float, float, float], ...],
) -> float | None:
    """Symmetry-naive RMSD between two coordinate sets of equal length."""
    if not a or len(a) != len(b):
        return None
    return (sum(math.dist(p, q) ** 2 for p, q in zip(a, b, strict=True)) / len(a)) ** 0.5


class NativePoseControl:
    """Redock the co-crystallized ligand and check its known pose is recovered.

    A docking run has many ways to be quietly wrong: a grid box on the wrong
    site, a mis-prepared receptor, a protonation error, an inhibitor whose bound
    conformation the search cannot reach. None of these raise — they return a
    number that looks like every other number.

    Redocking the ligand that is already in the crystal is the one available
    ground truth: its correct answer is known exactly, because it is sitting in
    the structure. If the setup cannot recover a pose it was handed, its score for
    a *different* molecule is not worth reading.

    Used as a gate on trust, not as a score. A failed control means the delta is
    withheld, not that the delta is wrong.
    """

    def __init__(self, rmsd_limit: float = NATIVE_POSE_RMSD_LIMIT) -> None:
        self.rmsd_limit = rmsd_limit

    def check(self, docked: tuple, native: tuple) -> tuple[bool, float | None]:
        rmsd = pose_rmsd(docked, native)
        if rmsd is None:
            # Could not be evaluated. Do not treat "unmeasurable" as "passed".
            return False, None
        return rmsd <= self.rmsd_limit, rmsd


class VinaDockClient:
    """Receptor/ligand prep and WT-vs-mutant docking with AutoDock Vina."""

    def __init__(
        self,
        *,
        receptor_preparer: ReceptorPreparer | None = None,
        mutant_builder: MutantBuilder | None = None,
        ligand_preparer: LigandPreparer | None = None,
        dock_engine: DockEngine | None = None,
        protonator: Protonator | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        seed: int = DEFAULT_SEED,
        exhaustiveness: int = DEFAULT_EXHAUSTIVENESS,
    ) -> None:
        defaults = receptor_preparer is None
        self._receptor_preparer = receptor_preparer or OpenBabelReceptorPreparer()
        self._mutant_builder = mutant_builder or PdbFixerMutantBuilder()
        self._ligand_preparer = ligand_preparer or MeekoLigandPreparer()
        self._dock_engine = dock_engine or VinaEngine(exhaustiveness=exhaustiveness)
        self._protonator = (
            protonator if protonator is not None else (PdbFixerProtonator() if defaults else None)
        )
        self.timeout_seconds = timeout_seconds
        self.seed = seed

    def score(
        self,
        *,
        pdb_text: str,
        smiles: str,
        mutation: str,
        position: int,
    ) -> BindingScore:
        # Restrict to one chain before anything else: meeko cannot prepare a
        # multi-chain receptor, and the grid box must come from the same chain as
        # the mutated residue. See select_docking_chain for the full rationale.
        chain = select_docking_chain(pdb_text, position)
        single_chain = extract_chain(pdb_text, chain)

        box = grid_box_from_pdb(single_chain)
        protein = protein_atoms_only(single_chain)

        # The deposited structure may be either form. Well-studied oncogenic
        # mutations are frequently crystallized *as the mutant* — 3OG7 is BRAF
        # with GLU already at 600 — so assuming wild-type input would refuse
        # exactly the best-characterised structures. Whichever form is on disk,
        # the other is built by side-chain substitution and the delta stays
        # mutant minus wild-type.
        wt_aa, _pos, mut_aa = parse_mutation_shorthand(mutation)
        wt_three, mut_three = ONE_TO_THREE.get(wt_aa), ONE_TO_THREE.get(mut_aa)
        if wt_three is None or mut_three is None:
            raise MutantPlacementError(f"Non-standard residue in mutation {mutation}")
        actual = _residue_name_at(protein, chain, position)

        if actual == wt_three:
            wildtype_pdb = self._protonator.protonate(protein) if self._protonator else protein
            mutant_pdb = self._mutant_builder.place_sidechain(protein, mutation, position)
        elif actual == mut_three:
            mutant_pdb = self._protonator.protonate(protein) if self._protonator else protein
            wildtype_pdb = self._mutant_builder.place_sidechain(
                protein, f"{mut_aa}{position}{wt_aa}", position
            )
        else:
            raise MutantPlacementError(
                f"PDB residue {chain}:{position} is {actual}, which is neither the "
                f"wild-type ({wt_three}) nor the mutant ({mut_three}) of {mutation}"
            )

        # Refuse before spending two docking runs on a number that cannot carry
        # signal. Checked after chain selection so the distance is measured against
        # the pocket actually being scored.
        distance = residue_min_distance_to_ligand(single_chain, position)
        if distance is not None and distance > MUTATION_CONTACT_MAX_ANGSTROM:
            raise MutationOutsidePocketError(
                f"Mutation at position {position} is {distance:.1f} A from the ligand, "
                f"beyond the {MUTATION_CONTACT_MAX_ANGSTROM:.0f} A docking contact range"
            )

        wildtype_pdbqt = self._receptor_preparer.to_pdbqt(wildtype_pdb)
        mutant_pdbqt = self._receptor_preparer.to_pdbqt(mutant_pdb)
        ligand_pdbqt = self._ligand_preparer.to_pdbqt(smiles)
        wildtype_score = self._dock_engine.dock(
            wildtype_pdbqt, ligand_pdbqt, box, self.timeout_seconds, self.seed
        )
        mutant_score = self._dock_engine.dock(
            mutant_pdbqt, ligand_pdbqt, box, self.timeout_seconds, self.seed
        )
        return BindingScore(
            status="scored",
            method="docking",
            delta_score=mutant_score - wildtype_score,
            affinity_class=None,
            distance_angstrom=residue_min_distance_to_ligand(single_chain, position),
            ligand_id=None,
            chain=chain,
        )


def _residue_name_at(pdb_text: str, chain: str, position: int) -> str:
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if (line[21].strip() or "A") != chain:
            continue
        try:
            resseq = int(line[22:26])
        except ValueError:
            continue
        if resseq == position:
            return line[17:20].strip().upper()
    raise MutantPlacementError(f"No residue {chain}:{position} in PDB")


def minimize_mutated_sidechain(
    pdb_text: str, position: int, chain: str, max_iterations: int = 300
) -> str:
    """Relieve steric clashes introduced by an in-place side-chain swap.

    PDBFixer places the new side chain on the existing backbone using a template
    rotamer. That rotamer frequently clashes with neighbouring atoms, and a clash
    is worth several kcal/mol to a docking score — far more than the differences
    being measured. Without relaxation, the delta partly reports how badly the
    substituted rotamer was placed rather than how the mutation affects binding.

    The minimization is deliberately **restrained**: backbone atoms are held with
    a stiff positional restraint and only the mutated residue and its immediate
    neighbours move. Unrestrained minimization would drift the whole structure,
    and the wild-type and mutant receptors would then differ by that drift as well
    as by the mutation — invalidating the comparison the delta depends on.

    A few hundred steps is enough to relieve clashes. This is clash relief, not
    conformational sampling: recovering conformational effects needs the methods
    in the "options" list, not a longer minimization.

    Returns the input unchanged if OpenMM is unavailable, rather than failing the
    run — an unminimized delta is noisier, not invalid.
    """
    try:
        import openmm
        from openmm import app, unit
    except ImportError:
        return pdb_text

    from io import StringIO

    try:
        structure = app.PDBFile(StringIO(pdb_text))
        forcefield = app.ForceField("amber14-all.xml", "implicit/gbn2.xml")
        system = forcefield.createSystem(
            structure.topology, nonbondedMethod=app.NoCutoff, constraints=None
        )

        # Stiff positional restraints on everything except the mutated residue and
        # its sequence neighbours, so relaxation stays local.
        restraint = openmm.CustomExternalForce("k*periodicdistance(x, y, z, x0, y0, z0)^2")
        restraint.addGlobalParameter("k", 100.0 * unit.kilojoules_per_mole / unit.nanometer**2)
        for name in ("x0", "y0", "z0"):
            restraint.addPerParticleParameter(name)

        mobile = {position - 1, position, position + 1}
        for atom in structure.topology.atoms():
            residue = atom.residue
            is_mobile = (
                residue.chain.id == chain
                and residue.id.strip().isdigit()
                and int(residue.id) in mobile
                and atom.name not in ("N", "CA", "C", "O")
            )
            if not is_mobile:
                restraint.addParticle(atom.index, structure.positions[atom.index])
        system.addForce(restraint)

        integrator = openmm.LangevinIntegrator(
            300 * unit.kelvin, 1 / unit.picosecond, 0.002 * unit.picoseconds
        )
        simulation = app.Simulation(
            structure.topology,
            system,
            integrator,
            openmm.Platform.getPlatformByName("CPU"),
        )
        simulation.context.setPositions(structure.positions)
        simulation.minimizeEnergy(maxIterations=max_iterations)
        state = simulation.context.getState(getPositions=True)

        out = StringIO()
        app.PDBFile.writeFile(structure.topology, state.getPositions(), out, keepIds=True)
        return out.getvalue()
    except (ValueError, KeyError, openmm.OpenMMException) as exc:  # noqa: F841
        # Force-field parameterization can fail on unusual residues. An unminimized
        # receptor is degraded, not wrong, so proceed rather than lose the case.
        return pdb_text


def _pdbfixer_complete(pdb_text: str, mutations: list[str] | None, chain: str | None) -> str:
    try:
        from openmm.app import PDBFile
        from pdbfixer import PDBFixer
    except ImportError as exc:
        raise ReceptorPrepError("pdbfixer/openmm is not installed") from exc
    fixer = PDBFixer(pdbfile=StringIO(pdb_text))
    if mutations and chain is not None:
        fixer.applyMutations(mutations, chain)
    fixer.findMissingResidues()
    fixer.missingResidues = {}
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(PHYSIOLOGICAL_PH)
    out = StringIO()
    PDBFile.writeFile(fixer.topology, fixer.positions, out, keepIds=True)
    return out.getvalue()


_VINA_SUBPROCESS = """
import json, sys
from secondlook.vina_dock import run_vina_from_files
args = json.loads(sys.argv[1])
print(run_vina_from_files(**args))
"""


def run_vina_from_files(
    *,
    receptor_path: str,
    ligand_path: str,
    center: list[float],
    size: list[float],
    seed: int,
    exhaustiveness: int,
) -> float:
    try:
        from vina import Vina
    except ImportError as exc:
        raise VinaRunError("vina is not installed") from exc
    engine = Vina(sf_name="vina", cpu=1, seed=seed, verbosity=0)
    engine.set_receptor(receptor_path)
    engine.set_ligand_from_file(ligand_path)
    engine.compute_vina_maps(center=center, box_size=size)
    engine.dock(exhaustiveness=exhaustiveness, n_poses=1)
    energies = engine.energies(n_poses=1)
    return float(energies[0][0])
