"""Load curated regulatory access pathways into the Tier 1 graph.

Subsystem J. Curated YAML, never scraped -- every entry is a regulatory claim a
clinician may act on, so it carries the instrument it rests on and a URL a
reader can check.

The shape verification here is stricter than the other loaders', because the
failure mode is worse. A malformed CIViC record produces a missing evidence
item. A malformed access pathway produces a confident, citable-looking claim
that a legal route exists when it does not.

Three rules are enforced at load time and will refuse a file rather than write
a doubtful node:

1. **Every pathway cites an instrument and a source URL.** A route without a
   citation is not usable by the person who has to file the application.

2. **`precedent_strength: granted_before` requires at least one
   `precedent_examples` entry.** This is the distinction the issue calls out:
   "expanded access has been granted for this agent before" is a materially
   different claim from "a pathway theoretically exists". Allowing the stronger
   claim without evidence would make the two indistinguishable in exactly the
   way the issue forbids.

3. **`review_status` travels onto every node.** The seed files are transcribed,
   not verified by anyone with regulatory-affairs training. A consumer must be
   able to tell reviewed guidance from unreviewed, and the default is
   unreviewed.

Run:
    python -m secondlook.tier1.access_pathway_loader --verify
    python -m secondlook.tier1.access_pathway_loader
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from secondlook.tier1.graph_schema import (
    PATHWAY_TYPES,
    PRECEDENT_STRENGTHS,
    assert_valid,
    with_provenance,
)

logger = logging.getLogger(__name__)

#: Repo-root `access_pathways/`, not under `tier1/config/`. This is curation
#: data owned by the Access Pathway Registry subsystem, and the build plan gives
#: each subsystem its own top-level directory precisely so two subsystems'
#: changes cannot collide in a shared tree.
PATHWAYS_DIR = Path(__file__).resolve().parents[3] / "access_pathways"
SOURCE_NAME = "curated"

#: A pathway carrying this has not been checked against the primary source by a
#: person with regulatory-affairs familiarity. Surfaced on every node.
UNREVIEWED = "unreviewed"


class AccessPathwayConfigError(RuntimeError):
    """A seed file is missing, malformed, or makes an unsupported claim."""


@dataclass
class PathwayLoadSummary:
    files_read: int = 0
    pathways_written: int = 0
    unreviewed: int = 0
    rejected: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"files read        : {self.files_read}",
            f"pathways written  : {self.pathways_written}",
            f"unreviewed        : {self.unreviewed}",
        ]
        if self.rejected:
            lines.append("REJECTED:")
            lines += [f"  {r}" for r in self.rejected]
        if self.unreviewed:
            lines.append(
                "\nNote: unreviewed entries are transcribed but not verified against the "
                "primary source. They must not be presented as settled guidance."
            )
        return "\n".join(lines)


def pathway_id(country: str, pathway_type: str, instrument: str) -> str:
    """Stable key so re-loading updates rather than duplicating.

    Includes the instrument: one country can offer the same pathway_type under
    two different legal instruments, and collapsing them would silently drop one.
    """
    return f"{country}:{pathway_type}:{instrument}"


def validate_pathway(entry: dict, *, country: str, path: Path | None = None) -> dict:
    """Return normalised properties, or raise with a specific reason.

    `path` only names the file in the error message. It is optional so this can
    be called on a single entry -- from a test, or from a review tool checking
    one proposed pathway before it is added to a seed file.
    """
    where = path.name if path is not None else f"<{country} pathway>"

    for required in ("pathway_type", "instrument", "description", "source_url"):
        value = entry.get(required)
        if not value or not str(value).strip():
            raise AccessPathwayConfigError(
                f"{where}: pathway missing required field {required!r} -- "
                "an access route without a citation is not actionable"
            )

    pathway_type = str(entry["pathway_type"])
    assert_valid(pathway_type, PATHWAY_TYPES, "pathway_type")

    strength = str(entry.get("precedent_strength") or "theoretical")
    assert_valid(strength, PRECEDENT_STRENGTHS, "precedent_strength")

    examples = entry.get("precedent_examples") or []
    if not isinstance(examples, list):
        raise AccessPathwayConfigError(f"{where}: precedent_examples must be a list")
    if strength == "granted_before" and not examples:
        raise AccessPathwayConfigError(
            f"{where}: pathway {pathway_type!r} claims precedent_strength="
            "'granted_before' with no precedent_examples. That claim asserts a "
            "grant has actually happened; it needs at least one citable case."
        )

    return {
        "pathway_type": pathway_type,
        "instrument": str(entry["instrument"]).strip(),
        "description": " ".join(str(entry["description"]).split()),
        "source_url": str(entry["source_url"]).strip(),
        "precedent_strength": strength,
        "precedent_examples": [str(e) for e in examples],
    }


def read_seed_file(path: Path) -> tuple[dict, list[dict]]:
    """(file-level fields, validated pathways). Raises on any malformed entry."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AccessPathwayConfigError(f"could not parse {path}: {exc}") from exc

    country = raw.get("country")
    regulator = raw.get("regulator")
    if not country or not regulator:
        raise AccessPathwayConfigError(f"{path.name}: needs both `country` and `regulator`")

    entries = raw.get("pathways")
    if not isinstance(entries, list) or not entries:
        raise AccessPathwayConfigError(f"{path.name}: declares no pathways")

    header = {
        "country": str(country),
        "regulator": str(regulator),
        "config_version": str(raw.get("config_version") or "unversioned"),
        "review_status": str(raw.get("review_status") or UNREVIEWED),
    }
    return header, [validate_pathway(e, country=header["country"], path=path) for e in entries]


def _merge_pathway(graph, properties: dict) -> None:
    graph.query(
        "MERGE (p:AccessPathway {pathway_id: $key}) SET p += $props",
        params={"key": properties["pathway_id"], "props": properties},
    )


def run_load(
    graph,
    *,
    pathways_dir: Path = PATHWAYS_DIR,
    dry_run: bool = False,
) -> PathwayLoadSummary:
    summary = PathwayLoadSummary()
    retrieved_at = datetime.now(UTC).isoformat()

    if not pathways_dir.is_dir():
        raise AccessPathwayConfigError(f"no access-pathway directory at {pathways_dir}")

    for path in sorted(pathways_dir.glob("*.yaml")):
        try:
            header, pathways = read_seed_file(path)
        except (AccessPathwayConfigError, ValueError) as exc:
            # Rejected files are reported and skipped, never partially loaded --
            # a half-loaded country is worse than an absent one.
            summary.rejected.append(str(exc))
            continue

        summary.files_read += 1
        for pathway in pathways:
            properties = {
                **pathway,
                "country": header["country"],
                "regulator": header["regulator"],
                "config_version": header["config_version"],
                "review_status": header["review_status"],
                "pathway_id": pathway_id(
                    header["country"], pathway["pathway_type"], pathway["instrument"]
                ),
            }
            if header["review_status"] == UNREVIEWED:
                summary.unreviewed += 1
            if not dry_run:
                _merge_pathway(
                    graph,
                    with_provenance(
                        properties, SOURCE_NAME, retrieved_at, header["config_version"]
                    ),
                )
            summary.pathways_written += 1
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="validate seeds, do not write")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    graph = None
    if not args.verify:
        from secondlook.tier1.graph_connection import connect_graph

        graph = connect_graph()
    summary = run_load(graph, dry_run=args.verify)
    print(summary.render())
    return 1 if summary.rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
