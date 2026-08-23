"""Load ClinicalTrials.gov v2 records into the Tier 1 knowledge graph.

Closes `ISSUES.md` #5 (no trial source) and populates the `Trial` nodes the
Eligibility Matcher reads.

Follows civic_loader.py's discipline: config-driven scope, idempotent MERGE
writes, every dropped record counted by reason and returned in a structured
summary rather than only logged.

Two things this loader does NOT do, deliberately:

* **It does not interpret eligibility text.** The raw `eligibilityCriteria`
  string is stored verbatim. Turning it into predicates is a separate, cached,
  spot-checked step (criteria_extraction.py) -- keeping them apart means the
  extractor can be re-run and re-validated against a fixed corpus, rather than
  against a registry that edits its own records underneath it.

* **It does not decide whether a patient matches.** Nothing here reads a case.

Run:
    python -m secondlook.tier1.ctgov_loader
    python -m secondlook.tier1.ctgov_loader --dry-run
    python -m secondlook.tier1.ctgov_loader --condition "Ewing Sarcoma"
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from secondlook.tier1.graph_schema import TRIAL_STATUSES, with_provenance

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "trials_scope.yaml"
CIVIC_SCOPE_PATH = Path(__file__).parent / "config" / "civic_scope.yaml"
SOURCE_NAME = "ClinicalTrials.gov"
REQUEST_TIMEOUT_SECONDS = 60.0


class CtgovApiError(RuntimeError):
    """ClinicalTrials.gov was unreachable or returned an unusable payload."""


@dataclass
class LoadSummary:
    """What one load did, including everything it refused and why."""

    conditions_queried: int = 0
    studies_seen: int = 0
    trials_written: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    #: Registry statuses seen that are not in TRIAL_STATUSES. Recorded rather
    #: than mapped to UNKNOWN: an unrecognised status means the registry
    #: changed its vocabulary, and that is a fact someone needs to act on.
    unmapped_statuses: dict[str, int] = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def render(self) -> str:
        lines = [
            f"conditions queried : {self.conditions_queried}",
            f"studies seen       : {self.studies_seen}",
            f"trials written     : {self.trials_written}",
        ]
        if self.dropped:
            lines.append("dropped:")
            lines += [f"  {reason}: {n}" for reason, n in sorted(self.dropped.items())]
        if self.unmapped_statuses:
            lines.append("UNMAPPED STATUSES (registry vocabulary may have changed):")
            lines += [f"  {s}: {n}" for s, n in sorted(self.unmapped_statuses.items())]
        return "\n".join(lines)


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise CtgovApiError(f"trials scope config not found: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CtgovApiError(f"could not parse {path}: {exc}") from exc


def scope_conditions(
    config: dict | None = None, civic_scope_path: Path = CIVIC_SCOPE_PATH
) -> list[str]:
    """Query terms, derived from civic_scope.yaml plus configured synonyms.

    Derived rather than duplicated so the trial scope cannot silently diverge
    from the evidence scope.
    """
    config = config if config is not None else load_config()
    if not civic_scope_path.exists():
        raise CtgovApiError(f"civic scope not found: {civic_scope_path}")
    try:
        civic = yaml.safe_load(civic_scope_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CtgovApiError(f"could not parse {civic_scope_path}: {exc}") from exc

    synonyms = config.get("synonyms") or {}
    terms: list[str] = []
    for disease in civic.get("diseases") or []:
        name = (disease or {}).get("name")
        if not name:
            continue
        terms.append(str(name))
        for extra in synonyms.get(str(disease.get("doid")), []) or []:
            terms.append(str(extra))
    # Stable order, no duplicates -- a re-run must query the same terms in the
    # same order so two runs are comparable.
    seen: set[str] = set()
    return [t for t in terms if not (t.lower() in seen or seen.add(t.lower()))]


def fetch_studies(
    condition: str,
    *,
    config: dict,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Every study for one condition, following pageToken to exhaustion."""
    owns_client = client is None
    client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
    api = config.get("api_base") or "https://clinicaltrials.gov/api/v2/studies"
    page_size = int(config.get("page_size") or 100)
    max_pages = int(config.get("max_pages_per_condition") or 20)
    pause = float(config.get("pause_seconds_between_requests") or 0.0)

    studies: list[dict] = []
    token: str | None = None
    try:
        for page in range(max_pages):
            params: dict[str, Any] = {
                "query.cond": condition,
                "pageSize": page_size,
                "format": "json",
            }
            if token:
                params["pageToken"] = token
            try:
                response = client.get(api, params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as exc:
                raise CtgovApiError(f"request failed for {condition!r}: {exc}") from exc
            except ValueError as exc:
                raise CtgovApiError(f"non-JSON response for {condition!r}: {exc}") from exc

            batch = payload.get("studies")
            if batch is None:
                raise CtgovApiError(
                    f"response for {condition!r} has no 'studies' key -- API shape changed"
                )
            studies.extend(batch)
            token = payload.get("nextPageToken")
            if not token:
                break
            if pause:
                time.sleep(pause)
        else:
            logger.warning(
                "hit max_pages_per_condition=%s for %r; results may be truncated",
                max_pages, condition,
            )
    finally:
        if owns_client:
            client.close()
    return studies


def parse_study(study: dict, summary: LoadSummary) -> dict | None:
    """One API record to Trial node properties, or None with a counted reason."""
    section = study.get("protocolSection") or {}
    ident = section.get("identificationModule") or {}
    status_mod = section.get("statusModule") or {}
    design = section.get("designModule") or {}
    conditions_mod = section.get("conditionsModule") or {}
    eligibility = section.get("eligibilityModule") or {}
    locations_mod = section.get("contactsLocationsModule") or {}

    nct_id = ident.get("nctId")
    if not nct_id:
        summary.drop("no nctId")
        return None

    status = status_mod.get("overallStatus")
    if not status:
        summary.drop("no overallStatus")
        return None
    if status not in TRIAL_STATUSES:
        # Counted, and the record is still dropped. Storing an unrecognised
        # status would let it reach a matcher with no rule for it; guessing a
        # mapping would be worse.
        summary.unmapped_statuses[status] = summary.unmapped_statuses.get(status, 0) + 1
        summary.drop(f"unmapped status {status}")
        return None

    criteria = eligibility.get("eligibilityCriteria")
    if not criteria:
        # Kept as a drop rather than a node with empty criteria: the matcher's
        # whole job is evaluating criteria, and a trial with none would bucket
        # as `highly_compatible` for everyone, which is the worst failure mode
        # available to it.
        summary.drop("no eligibilityCriteria")
        return None

    locations = locations_mod.get("locations") or []
    countries = sorted({loc.get("country") for loc in locations if loc.get("country")})
    facilities = [
        ", ".join(part for part in (loc.get("facility"), loc.get("city"), loc.get("country")) if part)
        for loc in locations
    ]
    phases = design.get("phases") or []

    return {
        "registry_id": nct_id,
        "registry": SOURCE_NAME,
        "status": status,
        "phase": ", ".join(phases) if phases else None,
        "study_type": design.get("studyType"),
        "brief_title": ident.get("briefTitle"),
        "conditions": conditions_mod.get("conditions") or [],
        "eligibility_criteria": criteria,
        "eligibility_url": f"https://clinicaltrials.gov/study/{nct_id}",
        "minimum_age": eligibility.get("minimumAge"),
        "maximum_age": eligibility.get("maximumAge"),
        "sex": eligibility.get("sex"),
        "locations": facilities,
        "country_codes": countries,
        "has_expanded_access": bool(
            (status_mod.get("expandedAccessInfo") or {}).get("hasExpandedAccess")
        ),
        "last_update_posted": (status_mod.get("lastUpdatePostDateStruct") or {}).get("date"),
    }


def _merge_trial(graph, properties: dict) -> None:
    """Idempotent write keyed on registry_id. MERGE, never CREATE."""
    graph.query(
        "MERGE (t:Trial {registry_id: $key}) SET t += $props",
        params={"key": properties["registry_id"], "props": properties},
    )


def run_load(
    graph,
    config: dict | None = None,
    *,
    dry_run: bool = False,
    only_condition: str | None = None,
    client: httpx.Client | None = None,
) -> LoadSummary:
    config = config if config is not None else load_config()
    summary = LoadSummary()
    retrieved_at = datetime.now(UTC).isoformat()
    source_version = str(config.get("config_version") or "unversioned")

    conditions = [only_condition] if only_condition else scope_conditions(config)
    seen_ids: set[str] = set()

    for condition in conditions:
        summary.conditions_queried += 1
        studies = fetch_studies(condition, config=config, client=client)
        logger.info("%s: %d studies", condition, len(studies))
        for study in studies:
            summary.studies_seen += 1
            properties = parse_study(study, summary)
            if properties is None:
                continue
            # The same trial legitimately matches several scope terms.
            if properties["registry_id"] in seen_ids:
                summary.drop("duplicate across conditions")
                continue
            seen_ids.add(properties["registry_id"])
            if dry_run:
                summary.trials_written += 1
                continue
            _merge_trial(
                graph,
                with_provenance(properties, SOURCE_NAME, retrieved_at, source_version),
            )
            summary.trials_written += 1
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fetch and parse, do not write")
    parser.add_argument("--condition", help="query one condition instead of the whole scope")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    graph = None
    if not args.dry_run:
        from secondlook.tier1.graph_connection import connect_graph

        graph = connect_graph()
    summary = run_load(graph, dry_run=args.dry_run, only_condition=args.condition)
    print(summary.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
