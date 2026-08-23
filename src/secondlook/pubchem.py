"""PubChem PUG REST client for Canonical SMILES, with client-side throttling."""

from __future__ import annotations

import os
import time
from urllib.parse import quote

import httpx

DEFAULT_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
MAX_REQUESTS_PER_SEC = 5.0
MAX_REQUESTS_PER_MIN = 400.0


class PubChemError(RuntimeError):
    pass


class TokenBucket:
    """Limiter satisfying ≤5 req/s and ≤400 req/min without waiting for 429s."""

    def __init__(
        self,
        rate_per_sec: float = MAX_REQUESTS_PER_SEC,
        capacity: float | None = None,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self.rate = min(rate_per_sec, MAX_REQUESTS_PER_MIN / 60.0)
        self.capacity = capacity if capacity is not None else self.rate
        self._tokens = self.capacity
        self._clock = clock
        self._sleeper = sleeper
        self._updated = clock()

    def acquire(self) -> None:
        while True:
            now = self._clock()
            elapsed = max(0.0, now - self._updated)
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._updated = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self.rate
            self._sleeper(wait)


class PubChemClient:
    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        limiter: TokenBucket | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("PUBCHEM_API_BASE") or DEFAULT_PUBCHEM_BASE
        ).rstrip("/")
        self._client = client
        self.limiter = limiter or TokenBucket()

    def fetch_smiles(self, drug_name: str) -> str:
        self.limiter.acquire()
        path = f"/compound/name/{quote(drug_name)}/property/CanonicalSMILES/TXT"
        url = f"{self.base_url}{path}"
        try:
            if self._client is not None:
                response = self._client.get(url, timeout=40.0)
            else:
                response = httpx.get(url, timeout=40.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PubChemError(f"PubChem request failed for {drug_name}") from exc
        smiles = response.text.strip()
        if not smiles or smiles.lower().startswith("<"):
            raise PubChemError(f"PubChem returned no Canonical SMILES for {drug_name}")
        return smiles
