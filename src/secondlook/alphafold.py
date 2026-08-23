"""AlphaFold DB lookups for precomputed wild-type models."""

from __future__ import annotations

import os

import httpx

DEFAULT_ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api"


class AlphaFoldError(RuntimeError):
    pass


class AlphaFoldDbClient:
    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("ALPHAFOLD_API_BASE") or DEFAULT_ALPHAFOLD_API
        ).rstrip("/")
        self._client = client

    def fetch_models(self, accession: str) -> list[dict]:
        response = self._get(f"{self.base_url}/prediction/{accession}")
        if response.status_code == 404:
            return []
        payload = response.json()
        if not isinstance(payload, list):
            raise AlphaFoldError(f"Unexpected AlphaFold response for {accession}")
        models = []
        for item in payload:
            models.append(
                {
                    "entry_id": item.get("entryId") or item.get("modelEntityId"),
                    "uniprot_start": item.get("uniprotStart") or item.get("sequenceStart") or 1,
                    "uniprot_end": item.get("uniprotEnd") or item.get("sequenceEnd") or 0,
                    "global_metric": item.get("globalMetricValue"),
                    "pdb_text": "",
                    "pdb_url": item.get("pdbUrl"),
                }
            )
        return models

    def fetch_pdb(self, model: dict) -> str:
        pdb_url = model.get("pdb_url")
        if not pdb_url:
            return ""
        return self._get(pdb_url).text

    def _get(self, url: str) -> httpx.Response:
        # The request call belongs inside the try — connection resets and
        # timeouts are raised there, not by raise_for_status().
        try:
            if self._client is not None:
                response = self._client.get(url, timeout=40.0)
            else:
                response = httpx.get(url, timeout=40.0, follow_redirects=True)
            if response.status_code != 404:
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AlphaFoldError(f"AlphaFold request failed for {url}") from exc
        return response
