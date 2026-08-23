"""Candidate drug generation (Tier 2 Step 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from secondlook.chembl import ChemblError
from secondlook.dgidb import DgidbError
from secondlook.mutation_validation import MutationValidationResult
from secondlook.opentargets import OpenTargetsError
from secondlook.pubchem import PubChemError

ZERO_CANDIDATES_MESSAGE = (
    "No candidate drugs targeting this protein, its family, or its pathway "
    "were found in open databases. "
    "Tier 2 cannot generate a signal for this target."
)

SHORTLIST_MAX = 20
TargetTier = Literal["exact_protein", "same_family", "same_pathway"]
CandidateSource = Literal["DGIdb", "OpenTargets", "ChEMBL"]

_TIER_FOR_SOURCE: dict[CandidateSource, TargetTier] = {
    "DGIdb": "exact_protein",
    "OpenTargets": "same_family",
    "ChEMBL": "same_pathway",
}


class DrugSource(Protocol):
    def fetch_drugs(self, gene_symbol: str) -> list[dict]: ...


class SmilesClient(Protocol):
    def fetch_smiles(self, drug_name: str) -> str: ...


@dataclass(frozen=True)
class DrugCandidate:
    name: str
    source: CandidateSource
    target_tier: TargetTier
    approved: bool | None
    smiles: str | None
    smiles_source: str | None


@dataclass(frozen=True)
class CandidateResult:
    status: Literal["found", "none"]
    candidates: list[DrugCandidate]
    error_message: str | None = None


def generate_candidates(
    validation: MutationValidationResult,
    *,
    dgidb_client: DrugSource | None = None,
    opentargets_client: DrugSource | None = None,
    chembl_client: DrugSource | None = None,
    pubchem_client: SmilesClient | None = None,
    max_candidates: int = SHORTLIST_MAX,
) -> CandidateResult:
    if (
        dgidb_client is None
        or opentargets_client is None
        or chembl_client is None
        or pubchem_client is None
    ):
        from secondlook.chembl import ChemblClient
        from secondlook.dgidb import DgidbClient
        from secondlook.opentargets import OpenTargetsClient
        from secondlook.pubchem import PubChemClient

        dgidb_client = dgidb_client or DgidbClient()
        opentargets_client = opentargets_client or OpenTargetsClient()
        chembl_client = chembl_client or ChemblClient()
        pubchem_client = pubchem_client or PubChemClient()

    if validation.status != "valid" or not validation.gene:
        return _none()

    gene = validation.gene
    rows, source = _first_source(gene, dgidb_client, opentargets_client, chembl_client)
    if not rows or source is None:
        return _none()

    ranked = _rank(rows)[:max_candidates]
    candidates: list[DrugCandidate] = []
    for row in ranked:
        name = str(row["name"])
        smiles = None
        smiles_source = None
        try:
            smiles = pubchem_client.fetch_smiles(name)
            smiles_source = "PubChem"
        except PubChemError:
            smiles = None
            smiles_source = None
        candidates.append(
            DrugCandidate(
                name=name,
                source=source,
                target_tier=_TIER_FOR_SOURCE[source],
                approved=row.get("approved"),
                smiles=smiles,
                smiles_source=smiles_source,
            )
        )
    return CandidateResult(status="found", candidates=candidates, error_message=None)


def _first_source(
    gene: str,
    dgidb_client: DrugSource,
    opentargets_client: DrugSource,
    chembl_client: DrugSource,
) -> tuple[list[dict], CandidateSource | None]:
    try:
        rows = dgidb_client.fetch_drugs(gene)
    except DgidbError:
        rows = []
    if rows:
        return rows, "DGIdb"

    try:
        rows = opentargets_client.fetch_drugs(gene)
    except OpenTargetsError:
        rows = []
    if rows:
        return rows, "OpenTargets"

    try:
        rows = chembl_client.fetch_drugs(gene)
    except ChemblError:
        rows = []
    if rows:
        return rows, "ChEMBL"

    return [], None


def _rank(rows: list[dict]) -> list[dict]:
    def key(row: dict) -> tuple:
        approved = bool(row.get("approved"))
        score = float(row.get("score") or 0)
        return (not approved, -score, str(row.get("name") or ""))

    deduped: dict[str, dict] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        existing = deduped.get(name.upper())
        if existing is None or float(row.get("score") or 0) > float(existing.get("score") or 0):
            deduped[name.upper()] = row
    return sorted(deduped.values(), key=key)


def _none() -> CandidateResult:
    return CandidateResult(status="none", candidates=[], error_message=ZERO_CANDIDATES_MESSAGE)
