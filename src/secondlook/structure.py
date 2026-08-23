"""Structure sourcing: RCSB PDB → AlphaFold DB → ESM Atlas fallback (Tier 2 Step 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from secondlook.alphafold import AlphaFoldError
from secondlook.mutation_validation import MutationValidationResult
from secondlook.rcsb import RcsbError

PLDDT_RELIABILITY_THRESHOLD = 70.0
ReliabilityFlag = Literal["high", "low"]
StructureSource = Literal["PDB", "AlphaFoldDB", "ESMAtlas"]
StructureStatus = Literal["found", "unavailable"]


class PdbClient(Protocol):
    def search_by_uniprot(
        self,
        accession: str,
        preferred_ligands: tuple[str, ...] = (),
        covering_residue: int | None = None,
    ) -> dict | None: ...


class AlphaFoldClient(Protocol):
    def fetch_models(self, accession: str) -> list[dict]: ...


class EsmClient(Protocol):
    def fold_sequence(self, sequence: str) -> str: ...


@dataclass(frozen=True)
class StructureResult:
    status: StructureStatus
    source: StructureSource | None
    id: str | None
    plddt_at_residue: float | None
    plddt_global: float | None
    reliability_flag: ReliabilityFlag | None
    ligand_bound: bool | None
    annotated_position: int | None
    pdb_text: str | None = None
    error_message: str | None = None


def plddt_reliability(plddt: float) -> ReliabilityFlag:
    return "low" if plddt < PLDDT_RELIABILITY_THRESHOLD else "high"


def is_dockable(pdb_text: str, residue_number: int) -> bool:
    """True when one chain holds both `residue_number` and a co-crystallized ligand.

    Stricter than `covers_residue`, and necessary because binding scoring needs
    the mutation and the drug pocket in the *same* chain. 3OG7 (BRAF) is the
    motivating case: chain A carries the ligand but leaves residue 600
    unresolved, while chain B resolves 600 and binds nothing — the entry passes
    `covers_residue` yet cannot support any binding analysis.

    Used to rank candidate entries, not to reject a structure outright: an entry
    that merely covers the residue is still worth returning, because AlphaMissense
    and binding-site distance remain reportable without a dockable pocket.
    """
    from secondlook.vina_dock import NoBindingSiteError, select_docking_chain

    try:
        select_docking_chain(pdb_text, residue_number)
    except NoBindingSiteError:
        return False
    return True


def covers_residue(pdb_text: str, residue_number: int) -> bool:
    """True when `pdb_text` has a real polymer residue numbered `residue_number`.

    Only `ATOM` records count. `HETATM` is deliberately excluded: waters, ions,
    and ligands are numbered in the same space as the polymer, so a structure
    whose only "residue 600" is a water molecule does not cover residue 600 —
    exactly the case that made the pipeline pick a 14-3-3/BRAF-phosphopeptide
    complex (8VSO) for BRAF V600E.
    """
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        try:
            if int(line[22:26]) == residue_number:
                return True
        except ValueError:
            continue
    return False


def residue_b_factor_from_pdb(pdb_text: str, residue_number: int) -> float | None:
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if line[12:16].strip() != "CA":
            continue
        try:
            resseq = int(line[22:26])
        except ValueError:
            continue
        if resseq != residue_number:
            continue
        try:
            return float(line[60:66])
        except ValueError:
            return None
    return None


def structure_unavailable_message(plddt: float | None) -> str:
    shown = "n/a" if plddt is None else f"{plddt}"
    return (
        "Structural analysis unavailable or low-confidence for this region "
        f"(pLDDT = {shown}, below reliability threshold). No structure-based binding "
        "signal is reported. AlphaMissense functional score is shown as the only "
        "available computational signal."
    )


def source_structure(
    validation: MutationValidationResult,
    *,
    pdb_client: PdbClient | None = None,
    alphafold_client: AlphaFoldClient | None = None,
    esm_client: EsmClient | None = None,
    allow_de_novo_folding: bool = False,
    preferred_ligands: tuple[str, ...] = (),
) -> StructureResult:
    """Fetch a wild-type structure; never fold the mutant sequence."""
    if pdb_client is None or alphafold_client is None or esm_client is None:
        from secondlook.alphafold import AlphaFoldDbClient
        from secondlook.esm_atlas import EsmAtlasClient
        from secondlook.rcsb import RcsbPdbClient

        pdb_client = pdb_client or RcsbPdbClient()
        alphafold_client = alphafold_client or AlphaFoldDbClient()
        esm_client = esm_client or EsmAtlasClient()

    if (
        validation.status != "valid"
        or validation.uniprot_accession is None
        or validation.position is None
    ):
        return _unavailable()

    position = validation.position
    accession = validation.uniprot_accession

    try:
        pdb_hit = pdb_client.search_by_uniprot(
            accession, preferred_ligands=preferred_ligands, covering_residue=position
        )
    except RcsbError:
        pdb_hit = None
    # Two things must hold before a PDB hit counts as usable, and both were
    # previously unchecked:
    #   1. It carries coordinates — every downstream binding step (chain
    #      resolution, HET-code lookup, docking) needs real atoms.
    #   2. Those coordinates actually contain the mutated residue.
    # Reporting a hit that fails either as `found` would advertise a
    # high-reliability experimental structure while silently disabling binding
    # scoring, and the resulting failure would then be explained as a
    # *binding-method* problem rather than an unusable structure. Fall through to
    # AlphaFold instead, whose models are full-length by construction.
    if (
        pdb_hit
        and (pdb_hit.get("pdb_text") or "").strip()
        and covers_residue(pdb_hit["pdb_text"], position)
    ):
        return StructureResult(
            status="found",
            source="PDB",
            id=str(pdb_hit["pdb_id"]),
            plddt_at_residue=None,
            plddt_global=None,
            reliability_flag="high",
            ligand_bound=bool(pdb_hit.get("ligand_bound")),
            annotated_position=position,
            pdb_text=pdb_hit["pdb_text"],
        )

    try:
        af_models = alphafold_client.fetch_models(accession)
    except AlphaFoldError:
        af_models = []
    model = _select_alphafold_model(af_models, accession, position)
    if model is not None:
        pdb_text = model.get("pdb_text") or ""
        if not pdb_text:
            fetch_pdb = getattr(alphafold_client, "fetch_pdb", None)
            if fetch_pdb is not None:
                try:
                    pdb_text = fetch_pdb(model) or ""
                except AlphaFoldError:
                    pdb_text = ""
        residue_plddt = residue_b_factor_from_pdb(pdb_text, position)
        global_plddt = model.get("global_metric")
        score_for_flag = residue_plddt if residue_plddt is not None else global_plddt
        flag: ReliabilityFlag | None = (
            plddt_reliability(score_for_flag) if score_for_flag is not None else None
        )
        return StructureResult(
            status="found",
            source="AlphaFoldDB",
            id=str(model["entry_id"]),
            plddt_at_residue=residue_plddt,
            plddt_global=float(global_plddt) if global_plddt is not None else None,
            reliability_flag=flag,
            ligand_bound=False,
            annotated_position=position,
            pdb_text=pdb_text or None,
        )

    if not allow_de_novo_folding or not validation.wildtype_sequence:
        return _unavailable()

    try:
        folded = esm_client.fold_sequence(validation.wildtype_sequence)
    except (TimeoutError, OSError, RuntimeError):
        return _unavailable()

    residue_plddt = residue_b_factor_from_pdb(folded, position)
    flag = plddt_reliability(residue_plddt) if residue_plddt is not None else None
    return StructureResult(
        status="found",
        source="ESMAtlas",
        id=None,
        plddt_at_residue=residue_plddt,
        plddt_global=None,
        reliability_flag=flag,
        ligand_bound=False,
        annotated_position=position,
        pdb_text=folded,
    )


def _select_alphafold_model(models: list[dict], accession: str, position: int) -> dict | None:
    covering = [
        model
        for model in models
        if int(model.get("uniprot_start") or 0) <= position <= int(model.get("uniprot_end") or 0)
    ]
    if not covering:
        return None

    canonical_prefix = f"AF-{accession}-F"

    def _rank(model: dict) -> tuple[int, int]:
        entry_id = str(model.get("entry_id") or "")
        canonical = 0 if entry_id.startswith(canonical_prefix) else 1
        length = int(model.get("uniprot_end") or 0) - int(model.get("uniprot_start") or 0)
        return (canonical, -length)

    covering.sort(key=_rank)
    return covering[0]


def _unavailable(plddt: float | None = None) -> StructureResult:
    return StructureResult(
        status="unavailable",
        source=None,
        id=None,
        plddt_at_residue=plddt,
        plddt_global=None,
        reliability_flag=None,
        ligand_bound=None,
        annotated_position=None,
        error_message=structure_unavailable_message(plddt),
    )
