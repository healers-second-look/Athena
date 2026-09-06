"""Request/response models this issue adds on top of query/contracts.py."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from secondlook.case.models import DECISION_ACTIONS, EVENT_TYPES


class CreateCaseRequest(BaseModel):
    """Mirrors CaseStore.create_case kwargs exactly. No extra P0 event fields."""

    model_config = ConfigDict(extra="forbid")

    label: str
    cancer_type: str
    age_years: int | None = None
    primary_site: str | None = None
    histology: str | None = None
    stage: str | None = None
    doid: str | None = None


class AppendEventRequest(BaseModel):
    event_type: str
    payload: dict
    occurred_at: datetime
    source_document: str | None = None
    recorded_by: str | None = None

    @field_validator("event_type")
    @classmethod
    def event_type_must_be_known(cls, value: str) -> str:
        if value not in EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(EVENT_TYPES)}")
        return value


class RecordDecisionRequest(BaseModel):
    action: str
    reason: str
    decided_by: str

    @field_validator("action")
    @classmethod
    def action_must_be_known(cls, value: str) -> str:
        if value not in DECISION_ACTIONS:
            raise ValueError(f"action must be one of {sorted(DECISION_ACTIONS)}")
        return value


class ResearchFindingView(BaseModel):
    id: str
    claim: str
    question_id: str


class ResearchResponse(BaseModel):
    questions_created: int
    findings_created: int
    findings: list[ResearchFindingView] = Field(default_factory=list)


# -- Patient Timeline -------------------------------------------------------
# Shapes mirror secondlook.timeline.reference_data's converted JSON field
# names exactly, so the API layer stays a thin pass-through rather than a
# second place these field names could drift out of sync.


class TimelineEventView(BaseModel):
    date: str
    end_date: str | None = None
    category: str  # "Treatments" | "Procedures" | "Imaging"
    subcategory: str | None = None
    group: str | None = None
    title: str
    dose: str | None = None
    condition_track: str


class MRDResultView(BaseModel):
    date: str
    assay: str
    value: str | None = None
    kind: str  # "not_detected" | "below_loq" | "numeric" | assay-report kind


class CytometryResultView(BaseModel):
    date: str
    category: str
    measurement: str
    short_name: str
    unit: str
    value: float


class LabResultView(BaseModel):
    date: str
    category: str
    measurement: str
    test_name: str
    panel_name: str | None = None
    unit: str | None = None
    value: str | None = None
    reference_low: str | None = None
    reference_high: str | None = None
    flag: str | None = None
    out_of_range: bool = False


class TimelineBundleView(BaseModel):
    """Everything the Patient Timeline section renders, in one response.

    Today every case returns the same reference dataset -- see
    `timeline.reference_data.get_patient_timeline`'s docstring for why, and
    for the seam a real per-patient data source will replace.
    """

    events: list[TimelineEventView] = Field(default_factory=list)
    mrd: list[MRDResultView] = Field(default_factory=list)
    cytometry: list[CytometryResultView] = Field(default_factory=list)
    lab_results: list[LabResultView] = Field(default_factory=list)
