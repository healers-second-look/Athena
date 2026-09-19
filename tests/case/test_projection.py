"""Offline unit tests for the patient-graph projection planner.

Pure. No FalkorDB, no Postgres. Mirrors tests/case/test_diff.py.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

from secondlook.case.projection import plan_projection
from secondlook.case.state import (
    Alteration,
    BiomarkerValue,
    CaseState,
    DiseaseAssessment,
    RawEvent,
    TreatmentEntry,
    fold_events,
)

CASE_ID = "case-proj-1"

CITATION_SHAPED = frozenset({"citation_url", "pmid", "civic_id", "source_url", "evidence_level"})

EVENT_DERIVED_LABELS = (
    "ObservedAlteration",
    "TreatmentLine",
    "DiseaseAssessment",
    "ClinicalQuestion",
    "BiomarkerMeasurement",
)


def _populated_state() -> CaseState:
    return CaseState(
        case_id=CASE_ID,
        alterations=(
            Alteration(
                gene="EGFR",
                variant="T790M",
                variant_type="missense",
                assay="NGS",
                tested_on="2026-01-02",
                event_id="evt-alt-1",
            ),
        ),
        biomarkers={
            "TMB": BiomarkerValue(
                name="TMB",
                value=16.0,
                unit="mut/Mb",
                measured_on="2026-01-03",
                event_id="evt-bio-1",
            ),
            "PD-L1": BiomarkerValue(
                name="PD-L1",
                value=35.0,
                unit="%",
                measured_on="2026-01-04",
                event_id="evt-bio-2",
            ),
        },
        treatments=(
            TreatmentEntry(
                regimen="osimertinib",
                line=1,
                action="started",
                reason=None,
                event_id="evt-tx-1",
            ),
        ),
        assessments=(
            DiseaseAssessment(
                status="stable",
                sites=["lung"],
                assessed_on="2026-01-05",
                event_id="evt-dx-1",
            ),
        ),
        clinical_questions=("next-line options after osimertinib?",),
    )


def _plan(**overrides):
    kwargs = {
        "cancer_type": "lung adenocarcinoma",
        "primary_site": "lung",
        "histology": "adenocarcinoma",
        "stage": "IV",
    }
    kwargs.update(overrides)
    return plan_projection(CASE_ID, _populated_state(), **kwargs)


def test_projection_module_is_import_clean_of_io():
    source = Path("src/secondlook/case/projection.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)

    forbidden_exact = {
        "falkordb",
        "sqlalchemy",
        "secondlook.chat",
        "secondlook.tier1.graph_connection",
    }
    hits = []
    for name in imported:
        if name in forbidden_exact:
            hits.append(name)
        if name.startswith("secondlook.chat.") or name.startswith("sqlalchemy."):
            hits.append(name)
        if name.startswith("falkordb."):
            hits.append(name)
    assert not hits, f"projection.py must stay I/O-free; found {hits}"


def test_plan_projection_is_deterministic():
    first = _plan()
    second = _plan()
    assert first == second
    assert first.nodes == second.nodes
    assert first.edges == second.edges


def test_event_derived_nodes_carry_source_event_id():
    events = [
        RawEvent(
            id="e-alt",
            event_type="ALTERATION_OBSERVED",
            payload={"gene": "EGFR", "variant": "T790M"},
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        RawEvent(
            id="e-bio",
            event_type="BIOMARKER_MEASURED",
            payload={"name": "TMB", "value": 12.0},
            occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        ),
        RawEvent(
            id="e-tx",
            event_type="TREATMENT_LINE",
            payload={"regimen": "osimertinib", "action": "started"},
            occurred_at=datetime(2026, 1, 3, tzinfo=UTC),
        ),
        RawEvent(
            id="e-dx",
            event_type="DISEASE_ASSESSMENT",
            payload={"status": "stable"},
            occurred_at=datetime(2026, 1, 4, tzinfo=UTC),
        ),
        RawEvent(
            id="e-q",
            event_type="CLINICAL_QUESTION",
            payload={"text": "any trial?"},
            occurred_at=datetime(2026, 1, 5, tzinfo=UTC),
        ),
    ]
    state = fold_events(CASE_ID, events)
    fold_event_ids = {e.id for e in events}
    plan = plan_projection(CASE_ID, state)

    seen: dict[str, str] = {}
    for node in plan.nodes:
        props = dict(node.properties)
        if node.label == "Case":
            continue
        source = props.get("source_event_id")
        assert source, f"{node.label} missing source_event_id"
        seen[node.label] = str(source)
        if node.label != "ClinicalQuestion":
            assert source in fold_event_ids, f"{node.label} id {source!r} not in fold"

    # ClinicalQuestion event ids are not kept on CaseState; the planner still
    # emits a non-empty provenance key derived from fold order (the question
    # tuple position), which is the only stable handle the fold exposes.
    for label in EVENT_DERIVED_LABELS:
        assert label in seen, f"missing {label} in plan"
        assert seen[label]


def test_no_citation_shaped_fields_on_patient_nodes():
    plan = _plan()
    offending: list[str] = []
    for node in plan.nodes:
        keys = {k for k, _v in node.properties}
        overlap = keys & CITATION_SHAPED
        if overlap:
            offending.append(f"{node.label}: {sorted(overlap)}")
    assert not offending, f"patient nodes must not carry citation-shaped fields: {offending}"


def test_biomarker_nodes_are_ordered_by_name_not_dict_insertion():
    """Dict insertion order must not leak into the plan (SS13.11)."""
    state = CaseState(
        case_id=CASE_ID,
        biomarkers={
            "TMB": BiomarkerValue(
                name="TMB", value=1.0, unit=None, measured_on=None, event_id="b-tmb"
            ),
            "PD-L1": BiomarkerValue(
                name="PD-L1", value=2.0, unit=None, measured_on=None, event_id="b-pdl1"
            ),
        },
    )
    plan = plan_projection(CASE_ID, state)
    bio = [n for n in plan.nodes if n.label == "BiomarkerMeasurement"]
    names = [dict(n.properties)["name"] for n in bio]
    assert names == sorted(names)
