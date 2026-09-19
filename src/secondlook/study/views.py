"""What a reviewer is allowed to see of a study case, per arm (issue #136).

The whole study rests on two things this module enforces by construction:

1. **Ground truth never leaves the server.** `valid`, `invalidated_by`,
   `flaw`, the seeded issues and the reference decision are not fields of any
   model here, so no code path can serialise them to a browser. A reviewer with
   devtools open learns nothing the interface does not already show.
2. **Only arm A is given the diff.** The reported changeset, the supersessions
   and the question worklist are the treatment; they are included for
   `diff_first` and structurally absent for `dashboard` and `chat`. Everything
   else -- events, findings, citations -- is identical across arms (protocol
   section 3: matched content, different organization).
"""

from __future__ import annotations

from pydantic import BaseModel

from secondlook.study.cases import StudyCase

DIFF_FIRST = "diff_first"


class CitationView(BaseModel):
    id: str
    url: str
    name: str


class EventView(BaseModel):
    id: str
    occurred_on: str
    event_type: str
    summary: str
    source_document: str | None = None


class FindingView(BaseModel):
    id: str
    claim: str
    evidence_class: str
    evidence_level: str | None = None
    citation: CitationView | None = None
    method: str | None = None


class ChangeView(BaseModel):
    kind: str
    summary: str
    triggering_event: str


class SupersessionView(BaseModel):
    finding_id: str
    broken_assumption: str
    triggering_event: str
    note: str


class QuestionView(BaseModel):
    id: str
    text: str


class DecisionOptionView(BaseModel):
    id: str
    text: str


class ReviewerCaseView(BaseModel):
    """The same shape for every arm; the diff fields are simply empty outside arm A."""

    case_id: str
    arm: str
    label: str
    cancer_type: str
    age_years: int | None = None
    stage: str | None = None
    baseline_events: list[EventView]
    update_events: list[EventView]
    findings: list[FindingView]
    decision_prompt: str
    decision_options: list[DecisionOptionView]
    reported_changes: list[ChangeView] = []
    reported_supersessions: list[SupersessionView] = []
    questions: list[QuestionView] = []


def _event(e) -> EventView:
    return EventView(
        id=e.id,
        occurred_on=e.occurred_on,
        event_type=e.event_type,
        summary=e.summary,
        source_document=e.source_document,
    )


def reviewer_view(case: StudyCase, arm: str) -> ReviewerCaseView:
    out = case.system_output
    findings = [
        FindingView(
            id=f.id,
            claim=f.claim,
            evidence_class=f.evidence_class,
            evidence_level=f.evidence_level,
            citation=(
                CitationView(id=f.citation.id, url=f.citation.url, name=f.citation.name)
                if f.citation
                else None
            ),
            method=f.method,
        )
        for f in out.findings
    ]
    view = ReviewerCaseView(
        case_id=case.case_id,
        arm=arm,
        label=case.label,
        cancer_type=case.cancer_type,
        age_years=case.age_years,
        stage=case.stage,
        baseline_events=[_event(e) for e in case.baseline_events],
        update_events=[_event(e) for e in case.update_events],
        findings=findings,
        decision_prompt=case.reference_decision.prompt,
        # Option text only -- which options are concordant is ground truth.
        decision_options=[
            DecisionOptionView(id=o.id, text=o.text) for o in case.reference_decision.options
        ],
    )
    if arm == DIFF_FIRST:
        view.reported_changes = [
            ChangeView(kind=c.kind, summary=c.summary, triggering_event=c.triggering_event)
            for c in out.reported_changes
        ]
        view.reported_supersessions = [
            SupersessionView(
                finding_id=s.finding_id,
                broken_assumption=s.broken_assumption,
                triggering_event=s.triggering_event,
                note=s.note,
            )
            for s in out.reported_supersessions
        ]
        view.questions = [QuestionView(id=q.id, text=q.text) for q in out.questions]
    return view
