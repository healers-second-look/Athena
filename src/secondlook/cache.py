"""Serialization and on-disk caching of pipeline output (Step 7 support).

Two jobs, one format:

**Demo-case caching** (`tier2-implementation-spec.md` §5 deliverable 4). The live
demo must never depend on external API latency or uptime — mCSM-lig is a shared
academic server and docking is real compute. Cached payloads carry an explicit
``cached: true`` marker plus the timestamp of the run that produced them, because
`ui-flow.md` Screen 3 requires cached results be *shown* as cached, never passed
off as live.

**Cheap threshold sweeps.** The gold-standard validation run is expensive (nine
cases, most candidates needing a real dock). Re-running it for every candidate
cutoff would be untenable, so the cache stores the raw `delta_score` and `method`
per candidate. Sweeping a cutoff then means re-labeling cached deltas — no
network, no docking. This is why `relabel_payload` exists.

`pdb_text` is deliberately excluded: it is megabytes of structure data, is not
part of the `api-contracts.md` wire shape, and is recoverable from `structure.id`.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from secondlook.graph import PIPELINE_VERSION
from secondlook.labeling import (
    MethodCalibration,
    ScoringMethod,
    label_binding_delta,
)
from secondlook.pipeline import Tier2Output, mutation_validated_payload

#: Where demo/validation payloads live unless a caller says otherwise.
DEFAULT_CACHE_DIR = Path("validation/cache")


def cache_key(gene: str, mutation: str) -> str:
    """Filesystem-safe key for one case."""
    return f"{gene.strip().upper()}_{mutation.strip().replace('.', '').upper()}"


def to_payload(output: Tier2Output, *, gene: str, mutation: str) -> dict[str, Any]:
    """Serialize a `Tier2Output` into a JSON-safe wire payload.

    Includes raw `delta_score`/`method` per result so a cached run can be
    re-labeled under a different cutoff without recomputation.
    """
    structure = None
    if output.structure is not None:
        structure = asdict(output.structure)
        # Excluded on purpose — see module docstring.
        structure.pop("pdb_text", None)

    # Same contract shape the result items use — full-length sequences are large,
    # not part of api-contracts.md, and derivable from the accession.
    validation = (
        mutation_validated_payload(output.validation) if output.validation is not None else None
    )

    return {
        "gene": gene,
        "mutation": mutation,
        "status": output.status,
        "computed_at": output.computed_at,
        "pipeline_version": output.pipeline_version,
        "cached": False,
        "results": [item.to_dict() for item in output.results],
        "failures": [failure.to_dict() for failure in output.failures],
        "signals": [
            {"gene": s.gene, "hgvs_p": s.hgvs_p, "drug": s.drug, **s.node_properties()}
            for s in output.signals
        ],
        "alphamissense": (
            asdict(output.alphamissense) if output.alphamissense is not None else None
        ),
        "validation": validation,
        "structure": structure,
        "scored_by_method": output.scored_by_method,
    }


def save_payload(payload: dict[str, Any], *, cache_dir: Path | str = DEFAULT_CACHE_DIR) -> Path:
    """Write a payload to `<cache_dir>/<gene>_<mutation>.json`."""
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cache_key(payload['gene'], payload['mutation'])}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def load_payload(
    gene: str, mutation: str, *, cache_dir: Path | str = DEFAULT_CACHE_DIR
) -> dict[str, Any] | None:
    """Read a cached payload, marked as cached. Returns None if absent.

    The `cached` flag is set on read rather than trusted from disk, so a payload
    served from cache can never be rendered as live — `ui-flow.md` Screen 3
    requires the indicator be shown, not hidden.
    """
    path = Path(cache_dir) / f"{cache_key(gene, mutation)}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    payload["cached"] = True
    payload["cache_source"] = str(path)
    return payload


def relabel_payload(
    payload: dict[str, Any],
    calibrations: dict[ScoringMethod, MethodCalibration],
) -> dict[str, Any]:
    """Re-label a cached payload's results under different thresholds.

    The whole point of caching raw deltas: sweeping a cutoff costs no network
    calls and no docking. Returns a new payload; the input is not mutated.
    """
    relabeled = json.loads(json.dumps(payload))
    for item in relabeled.get("results", []):
        method = item.get("method")
        delta = item.get("delta_score")
        if method is None or delta is None:
            continue
        calibration = calibrations.get(method)
        result = label_binding_delta(float(delta), method, calibration=calibration)
        item["label"] = result.label
        item["confidence"] = result.confidence
        item["calibration_status"] = result.calibration_status
        item["heuristic_note"] = result.heuristic_note
        item["delta_score_unit"] = result.unit
    return relabeled


def cache_case(
    output: Tier2Output,
    *,
    gene: str,
    mutation: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> Path:
    """Serialize and store one case in a single call."""
    return save_payload(to_payload(output, gene=gene, mutation=mutation), cache_dir=cache_dir)


def payload_is_stale(payload: dict[str, Any]) -> bool:
    """True when a cached payload came from a different pipeline version.

    A cached signal from an older pipeline is not interchangeable with a fresh
    one — the provenance requirement in `graph.py` exists for exactly this.
    """
    return payload.get("pipeline_version") != PIPELINE_VERSION
