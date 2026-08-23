"""ChEMBL REST client for pathway/family-level drug candidates."""

from __future__ import annotations

import os
from urllib.parse import quote

import httpx

DEFAULT_CHEMBL_API = "https://www.ebi.ac.uk/chembl/api/data"


class ChemblError(RuntimeError):
    pass


class ChemblClient:
    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("CHEMBL_API_BASE") or DEFAULT_CHEMBL_API
        ).rstrip("/")
        self._client = client

    def fetch_drugs(self, gene_symbol: str) -> list[dict]:
        search = self._get_json(f"/target/search.json?q={quote(gene_symbol)}")
        target_id = _best_target_id(search.get("targets") or [], gene_symbol)
        if not target_id:
            return []
        mechanisms = self._get_json(f"/mechanism.json?target_chembl_id={quote(target_id)}&limit=50")
        rows: list[dict] = []
        for mechanism in mechanisms.get("mechanisms") or []:
            mol_id = mechanism.get("molecule_chembl_id")
            if not mol_id:
                continue
            molecule = self._get_json(f"/molecule/{quote(mol_id)}.json")
            name = (molecule.get("pref_name") or mol_id).replace("_", " ")
            max_phase = mechanism.get("max_phase")
            rows.append(
                {
                    "name": name,
                    "approved": _is_approved_phase(max_phase),
                    "score": float(max_phase or 0),
                }
            )
        return rows

    def _get_json(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        try:
            if self._client is not None:
                response = self._client.get(url, timeout=40.0)
            else:
                response = httpx.get(url, timeout=40.0, follow_redirects=True)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ChemblError(f"ChEMBL request failed for {url}") from exc


def _best_target_id(targets: list[dict], gene_symbol: str) -> str | None:
    symbol = gene_symbol.upper()
    if not targets:
        return None

    def rank(target: dict) -> tuple:
        organism_penalty = 0 if target.get("organism") == "Homo sapiens" else 1
        components = target.get("target_components") or []
        synonyms = [
            (syn.get("component_synonym") or "").upper()
            for component in components
            for syn in component.get("target_component_synonyms") or []
            if syn.get("syn_type") == "GENE_SYMBOL"
        ]
        gene_penalty = 0 if symbol in synonyms else 1
        single_penalty = 0 if len(components) == 1 and symbol in synonyms else 1
        return (
            organism_penalty,
            gene_penalty,
            single_penalty,
            len(components) or 99,
            -float(target.get("score") or 0),
        )

    return min(targets, key=rank).get("target_chembl_id")


def _is_approved_phase(max_phase: object) -> bool:
    try:
        return float(max_phase) >= 4
    except (TypeError, ValueError):
        return str(max_phase).upper() in {"4", "4.0", "APPROVED"}
