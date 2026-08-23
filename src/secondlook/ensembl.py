"""Ensembl REST helpers for MANE/canonical transcripts and VEP lookups."""

from __future__ import annotations

import os
from urllib.parse import quote

import httpx

from secondlook.http_retry import with_retry

DEFAULT_ENSEMBL_REST = "https://rest.ensembl.org"


class EnsemblError(RuntimeError):
    pass


class EnsemblTranscriptResolver:
    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("ENSEMBL_REST_BASE") or DEFAULT_ENSEMBL_REST
        ).rstrip("/")
        self._client = client

    def resolve_mane_select(self, gene_symbol: str) -> str:
        payload = self._get_json(
            f"/lookup/symbol/homo_sapiens/{quote(gene_symbol)}",
            params={"expand": "1"},
        )
        canonical = payload.get("canonical_transcript")
        if isinstance(canonical, str) and canonical.startswith("ENST"):
            return canonical.split(".", 1)[0]
        for transcript in payload.get("Transcript") or []:
            if transcript.get("is_canonical"):
                transcript_id = transcript.get("id")
                if isinstance(transcript_id, str):
                    return transcript_id.split(".", 1)[0]
        raise EnsemblError(f"No canonical/MANE Select transcript found for gene {gene_symbol!r}")

    def fetch_cds(self, transcript_id: str) -> str:
        payload = self._get_json(
            f"/sequence/id/{quote(transcript_id)}",
            params={"type": "cds"},
        )
        seq = payload.get("seq")
        if not isinstance(seq, str) or not seq:
            raise EnsemblError(f"No CDS sequence returned for transcript {transcript_id}")
        return seq

    def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict:
        return _ensembl_get_json(self.base_url, path, params=params, client=self._client)


class EnsemblVepClient:
    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("ENSEMBL_REST_BASE") or DEFAULT_ENSEMBL_REST
        ).rstrip("/")
        self._client = client

    def lookup_hgvs(self, transcript_id: str, hgvs: str) -> list[dict]:
        hgvs_id = f"{transcript_id}:{hgvs}"
        payload = _ensembl_get_json(
            self.base_url,
            f"/vep/human/hgvs/{quote(hgvs_id, safe=':.')}",
            params={"AlphaMissense": "1"},
            client=self._client,
        )
        if not isinstance(payload, list):
            raise EnsemblError(f"Unexpected VEP response for {hgvs_id}")
        return payload


def _ensembl_get_json(
    base_url: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    client: httpx.Client | None = None,
) -> dict | list:
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    # Request and status check both inside `attempt`: transport errors are
    # raised by the request call, so they must be covered to be retried and
    # converted rather than escaping as raw httpx errors.
    def attempt() -> httpx.Response:
        if client is not None:
            response = client.get(url, params=params, headers=headers, timeout=40.0)
        else:
            response = httpx.get(
                url, params=params, headers=headers, timeout=40.0, follow_redirects=True
            )
        response.raise_for_status()
        return response

    try:
        return with_retry(attempt).json()
    except httpx.HTTPError as exc:
        raise EnsemblError(f"Ensembl request failed for {url}") from exc
