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
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from secondlook.api.auth import API_KEY_HEADER, require_api_key
from secondlook.api.deps import get_session
from secondlook.chat.engine import run_turn
from secondlook.chat.knowledge import graph_live_evidence_ready
from secondlook.chat.session import create_session
from secondlook.chat.session import get_session as get_chat_session
from secondlook.study.assignment import build_schedule
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
from secondlook.study.chat import (
    briefing_text,
    chat_context_lines,
    chat_sources,
    gene_context_id,
)
from secondlook.study.enrollment import StudyParticipant, enrollment_required
from secondlook.study.events import (
    ARMS,
    MAX_BATCH,
    InvalidStudyEvent,
    NewStudyEvent,
    StudyEventStore,
)
from secondlook.study.schedule import participant_case_schedule, schedule_contains
from secondlook.study.views import (
    RecallOptionView,
    ReviewerCaseView,
    recall_options,
    reviewer_view,
)

ENABLED_ENV = "ATHENA_STUDY_ENABLED"
CASE_SET_ENV = "ATHENA_STUDY_CASE_SET"
ALLOW_UNREVIEWED_ENV = "ATHENA_STUDY_ALLOW_UNREVIEWED"
CHAT_MODEL_ENV = "ATHENA_STUDY_CHAT_MODEL"
DEFAULT_CHAT_MODEL = "mock-outline"
STUDY_CHAT_MAX_TURNS_ENV = "STUDY_CHAT_MAX_TURNS"
DEFAULT_STUDY_CHAT_MAX_TURNS = 40
MOCK_STUDY_MODELS = frozenset({"mock-outline", "mock-terse"})
ATHENA_FULL_ATTACHMENTS = ("variant-normalizer", "citation-guard")

router = APIRouter(prefix="/api/study", tags=["study"])


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def study_chat_allows_degraded() -> bool:
    return _flag(ALLOW_UNREVIEWED_ENV)


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


