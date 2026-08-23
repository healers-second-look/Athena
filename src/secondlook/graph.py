"""Graph-ready `StructuralSignal` emission (Tier 2 side of the §4 contract).

Implements `tier2-implementation-spec.md` §4 / `tier1-implementation-spec.md`
§3.4. Tier 2 *builds* these objects; Tier 1 persists them. Nothing here talks to
FalkorDB, and no `falkordb` dependency is introduced — see `tier1.GraphSink`.

Target shape in the graph::

    (Variant)-[:HAS_COMPUTATIONAL_SIGNAL]->(StructuralSignal)
    (StructuralSignal)-[:PREDICTS_BINDING_CHANGE {delta_score, label, method}]->(Drug)

## Two rules this module enforces structurally

**A `StructuralSignal` is never an `EvidenceItem`.** Separate node label,
separate edge type, no shared parent class. `ui-flow.md` requires computed and
documented results to render as visually distinct sections and `architecture.md`
forbids conflating them, so the distinction is kept impossible to blur rather
than merely documented. Note the deliberate absence of a `citation_url` field —
a `StructuralSignal` has a *method*, not a citation, and giving it a
citation-shaped field is exactly how the two would start to look alike.

**`computed_at` and `pipeline_version` are mandatory.** A structural signal is a
point-in-time computation against external databases that change underneath it.
Without provenance a cached six-month-old signal is indistinguishable from a
fresh one — the precise failure that made RareCure's published metrics
unreproducible from its own committed artifacts (`rarecure-build-reference.md`
§4: no retrieval timestamp or data version recorded anywhere).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

#: Bump on any change to what the pipeline computes or how it assembles output.
#: Recorded on every emitted signal, and used by the validation harness to treat
#: older cached runs as stale rather than silently reusing them.
#:
#: 0.2.0 — audit fixes: covalent mechanism gate, InChIKey ligand identity
#: (replacing name/HET substring matching), restrained post-mutation
#: minimization, native-pose docking control, Vina exhaustiveness 8 -> 32.
#: All five change the computed numbers, so 0.1.0 results are not comparable.
PIPELINE_VERSION = "0.2.0"

#: Node label and edge types, named once so Tier 1's loader and Tier 2's emitter
#: cannot drift apart on a typo.
STRUCTURAL_SIGNAL_LABEL = "StructuralSignal"
HAS_COMPUTATIONAL_SIGNAL_EDGE = "HAS_COMPUTATIONAL_SIGNAL"
PREDICTS_BINDING_CHANGE_EDGE = "PREDICTS_BINDING_CHANGE"


def utc_now_iso() -> str:
    """Timezone-aware ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class StructuralSignal:
    """One computed binding signal for a (variant, drug) pair.

    Deliberately standalone — see the module docstring on why this shares no
    parent class with any documented-evidence type.
    """

    # --- identity of what was analyzed -------------------------------------
    gene: str
    hgvs_p: str
    drug: str

    # --- computed signal ----------------------------------------------------
    alphamissense_score: float | None
    alphamissense_class: str | None
    structure_source: Literal["PDB", "AlphaFoldDB", "ESMAtlas"] | None
    structure_id: str | None
    plddt_at_residue: float | None
    reliability_flag: Literal["high", "low"] | None
    method: Literal["mCSM-lig", "docking"] | None
    delta_score: float | None
    label: str | None
    binding_site_distance_angstrom: float | None

    # --- honesty metadata ---------------------------------------------------
    confidence: str | None
    calibration_status: str | None

    # --- provenance (mandatory, see module docstring) ------------------------
    computed_at: str
    pipeline_version: str
    labeling_version: str | None

    def edge_properties(self) -> dict:
        """Properties for the `PREDICTS_BINDING_CHANGE` edge to the `Drug` node."""
        return {
            "delta_score": self.delta_score,
            "label": self.label,
            "method": self.method,
            "confidence": self.confidence,
            "calibration_status": self.calibration_status,
            "computed_at": self.computed_at,
            "pipeline_version": self.pipeline_version,
        }

    def node_properties(self) -> dict:
        """Properties for the `StructuralSignal` node itself."""
        return {
            "alphamissense_score": self.alphamissense_score,
            "alphamissense_class": self.alphamissense_class,
            "structure_source": self.structure_source,
            "structure_id": self.structure_id,
            "plddt_at_residue": self.plddt_at_residue,
            "reliability_flag": self.reliability_flag,
            "method": self.method,
            "binding_site_distance_angstrom": self.binding_site_distance_angstrom,
            "confidence": self.confidence,
            "calibration_status": self.calibration_status,
            "computed_at": self.computed_at,
            "pipeline_version": self.pipeline_version,
            "labeling_version": self.labeling_version,
        }
