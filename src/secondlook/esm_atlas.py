"""ESM Atlas fold API — fallback only, never on the live demo path."""

from __future__ import annotations

import os

import httpx

DEFAULT_ESM_FOLD_URL = "https://api.esmatlas.com/foldSequence/v1/pdb/"
DEFAULT_TIMEOUT_SECONDS = 30.0


class EsmAtlasError(RuntimeError):
    pass


class EsmAtlasClient:
    def __init__(
        self,
        url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url or os.environ.get("ESM_ATLAS_FOLD_URL") or DEFAULT_ESM_FOLD_URL
        self.timeout = timeout
        self._client = client

    def fold_sequence(self, sequence: str) -> str:
        headers = {"Content-Type": "text/plain"}
        try:
            if self._client is not None:
                response = self._client.post(
                    self.url, content=sequence.encode(), headers=headers, timeout=self.timeout
                )
            else:
                response = httpx.post(
                    self.url,
                    content=sequence.encode(),
                    headers=headers,
                    timeout=self.timeout,
                    follow_redirects=True,
                )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"ESM Atlas fold timed out after {self.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise EsmAtlasError(f"ESM Atlas fold failed for {self.url}") from exc
        if not response.text.strip().startswith(("HEADER", "ATOM", "MODEL", "TITLE")):
            raise EsmAtlasError("ESM Atlas did not return a PDB structure")
        return response.text
