"""mCSM-lig submission via Playwright — drives the live HTML form, does not
replay a guessed POST."""

from __future__ import annotations

import re
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from secondlook.binding import (
    McsmLigResult,
    McsmPageError,
    McsmParseError,
    McsmTimeoutError,
    parse_mcsm_result,
)

PREDICTION_URL = "https://biosig.lab.uq.edu.au/mcsm_lig/prediction"
DEFAULT_TIMEOUT_MS = 180_000
PROCESS_POLL_MS = 30_000
# The live form rejects blank/zero: "Wild-type affinity value must be greater than zero."
# Example page uses 0.270 nM. Predicted log(fold change) is the delta we report;
# this placeholder only satisfies the required field when no experimental WT nM is known.
DEFAULT_WILDTYPE_AFFINITY_NM = 1.0

_ERROR_TEXT = re.compile(
    r"alert-error.*?</h4>\s*(.*?)\s*(?:<a |</div>)",
    re.IGNORECASE | re.DOTALL,
)


class McsmLigPlaywrightClient:
    def __init__(
        self,
        page_factory: Callable[[], object] | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._page_factory = page_factory
        self.timeout_ms = timeout_ms

    def submit(
        self,
        *,
        pdb_code: str | None,
        pdb_text: str | None,
        mutation: str,
        chain: str,
        lig_id: str,
        wildtype_affinity_nm: float | None = None,
    ) -> McsmLigResult:
        with self._page() as page:
            try:
                page.goto(PREDICTION_URL, timeout=self.timeout_ms, wait_until="domcontentloaded")
            except Exception as exc:
                raise McsmPageError(f"Cannot reach mCSM-lig prediction page: {exc}") from exc

            try:
                self._fill_form(
                    page,
                    pdb_code=pdb_code,
                    pdb_text=pdb_text,
                    mutation=mutation,
                    chain=chain,
                    lig_id=lig_id,
                    wildtype_affinity_nm=wildtype_affinity_nm,
                )
                self._click_single(page)
                self._wait_for_result(page)
            except (McsmPageError, McsmTimeoutError):
                raise
            except Exception as exc:
                if _is_timeout(exc):
                    raise McsmTimeoutError("mCSM-lig form submission timed out") from exc
                raise McsmPageError(f"mCSM-lig page/form interaction failed: {exc}") from exc

            try:
                return parse_mcsm_result(page.content())
            except McsmParseError:
                raise

    def submit_example(self) -> McsmLigResult:
        """Drive the site's Run example control (2Z4O / D30N / chain A / ligand 065)."""
        with self._page() as page:
            try:
                page.goto(PREDICTION_URL, timeout=self.timeout_ms, wait_until="domcontentloaded")
            except Exception as exc:
                raise McsmPageError(f"Cannot reach mCSM-lig prediction page: {exc}") from exc
            try:
                _require(
                    page,
                    'form[action="/mcsm_lig/run_example"] button[type="submit"]',
                    "Run example",
                )
                page.locator('form[action="/mcsm_lig/run_example"] button[type="submit"]').click()
                self._wait_for_result(page)
            except (McsmPageError, McsmTimeoutError):
                raise
            except Exception as exc:
                if _is_timeout(exc):
                    raise McsmTimeoutError("mCSM-lig form submission timed out") from exc
                raise McsmPageError(f"mCSM-lig page/form interaction failed: {exc}") from exc
            return parse_mcsm_result(page.content())

    def _fill_form(
        self,
        page,
        *,
        pdb_code: str | None,
        pdb_text: str | None,
        mutation: str,
        chain: str,
        lig_id: str,
        wildtype_affinity_nm: float | None,
    ) -> None:
        if pdb_code:
            _require(page, '[name="pdb_code"]', "pdb_code")
            _fill(page, "pdb_code", pdb_code)
        elif pdb_text:
            _require(page, '[name="wild"]', "wild")
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pdb", delete=False) as handle:
                handle.write(pdb_text)
                path = handle.name
            try:
                page.set_input_files('[name="wild"]', path)
            finally:
                Path(path).unlink(missing_ok=True)
        else:
            raise McsmPageError("mCSM-lig submission needs a PDB code or PDB file contents")
        _require(page, '[name="mutation"]', "mutation")
        _require(page, '[name="chain"]', "chain")
        _require(page, '[name="lig_id"]', "lig_id")
        _require(page, '[name="affin_wt"]', "affin_wt")
        _fill(page, "mutation", mutation)
        _fill(page, "chain", chain)
        _fill(page, "lig_id", lig_id)
        affinity = (
            DEFAULT_WILDTYPE_AFFINITY_NM if wildtype_affinity_nm is None else wildtype_affinity_nm
        )
        if affinity <= 0:
            raise McsmPageError("mCSM-lig wild-type affinity must be greater than zero")
        _fill(page, "affin_wt", str(affinity))

    def _click_single(self, page) -> None:
        _require(page, '[name="run"][value="single"]', "run=single")
        page.locator('[name="run"][value="single"]').click()

    def _wait_for_result(self, page) -> None:
        deadline = time.monotonic() + self.timeout_ms / 1000
        while True:
            html = page.content()
            if "Predicted Affinity Change" in html:
                return
            if "alert-error" in html:
                raise McsmPageError(_form_error_message(html))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McsmTimeoutError("mCSM-lig form submission timed out")
            wait_ms = min(PROCESS_POLL_MS, max(1, int(remaining * 1000)))
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(wait_ms)
            else:
                time.sleep(wait_ms / 1000)
            if hasattr(page, "reload"):
                page.reload(wait_until="domcontentloaded")

    @contextmanager
    def _page(self) -> Iterator[object]:
        if self._page_factory is not None:
            yield self._page_factory()
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise McsmPageError("Playwright is not installed") from exc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                yield page
            finally:
                browser.close()


def _fill(page, name: str, value: str) -> None:
    page.fill(f'[name="{name}"]', value)


def _require(page, selector: str, label: str) -> None:
    locator = page.locator(selector)
    count = getattr(locator, "count", None)
    if callable(count) and count() == 0:
        raise McsmPageError(f"mCSM-lig page missing {label} ({selector})")


def _form_error_message(html: str) -> str:
    match = _ERROR_TEXT.search(html)
    if match:
        text = re.sub(r"<[^>]+>", " ", match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return f"mCSM-lig rejected the submission: {text}"
    return "mCSM-lig rejected the submission"


def _is_timeout(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    return "timeout" in name or "timeout" in str(exc).lower()
