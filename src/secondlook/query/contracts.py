"""Pydantic wire shapes for the query layer (MCP and REST).

`ChangeSetForApi` is display-shaped: human-readable descriptions computed
server-side so a text client can render a change banner without reimplementing
`case/diff.py`. It is not a field-for-field mirror of `ChangeSet`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AlterationView(BaseModel):
    gene: str
    variant: str


class BiomarkerView(BaseModel):
    name: str
    value: float
    unit: str | None = None


class TreatmentView(BaseModel):
    regimen: str
    action: str
    line: int | None = None


class AssessmentView(BaseModel):
    status: str


class CurrentStateView(BaseModel):
    """Mirrors `case/state.py`'s `CaseState` shape for the frontend's
    `CurrentStatePanel` -- see issue #101. `alterations` is duplicated
    here (also present top-level on `CaseSummary` for `api/brief.py` and
    any other existing consumer) rather than replacing it, so this is a
    purely additive field.
    """

    alterations: list[AlterationView] = Field(default_factory=list)
    biomarkers: list[BiomarkerView] = Field(default_factory=list)
    treatments: list[TreatmentView] = Field(default_factory=list)
    assessments: list[AssessmentView] = Field(default_factory=list)


class TimelineEventView(BaseModel):
    """One raw case event, shaped for `web/src/components/Timeline.jsx`'s
    `describe()` -- it switches on `event_type` and reads fields straight
    out of `payload`, so this mirrors `CaseEvent`, not a pre-rendered
    summary string.
    """

    id: str
    event_type: str
    payload: dict
    occurred_at: datetime
    recorded_at: datetime
    source_document: str | None = None


class QuestionView(BaseModel):
    id: str
    text: str
    status: str
    priority: int


class CaseSummary(BaseModel):
    case_id: str
    label: str
    cancer_type: str
    age_years: int | None = None
    primary_site: str | None = None
    histology: str | None = None
    stage: str | None = None
    doid: str | None = None
    latest_assessment: str | None = None
    alterations: list[AlterationView] = Field(default_factory=list)
    current_state: CurrentStateView = Field(default_factory=CurrentStateView)
    timeline: list[TimelineEventView] = Field(default_factory=list)
    questions: list[QuestionView] = Field(default_factory=list)
    question_counts: dict[str, int] = Field(default_factory=dict)
    active_finding_count: int = 0
    empty_reason: str | None = None


class EvidenceItem(BaseModel):
    gene: str
    variant: str | None = None
    cancer_type: str | None = None
    retrieval_mode: str
    item: dict


class TrialMatchResult(BaseModel):
    trial_id: str
    bucket: str
    brief_title: str | None = None
    status: str | None = None
    phase: str | None = None
    eligibility_url: str | None = None
    matched_criteria: list[str] = Field(default_factory=list)
    unresolved_criteria: list[str] = Field(default_factory=list)
    violated_criteria: list[str] = Field(default_factory=list)


class AccessPathway(BaseModel):
    pathway_id: str
    country: str
    pathway_type: str
    instrument: str
    description: str
    source_url: str
    regulator: str | None = None
    precedent_strength: str | None = None
    review_status: str | None = None
    resolved_drug_name: str | None = None
    resolved_chembl_id: str | None = None


class ChangeDescription(BaseModel):
    kind: str
    summary: str
    triggering_event_id: str


class SupersessionDescription(BaseModel):
    finding_id: str
    broken_assumption: str
    note: str
    triggering_event_id: str


class ChangeSetForApi(BaseModel):
    """Display-shaped diff. Not a field-for-field mirror of `case/diff.ChangeSet`."""

    changes: list[ChangeDescription] = Field(default_factory=list)
    supersessions: list[SupersessionDescription] = Field(default_factory=list)
    boundary_event_id: str | None = None
    empty_reason: str | None = None


class DecisionView(BaseModel):
    id: str
    action: str
    reason: str
    decided_by: str
    decided_at: datetime


class FindingDetail(BaseModel):
    """Single finding plus the provenance chain GET /api/findings/{id} returns."""

    id: str
    claim: str
    evidence_class: str
    evidence_ref: dict
    evidence_level: str | None = None
    status: str
    assumptions: list[str] = Field(default_factory=list)
    question_text: str
    case_id: str
    decisions: list[DecisionView] = Field(default_factory=list)


class QueueView(BaseModel):
    case_id: str
    questions: list[QuestionView] = Field(default_factory=list)
    question_counts: dict[str, int] = Field(default_factory=dict)
    empty_reason: str | None = None


class CaseView(BaseModel):
    """Bare creation/read of a Case row. Not a CaseSummary — no folded state."""

    id: str
    label: str
    cancer_type: str
    age_years: int | None = None
    primary_site: str | None = None
    histology: str | None = None
    stage: str | None = None
    doid: str | None = None
    created_at: datetime | None = None
