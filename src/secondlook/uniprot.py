"""UniProt REST sequence lookup for mutation validation."""

from __future__ import annotations

import os
import re

import httpx

from secondlook.http_retry import with_retry
from secondlook.mutation_validation import ProteinSequence

DEFAULT_UNIPROT_API_BASE = "https://rest.uniprot.org"
_ACCESSION = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-\d+)?$",
    re.IGNORECASE,
)
_HEADER_ACCESSION = re.compile(r"^[>\w]+\|([^|]+)\|")
_HEADER_GENE = re.compile(r"\bGN=(\S+)")
_HEADER_VERSION = re.compile(r"\bSV=(\d+)")


class UniProtLookupError(RuntimeError):
    pass


class UniProtSequenceProvider:
    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("UNIPROT_API_BASE") or DEFAULT_UNIPROT_API_BASE
        ).rstrip("/")
        self._client = client

    def fetch(self, identifier: str) -> ProteinSequence:
        accession = identifier.strip()
        if not _ACCESSION.fullmatch(accession):
            accession = self._resolve_gene_symbol(accession)
        fasta = self._get(f"/uniprotkb/{accession}.fasta")
        return parse_uniprot_fasta(fasta)

    def _resolve_gene_symbol(self, symbol: str) -> str:
        query = f"gene_exact:{symbol} AND organism_id:9606 AND reviewed:true"
        payload = self._get_json(
            "/uniprotkb/search",
            params={"query": query, "fields": "accession", "format": "json", "size": "1"},
        )
        results = payload.get("results") or []
        if not results:
            raise UniProtLookupError(
                f"No reviewed human UniProt entry found for gene symbol {symbol!r}"
            )
        return results[0]["primaryAccession"]

    def _get(self, path: str) -> str:
        response = self._request("GET", path)
        return response.text

    def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict:
        response = self._request("GET", path, params=params)
        return response.json()

    def _request(
        self, method: str, path: str, params: dict[str, str] | None = None
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"

        # Both the request and the status check live inside `attempt`, so
        # connection resets and timeouts — which are raised by the request call,
        # not by raise_for_status() — are retried and then converted to
        # UniProtLookupError rather than escaping as raw httpx errors.
        def attempt() -> httpx.Response:
            if self._client is not None:
                response = self._client.request(method, url, params=params, timeout=30.0)
            else:
                response = httpx.request(
                    method, url, params=params, timeout=30.0, follow_redirects=True
                )
            response.raise_for_status()
            return response

        try:
            return with_retry(attempt)
        except httpx.HTTPError as exc:
            raise UniProtLookupError(f"UniProt request failed for {url}") from exc


def parse_uniprot_fasta(fasta: str) -> ProteinSequence:
    lines = [line.strip() for line in fasta.strip().splitlines() if line.strip()]
    if not lines or not lines[0].startswith(">"):
        raise UniProtLookupError("UniProt FASTA response was empty or missing a header")
    header = lines[0]
    sequence = "".join(lines[1:])
    accession_match = _HEADER_ACCESSION.search(header)
    accession = accession_match.group(1) if accession_match else header[1:].split()[0]
    gene_match = _HEADER_GENE.search(header)
    version_match = _HEADER_VERSION.search(header)
    isoform_label = accession if re.search(r"-\d+$", accession) else "canonical"
    version = version_match.group(1) if version_match else "unknown"
    return ProteinSequence(
        accession=accession,
        sequence=sequence,
        gene=gene_match.group(1) if gene_match else None,
        isoform_note=f"{accession} ({isoform_label}; UniProt sequence version {version})",
    )
