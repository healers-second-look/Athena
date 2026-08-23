"""Event log -> derived `CaseState`.

Pure. No I/O, no database session. Takes an ordered sequence of `RawEvent`
(a plain dataclass, not a SQLAlchemy row) and folds it into a `CaseState`.
This is deliberate: the diff engine (`case/diff.py`, subsystem D) consumes
`CaseState` objects directly and must stay offline-testable per the
project-wide DI invariant (`IMPLEMENTATION_PLAN.md` SS13.2) -- it should
never need a live Postgres connection to run its test suite. `store.py`
is the only module that bridges `CaseEvent` rows to `RawEvent` and calls
`fold_events`.

Payload shapes follow the five-type taxonomy in `models.py`'s
`EVENT_TYPES` exactly -- see `IMPLEMENTATION_PLAN.md` SS2.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RawEvent:
    """The minimal shape `fold_events` needs from a `CaseEvent` row."""

    id: str
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class Alteration:
    gene: str
    variant: str
    variant_type: str | None
    assay: str | None
    tested_on: str | None
    event_id: str


@dataclass(frozen=True)
class BiomarkerValue:
    name: str
    value: float
    unit: str | None
    measured_on: str | None
    event_id: str


@dataclass(frozen=True)
class TreatmentEntry:
    regimen: str
    line: int | None
    action: str  # "started" | "stopped"
    reason: str | None
    event_id: str


@dataclass(frozen=True)
class DiseaseAssessment:
    status: str  # "response" | "stable" | "progression"
    sites: list[str] | None
    assessed_on: str | None
    event_id: str


@dataclass(frozen=True)
class CaseState:
    """Current state of a case, derived by folding its event log.

    Two states of the same case (`previous`, `current`) are exactly what
    `case/diff.py`'s `compute_diff()` takes as input -- this dataclass's
    shape is a contract with that module, not just internal bookkeeping.
    """

    case_id: str
    alterations: tuple[Alteration, ...] = field(default_factory=tuple)
    biomarkers: dict[str, BiomarkerValue] = field(default_factory=dict)
    treatments: tuple[TreatmentEntry, ...] = field(default_factory=tuple)
    assessments: tuple[DiseaseAssessment, ...] = field(default_factory=tuple)
    clinical_questions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def latest_assessment(self) -> str | None:
        """Most recent disease-assessment status, or None if never assessed.

        `DiseaseNotProgressing.holds()` in `case/diff.py` reads exactly
        this property.
        """
        return self.assessments[-1].status if self.assessments else None


def fold_events(case_id: str, events: list[RawEvent]) -> CaseState:
    """Deterministic. Same event list, in the same order, in -> byte-identical
    CaseState, always. Events are expected pre-sorted by `occurred_at`
    (ascending) by the caller (`store.py`, which sorts at the query level) --
    this function does not re-sort, since re-sorting silently masks a caller
    bug in event ordering rather than surfacing it.
    """
    alterations: list[Alteration] = []
    biomarkers: dict[str, BiomarkerValue] = {}
    treatments: list[TreatmentEntry] = []
    assessments: list[DiseaseAssessment] = []
    clinical_questions: list[str] = []

    for event in events:
        payload = event.payload

        if event.event_type == "ALTERATION_OBSERVED":
            alterations.append(
                Alteration(
                    gene=payload["gene"],
                    variant=payload["variant"],
                    variant_type=payload.get("variant_type"),
                    assay=payload.get("assay"),
                    tested_on=payload.get("tested_on"),
                    event_id=event.id,
                )
            )

        elif event.event_type == "BIOMARKER_MEASURED":
            name = payload["name"]
            biomarkers[name] = BiomarkerValue(
                name=name,
                value=payload["value"],
                unit=payload.get("unit"),
                measured_on=payload.get("measured_on"),
                event_id=event.id,
            )

        elif event.event_type == "TREATMENT_LINE":
            treatments.append(
                TreatmentEntry(
                    regimen=payload["regimen"],
                    line=payload.get("line"),
                    action=payload["action"],
                    reason=payload.get("reason"),
                    event_id=event.id,
                )
            )

        elif event.event_type == "DISEASE_ASSESSMENT":
            assessments.append(
                DiseaseAssessment(
                    status=payload["status"],
                    sites=payload.get("sites"),
                    assessed_on=payload.get("assessed_on"),
                    event_id=event.id,
                )
            )

        elif event.event_type == "CLINICAL_QUESTION":
            clinical_questions.append(payload["text"])

        else:
            # Unknown event_type. Fail loudly rather than silently drop it --
            # per the project's "no silent gaps" rule (IMPLEMENTATION_PLAN.md
            # SS13.1). A new event type must be added to models.EVENT_TYPES
            # and handled here in the same PR.
            raise ValueError(f"Unknown event_type {event.event_type!r} on event {event.id}")

    return CaseState(
        case_id=case_id,
        alterations=tuple(alterations),
        biomarkers=biomarkers,
        treatments=tuple(treatments),
        assessments=tuple(assessments),
        clinical_questions=tuple(clinical_questions),
    )
