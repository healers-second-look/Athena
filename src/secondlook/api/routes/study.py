"""Study routes for the diff-first evaluation (issue #136).

Off by default. The router is only mounted when ``ATHENA_STUDY_ENABLED`` is
true (see `api/app.py`), because two of its routes are reachable from a
browser with no API key: a reviewer's browser must be able to fetch a case and
log events, and it has no secret to send. That is acceptable for a closed,
supervised study deployment on synthetic cases and is not acceptable on a
reachable network -- `create_app` warns loudly, the same way it does for
``ATHENA_API_AUTH_DISABLED``. Reading the collected data back
(``GET /events``) does require the server API key.

The case set served is whatever ``ATHENA_STUDY_CASE_SET`` points at. Unless
``ATHENA_STUDY_ALLOW_UNREVIEWED`` is set, only a clinician-reviewed set with
verified citations is served -- the shipped pilot set is refused, so a real
study cannot silently run on debug content. When the override is on, every
response says so (`unreviewed: true`) and the client must show it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from secondlook.api.auth import require_api_key
from secondlook.api.deps import get_session
from secondlook.study.cases import (
    DEFAULT_CASE_SET_DIR,
    STUDY_ELIGIBLE_STATUS,
    CaseSet,
    CaseSetError,
    IneligibleCaseSetError,
    assert_eligible_for_study,
    load_case_set,
    validate_case_set,
)
from secondlook.study.events import (
    ARMS,
    MAX_BATCH,
    InvalidStudyEvent,
    NewStudyEvent,
    StudyEventStore,
)
from secondlook.study.views import ReviewerCaseView, reviewer_view

ENABLED_ENV = "ATHENA_STUDY_ENABLED"
CASE_SET_ENV = "ATHENA_STUDY_CASE_SET"
ALLOW_UNREVIEWED_ENV = "ATHENA_STUDY_ALLOW_UNREVIEWED"

router = APIRouter(prefix="/api/study", tags=["study"])


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def study_enabled() -> bool:
    return _flag(ENABLED_ENV)


@dataclass(frozen=True)
class LoadedCaseSet:
    case_set: CaseSet
    unreviewed: bool


def get_case_set() -> LoadedCaseSet:
    path = Path(os.environ.get(CASE_SET_ENV) or DEFAULT_CASE_SET_DIR / "pilot_v0.yaml")
    try:
        case_set = load_case_set(path)
    except (OSError, CaseSetError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=500, detail=f"cannot load case set {path}: {exc}") from exc

    if _flag(ALLOW_UNREVIEWED_ENV):
        problems = validate_case_set(case_set)
        if problems:
            raise HTTPException(status_code=500, detail={"case_set_errors": problems})
        unreviewed = case_set.review_status != STUDY_ELIGIBLE_STATUS or any(
            not c.citations_verified for c in case_set.cases
        )
        return LoadedCaseSet(case_set, unreviewed)

    try:
        assert_eligible_for_study(case_set)
    except IneligibleCaseSetError as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "no eligible study case set is configured", "reasons": exc.reasons},
        ) from exc
    return LoadedCaseSet(case_set, False)


def get_study_store(session: Session = Depends(get_session)) -> StudyEventStore:
    return StudyEventStore(session)


class CaseListItem(BaseModel):
    case_id: str
    label: str


class CaseListResponse(BaseModel):
    set_id: str
    version: int
    unreviewed: bool
    cases: list[CaseListItem]


class StudyCaseResponse(BaseModel):
    unreviewed: bool
    case: ReviewerCaseView


class StudyEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_id: str
    session_id: str
    case_id: str
    arm: str
    event_type: str
    client_ts: datetime
    payload: dict = Field(default_factory=dict)


class StudyEventsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[StudyEventIn] = Field(min_length=1, max_length=MAX_BATCH)


class StudyEventsAccepted(BaseModel):
    accepted: int


class StudyEventOut(BaseModel):
    id: str
    participant_id: str
    session_id: str
    case_id: str
    arm: str
    event_type: str
    payload: dict
    client_ts: datetime
    server_ts: datetime


@router.get("/cases", response_model=CaseListResponse)
def list_cases(loaded: LoadedCaseSet = Depends(get_case_set)) -> CaseListResponse:
    cs = loaded.case_set
    return CaseListResponse(
        set_id=cs.set_id,
        version=cs.version,
        unreviewed=loaded.unreviewed,
        cases=[CaseListItem(case_id=c.case_id, label=c.label) for c in cs.cases],
    )


@router.get("/cases/{case_id}", response_model=StudyCaseResponse)
def read_case(
    case_id: str,
    arm: str = Query(...),
    loaded: LoadedCaseSet = Depends(get_case_set),
) -> StudyCaseResponse:
    if arm not in ARMS:
        raise HTTPException(status_code=422, detail=f"arm must be one of {list(ARMS)}")
    case = next((c for c in loaded.case_set.cases if c.case_id == case_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no study case {case_id!r}")
    return StudyCaseResponse(unreviewed=loaded.unreviewed, case=reviewer_view(case, arm))


@router.post("/events", response_model=StudyEventsAccepted, status_code=201)
def write_events(
    body: StudyEventsIn,
    loaded: LoadedCaseSet = Depends(get_case_set),
    store: StudyEventStore = Depends(get_study_store),
) -> StudyEventsAccepted:
    known = {c.case_id for c in loaded.case_set.cases}
    for event in body.events:
        if event.case_id not in known:
            raise HTTPException(status_code=422, detail=f"unknown study case {event.case_id!r}")
    try:
        accepted = store.append_many(
            [
                NewStudyEvent(
                    participant_id=e.participant_id,
                    session_id=e.session_id,
                    case_id=e.case_id,
                    arm=e.arm,
                    event_type=e.event_type,
                    client_ts=e.client_ts,
                    payload=e.payload,
                )
                for e in body.events
            ]
        )
    except InvalidStudyEvent as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StudyEventsAccepted(accepted=accepted)


@router.get("/events", response_model=list[StudyEventOut])
def read_events(
    participant_id: str | None = None,
    case_id: str | None = None,
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    store: StudyEventStore = Depends(get_study_store),
    _: None = Depends(require_api_key),
) -> list[StudyEventOut]:
    rows = store.list_events(
        participant_id=participant_id, case_id=case_id, limit=limit, offset=offset
    )
    return [
        StudyEventOut(
            id=str(r.id),
            participant_id=r.participant_id,
            session_id=r.session_id,
            case_id=r.case_id,
            arm=r.arm,
            event_type=r.event_type,
            payload=r.payload,
            client_ts=r.client_ts,
            server_ts=r.server_ts,
        )
        for r in rows
    ]


__all__ = ["router", "study_enabled"]
