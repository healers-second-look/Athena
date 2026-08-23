"""Open Targets GraphQL client for target–disease–drug associations."""

from __future__ import annotations

import os
from urllib.parse import quote

import httpx

DEFAULT_OT_URL = "https://api.platform.opentargets.org/api/v4/graphql"
DEFAULT_ENSEMBL_REST = "https://rest.ensembl.org"

_CANDIDATES_QUERY = """
query TargetDrugs($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    approvedSymbol
    drugAndClinicalCandidates {
      rows {
        maxClinicalStage
        drug { name id drugType maximumClinicalStage }
      }
    }
  }
}
"""

_APPROVED_STAGES = {"PHASE_4", "APPROVED"}


class OpenTargetsError(RuntimeError):
    pass


class OpenTargetsClient:
    def __init__(
        self,
        url: str | None = None,
        ensembl_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url or os.environ.get("OPENTARGETS_GRAPHQL_URL") or DEFAULT_OT_URL
        self.ensembl_url = (
            ensembl_url or os.environ.get("ENSEMBL_REST_BASE") or DEFAULT_ENSEMBL_REST
        ).rstrip("/")
        self._client = client

    def fetch_drugs(self, gene_symbol: str) -> list[dict]:
        ensembl_id = self._ensembl_gene_id(gene_symbol)
        payload = self._post({"query": _CANDIDATES_QUERY, "variables": {"ensemblId": ensembl_id}})
        target = ((payload.get("data") or {}).get("target")) or {}
        rows = ((target.get("drugAndClinicalCandidates") or {}).get("rows")) or []
        drugs: list[dict] = []
        for row in rows:
            drug = row.get("drug") or {}
            name = drug.get("name")
            if not name:
                continue
            stage = str(row.get("maxClinicalStage") or drug.get("maximumClinicalStage") or "")
            drugs.append(
                {
                    "name": name,
                    "approved": stage.upper() in _APPROVED_STAGES,
                    "score": _stage_score(stage),
                    "max_stage": stage,
                }
            )
        return drugs

    def _ensembl_gene_id(self, gene_symbol: str) -> str:
        url = f"{self.ensembl_url}/lookup/symbol/homo_sapiens/{quote(gene_symbol)}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        try:
            if self._client is not None:
                response = self._client.get(url, headers=headers, timeout=40.0)
            else:
                response = httpx.get(url, headers=headers, timeout=40.0, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenTargetsError(f"Ensembl gene lookup failed for {gene_symbol}") from exc
        gene_id = payload.get("id")
        if not isinstance(gene_id, str) or not gene_id.startswith("ENSG"):
            raise OpenTargetsError(f"No Ensembl gene ID for {gene_symbol!r}")
        return gene_id

    def _post(self, body: dict) -> dict:
        try:
            if self._client is not None:
                response = self._client.post(self.url, json=body, timeout=40.0)
            else:
                response = httpx.post(self.url, json=body, timeout=40.0, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenTargetsError(f"Open Targets request failed for {self.url}") from exc
        if payload.get("errors"):
            raise OpenTargetsError(f"Open Targets GraphQL error: {payload['errors']}")
        return payload


def _stage_score(stage: str) -> float:
    order = {
        "PHASE_1": 1,
        "PHASE_2": 2,
        "PHASE_3": 3,
        "PHASE_4": 4,
        "APPROVED": 5,
    }
    return float(order.get(stage.upper(), 0))
