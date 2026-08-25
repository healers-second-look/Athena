"""Case summary for MCP and REST GET /api/cases/{id}."""

from __future__ import annotations

from secondlook.query.contracts import (
    AlterationView,
    AssessmentView,
    BiomarkerView,
    CaseSummary,
    CurrentStateView,
    QuestionView,
    TimelineEventView,
    TreatmentView,
)
from secondlook.query.fold import fold_store_events
from secondlook.query.question_counts import question_status_counts
from secondlook.query.result import QueryResult


def get_case_summary(store, case_id) -> QueryResult[CaseSummary]:
    case = store.get_case(case_id)
    if case is None:
        return QueryResult(empty_reason=f"no case with id {case_id}")

    events = store.list_events(case_id)
    # Fold once here. Do not also call derive_state -- that would fold again.
    state = fold_store_events(case_id, events)
    questions = store.list_questions(case_id)
    findings = store.list_active_findings(case_id)
    question_counts = question_status_counts(questions)

    alteration_views = [AlterationView(gene=a.gene, variant=a.variant) for a in state.alterations]

    summary = CaseSummary(
        case_id=str(case.id),
        label=case.label,
        cancer_type=case.cancer_type,
        age_years=case.age_years,
        primary_site=case.primary_site,
        histology=case.histology,
        stage=case.stage,
        doid=case.doid,
        latest_assessment=state.latest_assessment,
        alterations=alteration_views,
        current_state=CurrentStateView(
            alterations=alteration_views,
            biomarkers=[
                BiomarkerView(name=b.name, value=b.value, unit=b.unit)
                for b in state.biomarkers.values()
            ],
            treatments=[
                TreatmentView(regimen=t.regimen, action=t.action, line=t.line)
                for t in state.treatments
            ],
            assessments=[AssessmentView(status=a.status) for a in state.assessments],
        ),
        timeline=[
            TimelineEventView(
                id=str(e.id),
                event_type=e.event_type,
                payload=e.payload,
                occurred_at=e.occurred_at,
                recorded_at=e.recorded_at,
                source_document=getattr(e, "source_document", None),
            )
            for e in events
        ],
        questions=[
            QuestionView(id=str(q.id), text=q.text, status=q.status, priority=q.priority)
            for q in questions
        ],
        question_counts=question_counts,
        active_finding_count=len(findings),
        empty_reason=None if events else "no events recorded for this case",
    )
    return QueryResult(items=(summary,))
