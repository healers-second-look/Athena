"""Fold a `CaseState` into a typed patient subgraph *plan*.

Postgres remains the source of truth; this module never talks to it, and
never talks to FalkorDB. It only describes the nodes and edges a writer
would persist as a derived, rebuildable index of one case.

The patient labels here are a separate epistemic class from the world
evidence graph (`:Gene`, `:Variant`, `:Disease`, `:Drug`, `:EvidenceItem`).
They share no parent type, and they carry no field shaped like a citation
(`citation_url`, `pmid`, `civic_id`, `source_url`, `evidence_level`).
`source_event_id` points at a Postgres event — provenance, not a paper.
See `ARCHITECTURE.md` §5 and `graph.py`'s documented/computed split.

Bridge edges into the world (`INSTANCE_OF`, `USES`, `DIAGNOSED_WITH`) are
*intent* in this plan. Matching them against live world nodes is I/O, so
it lives in `projection_writer.py`. This module must stay offline-testable
exactly like `case/diff.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from secondlook.case.state import CaseState

# ---------------------------------------------------------------------------
# Patient-side schema. Intentionally *not* in tier1/graph_schema.py — that
# module is the world evidence spine. A patient record is not published
# evidence, and putting these labels on ALL_NODE_TYPES would let the two
# classes be queried as if they were the same kind of thing.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeType:
    """A patient-graph node label plus its declared property names."""

    label: str
    properties: tuple[str, ...]


CASE = NodeType(
    "Case",
    ("case_id", "cancer_type", "primary_site", "histology", "stage"),
)
OBSERVED_ALTERATION = NodeType(
    "ObservedAlteration",
    (
        "case_id",
        "gene_symbol",
        "variant",
        "variant_type",
        "assay",
        "tested_on",
        "source_event_id",
    ),
)
TREATMENT_LINE = NodeType(
    "TreatmentLine",
    ("case_id", "regimen", "line", "action", "reason", "source_event_id"),
)
DISEASE_ASSESSMENT = NodeType(
    "DiseaseAssessment",
    ("case_id", "status", "sites", "assessed_on", "source_event_id"),
)
CLINICAL_QUESTION = NodeType(
    "ClinicalQuestion",
    ("case_id", "text", "source_event_id"),
)
BIOMARKER_MEASUREMENT = NodeType(
    "BiomarkerMeasurement",
    ("case_id", "name", "value", "unit", "measured_on", "source_event_id"),
)

PATIENT_NODE_TYPES: tuple[NodeType, ...] = (
    CASE,
    OBSERVED_ALTERATION,
    TREATMENT_LINE,
    DISEASE_ASSESSMENT,
    CLINICAL_QUESTION,
    BIOMARKER_MEASUREMENT,
)

HAS_ALTERATION = "HAS_ALTERATION"
RECEIVED = "RECEIVED"
ASSESSED = "ASSESSED"
ASKED = "ASKED"
MEASURED = "MEASURED"
INSTANCE_OF = "INSTANCE_OF"
USES = "USES"
DIAGNOSED_WITH = "DIAGNOSED_WITH"

OWNERSHIP_REL_BY_LABEL: dict[str, str] = {
    OBSERVED_ALTERATION.label: HAS_ALTERATION,
    TREATMENT_LINE.label: RECEIVED,
    DISEASE_ASSESSMENT.label: ASSESSED,
    CLINICAL_QUESTION.label: ASKED,
    BIOMARKER_MEASUREMENT.label: MEASURED,
}

# CaseState.clinical_questions is text-only (fold drops the event id). The
# only stable handle left is fold order, so questions are keyed by index.
QUESTION_EVENT_PREFIX = "question:"


@dataclass(frozen=True)
class ProjectionNode:
    """One patient node in a plan. `properties` is a sorted tuple of pairs."""

    label: str
    key: str
    properties: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class ProjectionEdge:
    """An ownership edge or an intended MATCH-only bridge into the world."""

    rel_type: str
    from_key: str
    to_key: str
    kind: str  # "ownership" | "bridge"
    to_label: str
    match_property: str | None = None
    match_value: str | None = None
    extra: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class ProjectionPlan:
    case_id: str
    nodes: tuple[ProjectionNode, ...]
    edges: tuple[ProjectionEdge, ...]


def _props(mapping: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    frozen: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, list):
            frozen[key] = tuple(value)
        else:
            frozen[key] = value
    return tuple((k, frozen[k]) for k in sorted(frozen))


def _node(label: str, key: str, mapping: dict[str, Any]) -> ProjectionNode:
    return ProjectionNode(label=label, key=key, properties=_props(mapping))


def plan_projection(
    case_id: str,
    state: CaseState,
    *,
    cancer_type: str | None = None,
    primary_site: str | None = None,
    histology: str | None = None,
    stage: str | None = None,
) -> ProjectionPlan:
    """Pure. Deterministic. Same CaseState in -> byte-identical plan out."""

    nodes: list[ProjectionNode] = []
    edges: list[ProjectionEdge] = []

    case_key = f"case:{case_id}"
    nodes.append(
        _node(
            CASE.label,
            case_key,
            {
                "case_id": case_id,
                "cancer_type": cancer_type,
                "primary_site": primary_site,
                "histology": histology,
                "stage": stage,
            },
        )
    )

    for alt in state.alterations:
        key = f"alt:{alt.event_id}"
        nodes.append(
            _node(
                OBSERVED_ALTERATION.label,
                key,
                {
                    "case_id": case_id,
                    "gene_symbol": alt.gene,
                    "variant": alt.variant,
                    "variant_type": alt.variant_type,
                    "assay": alt.assay,
                    "tested_on": alt.tested_on,
                    "source_event_id": alt.event_id,
                },
            )
        )
        edges.append(
            ProjectionEdge(
                rel_type=HAS_ALTERATION,
                from_key=case_key,
                to_key=key,
                kind="ownership",
                to_label=OBSERVED_ALTERATION.label,
            )
        )
        edges.append(
            ProjectionEdge(
                rel_type=INSTANCE_OF,
                from_key=key,
                to_key=f"world:Variant:{alt.gene}:{alt.variant}",
                kind="bridge",
                to_label="Variant",
                match_property="variant",
                match_value=alt.variant,
                extra=_props({"gene_symbol": alt.gene, "source_event_id": alt.event_id}),
            )
        )

    for treatment in state.treatments:
        key = f"tx:{treatment.event_id}"
        nodes.append(
            _node(
                TREATMENT_LINE.label,
                key,
                {
                    "case_id": case_id,
                    "regimen": treatment.regimen,
                    "line": treatment.line,
                    "action": treatment.action,
                    "reason": treatment.reason,
                    "source_event_id": treatment.event_id,
                },
            )
        )
        edges.append(
            ProjectionEdge(
                rel_type=RECEIVED,
                from_key=case_key,
                to_key=key,
                kind="ownership",
                to_label=TREATMENT_LINE.label,
            )
        )
        edges.append(
            ProjectionEdge(
                rel_type=USES,
                from_key=key,
                to_key=f"world:Drug:{treatment.regimen}",
                kind="bridge",
                to_label="Drug",
                match_property="name",
                match_value=treatment.regimen,
                extra=_props({"source_event_id": treatment.event_id}),
            )
        )

    for assessment in state.assessments:
        key = f"assess:{assessment.event_id}"
        sites = tuple(assessment.sites) if assessment.sites is not None else None
        nodes.append(
            _node(
                DISEASE_ASSESSMENT.label,
                key,
                {
                    "case_id": case_id,
                    "status": assessment.status,
                    "sites": sites,
                    "assessed_on": assessment.assessed_on,
                    "source_event_id": assessment.event_id,
                },
            )
        )
        edges.append(
            ProjectionEdge(
                rel_type=ASSESSED,
                from_key=case_key,
                to_key=key,
                kind="ownership",
                to_label=DISEASE_ASSESSMENT.label,
            )
        )

    for index, text in enumerate(state.clinical_questions):
        source_event_id = f"{QUESTION_EVENT_PREFIX}{index}"
        key = f"q:{case_id}:{index}"
        nodes.append(
            _node(
                CLINICAL_QUESTION.label,
                key,
                {
                    "case_id": case_id,
                    "text": text,
                    "source_event_id": source_event_id,
                },
            )
        )
        edges.append(
            ProjectionEdge(
                rel_type=ASKED,
                from_key=case_key,
                to_key=key,
                kind="ownership",
                to_label=CLINICAL_QUESTION.label,
            )
        )

    for name in sorted(state.biomarkers):
        bio = state.biomarkers[name]
        key = f"bio:{bio.event_id}"
        nodes.append(
            _node(
                BIOMARKER_MEASUREMENT.label,
                key,
                {
                    "case_id": case_id,
                    "name": bio.name,
                    "value": bio.value,
                    "unit": bio.unit,
                    "measured_on": bio.measured_on,
                    "source_event_id": bio.event_id,
                },
            )
        )
        edges.append(
            ProjectionEdge(
                rel_type=MEASURED,
                from_key=case_key,
                to_key=key,
                kind="ownership",
                to_label=BIOMARKER_MEASUREMENT.label,
            )
        )

    if cancer_type:
        edges.append(
            ProjectionEdge(
                rel_type=DIAGNOSED_WITH,
                from_key=case_key,
                to_key=f"world:Disease:{cancer_type}",
                kind="bridge",
                to_label="Disease",
                match_property="name",
                match_value=cancer_type,
            )
        )

    return ProjectionPlan(case_id=case_id, nodes=tuple(nodes), edges=tuple(edges))