def require_admin_when_enrollment_locked(
    x_athena_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> str | None:
    """When ``STUDY_REQUIRE_ENROLLMENT`` is on, legacy schedule export needs the admin key."""
    if enrollment_required():
        return require_api_key(x_athena_api_key)
    return None


def require_api_key_when_enrollment_locked(
    x_athena_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> str | None:
    if enrollment_required():
        return require_api_key(x_athena_api_key)
    return None


def _schedule_for_participant(
    participant: StudyParticipant,
    loaded: LoadedCaseSet,
) -> list[tuple[str, str]]:
    case_ids = [c.case_id for c in loaded.case_set.cases]
    return participant_case_schedule(participant.reviewer_index, case_ids)


def _participant_row(
    participant_id: str,
    session: Session,
) -> StudyParticipant | None:
    return session.get(StudyParticipant, participant_id)


def enrolled_participant_when_required(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> StudyParticipant | None:
    """Active participant row when enrollment is enforced; otherwise skipped."""
    if not enrollment_required():
        return None
    from secondlook.api.routes.enroll import require_participant_token

    participant_id = require_participant_token(authorization)
    row = _participant_row(participant_id, session)
    if row is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    if row.withdrawn_at is not None:
        raise HTTPException(status_code=403, detail="participant has withdrawn")
    return row


def active_enrolled_participant(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> str | None:
    """Bearer token identifying the participant when enrollment is enforced."""
    if not enrollment_required():
        return None
    from secondlook.api.routes.enroll import require_participant_token

    participant_id = require_participant_token(authorization)
    row = session.get(StudyParticipant, participant_id)
    if row is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    if row.withdrawn_at is not None:
        raise HTTPException(status_code=403, detail="participant has withdrawn")
    return participant_id


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


class RecallResponse(BaseModel):
    case_id: str
    options: list[RecallOptionView]


class ScheduleItem(BaseModel):
    case_id: str
    arm: str
    label: str


class ScheduleResponse(BaseModel):
    reviewer_index: int
    participant_id: str
    unreviewed: bool
    items: list[ScheduleItem]


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
def list_cases(
    loaded: LoadedCaseSet = Depends(get_case_set),
    _: str | None = Depends(require_api_key_when_enrollment_locked),
) -> CaseListResponse:
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
    db: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> StudyCaseResponse:
    if enrollment_required():
        from secondlook.api.routes.enroll import require_participant_token

        participant_id = require_participant_token(authorization)
        participant = _participant_row(participant_id, db)
        if participant is None:
            raise HTTPException(status_code=401, detail="invalid or expired token")
        if participant.withdrawn_at is not None:
            raise HTTPException(status_code=403, detail="participant has withdrawn")
        schedule = _schedule_for_participant(participant, loaded)
        if not schedule_contains(schedule, case_id=case_id, arm=arm):
            raise HTTPException(status_code=403, detail="case not in participant schedule")
    if arm not in ARMS:
        raise HTTPException(status_code=422, detail=f"arm must be one of {list(ARMS)}")
    case = next((c for c in loaded.case_set.cases if c.case_id == case_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no study case {case_id!r}")
    return StudyCaseResponse(unreviewed=loaded.unreviewed, case=reviewer_view(case, arm))


@router.get("/cases/{case_id}/recall", response_model=RecallResponse)
def read_recall_options(
    case_id: str,
    loaded: LoadedCaseSet = Depends(get_case_set),
    participant: StudyParticipant | None = Depends(enrolled_participant_when_required),
) -> RecallResponse:
    if participant is not None and case_id not in {
        scheduled for scheduled, _ in _schedule_for_participant(participant, loaded)
    }:
        raise HTTPException(status_code=403, detail="case not in participant schedule")
    case = next((c for c in loaded.case_set.cases if c.case_id == case_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no study case {case_id!r}")
    return RecallResponse(case_id=case_id, options=recall_options(case))


@router.get("/schedule/{reviewer_index}", response_model=ScheduleResponse)
def read_schedule(
    reviewer_index: int,
    cases_per_arm: int | None = Query(None, ge=1, le=20),
    loaded: LoadedCaseSet = Depends(get_case_set),
    _: str | None = Depends(require_admin_when_enrollment_locked),
) -> ScheduleResponse:
    """The reviewer's ordered (case, arm) list -- see study/assignment.py.

    `cases_per_arm` defaults to the protocol's 3, or fewer if the pool is too
    small (a dry run on the pilot set); a real run passes it explicitly.
    """
    if reviewer_index < 0:
        raise HTTPException(status_code=422, detail="reviewer_index must be >= 0")
    cases = loaded.case_set.cases
    per_arm = cases_per_arm or max(1, min(3, len(cases) // 3))
    try:
        pairs = build_schedule(reviewer_index, [c.case_id for c in cases], cases_per_arm=per_arm)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    labels = {c.case_id: c.label for c in cases}
    return ScheduleResponse(
        reviewer_index=reviewer_index,
        participant_id=f"P{reviewer_index + 1:02d}",
        unreviewed=loaded.unreviewed,
        items=[ScheduleItem(case_id=c, arm=a, label=labels[c]) for c, a in pairs],
    )


# --- chat arm (arm C) -----------------------------------------------------------


@dataclass(frozen=True)
class StudyChatMeta:
    case_id: str
    participant_id: str | None
    mode: str


_STUDY_CHAT_SESSIONS: dict[str, StudyChatMeta] = {}


class StudyChatSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    arm: str | None = None


class StudyChatTurnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(max_length=4000)


def _study_chat_max_turns() -> int:
    raw = os.environ.get(STUDY_CHAT_MAX_TURNS_ENV, str(DEFAULT_STUDY_CHAT_MAX_TURNS)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_STUDY_CHAT_MAX_TURNS


def _athena_full_degraded_reasons(model_id: str) -> list[str]:
    reasons: list[str] = []
    ok, graph_reasons = graph_live_evidence_ready()
    if not ok:
        reasons.extend(graph_reasons)
    if model_id in MOCK_STUDY_MODELS:
        reasons.append(f"study chat model {model_id!r} is a mock, not live synthesis")
    return reasons


def _count_user_turns(participant_id: str, case_id: str) -> int:
    total = 0
    for session_id, meta in _STUDY_CHAT_SESSIONS.items():
        if meta.participant_id != participant_id or meta.case_id != case_id:
            continue
        session = get_chat_session(session_id)
        if session is None:
            continue
        total += sum(1 for msg in session.history if msg["role"] == "user")
    return total


def _study_chat_meta(session_id: str) -> StudyChatMeta | None:
    return _STUDY_CHAT_SESSIONS.get(session_id)


def _assert_study_session_access(
    meta: StudyChatMeta,
    participant: StudyParticipant | None,
) -> None:
    if not enrollment_required():
        return
    if participant is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    if meta.participant_id != participant.participant_id:
        raise HTTPException(status_code=404, detail="no such study chat session")


def _session_chat_mode(body: StudyChatSessionIn) -> str:
    if enrollment_required():
        return "athena_full"
    if body.arm == "athena_full":
        return "athena_full"
    return "chat"


def _find_case(loaded: LoadedCaseSet, case_id: str):
    case = next((c for c in loaded.case_set.cases if c.case_id == case_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no study case {case_id!r}")
    return case


@router.post("/chat/sessions")
def create_study_chat_session(
    body: StudyChatSessionIn,
    loaded: LoadedCaseSet = Depends(get_case_set),
    participant: StudyParticipant | None = Depends(enrolled_participant_when_required),
) -> dict:
    """A chat session about one study case, opened with the shared findings.

    The model is fixed by `ATHENA_STUDY_CHAT_MODEL` (the protocol pins it), not
    chosen by the reviewer.
    """
    case = _find_case(loaded, body.case_id)
    mode = _session_chat_mode(body)
    owner_id: str | None = None
    if enrollment_required():
        if participant is None:
            raise HTTPException(status_code=401, detail="missing bearer token")
        owner_id = participant.participant_id
        schedule = _schedule_for_participant(participant, loaded)
        if mode == "athena_full" and not schedule_contains(
            schedule, case_id=body.case_id, arm="athena_full"
        ):
            raise HTTPException(status_code=403, detail="case not in participant schedule")

    model_id = os.environ.get(CHAT_MODEL_ENV) or DEFAULT_CHAT_MODEL
    degraded: list[str] = []
    if mode == "athena_full":
        degraded = _athena_full_degraded_reasons(model_id)
        if degraded and not study_chat_allows_degraded():
            raise HTTPException(status_code=503, detail="; ".join(degraded))

    context_id = gene_context_id(case) if mode == "athena_full" else None
    attachment_ids = list(ATHENA_FULL_ATTACHMENTS) if mode == "athena_full" else []
    session = create_session(
        model_id=model_id,
        attachment_ids=attachment_ids,
        context_id=context_id,
    )
    session.add_message(
        "assistant",
        briefing_text(case),
        sources=chat_sources(case),
        sources_count=len(case.system_output.findings),
        entities={},
        notes=[],
        context_lines=[],
        model_id=session.model_id,
    )
    _STUDY_CHAT_SESSIONS[session.id] = StudyChatMeta(
        case_id=case.case_id,
        participant_id=owner_id,
        mode=mode,
    )
    payload = session.as_dict()
    payload["mode"] = mode
    if degraded:
        payload["degraded"] = degraded
    return payload


@router.get("/chat/sessions/{session_id}")
def read_study_chat_session(
    session_id: str,
    participant: StudyParticipant | None = Depends(enrolled_participant_when_required),
) -> dict:
    session = get_chat_session(session_id)
    meta = _study_chat_meta(session_id)
    if session is None or meta is None:
        raise HTTPException(status_code=404, detail="no such study chat session")
    _assert_study_session_access(meta, participant)
    payload = session.as_dict()
    payload["mode"] = meta.mode
    return payload


@router.post("/chat/sessions/{session_id}/turns")
def send_study_chat_turn(
    session_id: str,
    body: StudyChatTurnIn,
    loaded: LoadedCaseSet = Depends(get_case_set),
    participant: StudyParticipant | None = Depends(enrolled_participant_when_required),
) -> dict:
    session = get_chat_session(session_id)
    meta = _study_chat_meta(session_id)
    if session is None or meta is None:
        raise HTTPException(status_code=404, detail="no such study chat session")
    _assert_study_session_access(meta, participant)

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")
    if len(body.message) > 4000:
        raise HTTPException(status_code=422, detail="message exceeds 4000 characters")

    if meta.participant_id is not None:
        if _count_user_turns(meta.participant_id, meta.case_id) >= _study_chat_max_turns():
            raise HTTPException(
                status_code=429,
                detail="turn limit reached for this case",
            )

    case = _find_case(loaded, meta.case_id)
    if meta.mode == "athena_full" and not study_chat_allows_degraded():
        # Retrieval swallows graph errors and returns no sources, so a graph
        # lost mid-case would silently turn this arm into an ungrounded chat.
        if _athena_full_degraded_reasons(session.model_id):
            raise HTTPException(status_code=503, detail="Athena evidence is not available")
    user_msg = session.add_message("user", message)
    if meta.mode == "athena_full":
        result = run_turn(
            message,
            model_id=session.model_id,
            attachment_ids=list(ATHENA_FULL_ATTACHMENTS),
            context_id=session.context_id,
            extra_context_lines=chat_context_lines(case),
        )
    else:
        result = run_turn(
            message,
            model_id=session.model_id,
            attachment_ids=[],
            sources_override=chat_sources(case),
            extra_context_lines=chat_context_lines(case),
        )
    assistant_msg = session.add_message(
        "assistant",
        result.content,
        entities=result.entities,
        notes=result.notes,
        context_lines=result.context_lines,
        sources=result.sources,
        sources_count=result.sources_count,
        model_id=result.model_id,
    )
    return {"user_message": user_msg, "assistant_message": assistant_msg, "turn": result.as_dict()}


@router.post("/events", response_model=StudyEventsAccepted, status_code=201)
def write_events(
    body: StudyEventsIn,
    loaded: LoadedCaseSet = Depends(get_case_set),
    store: StudyEventStore = Depends(get_study_store),
    token_participant: str | None = Depends(active_enrolled_participant),
    db: Session = Depends(get_session),
) -> StudyEventsAccepted:
    known = {c.case_id for c in loaded.case_set.cases}
    schedule: list[tuple[str, str]] | None = None
    if token_participant is not None:
        participant = _participant_row(token_participant, db)
        if participant is not None:
            schedule = _schedule_for_participant(participant, loaded)
    for event in body.events:
        if event.case_id not in known:
            raise HTTPException(status_code=422, detail=f"unknown study case {event.case_id!r}")
        if token_participant is not None and event.participant_id != token_participant:
            raise HTTPException(
                status_code=403,
                detail="participant_id does not match session token",
            )
        if schedule is not None and not schedule_contains(
            schedule, case_id=event.case_id, arm=event.arm
        ):
            raise HTTPException(status_code=403, detail="case not in participant schedule")
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
