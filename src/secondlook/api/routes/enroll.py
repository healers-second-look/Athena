"""Study enrollment routes under /api/study (mounted on the study router)."""

from __future__ import annotations

import os
import csv
import io
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from secondlook.api.auth import require_api_key
from secondlook.api.deps import get_session
from secondlook.api.routes.study import LoadedCaseSet, ScheduleItem, get_case_set
from secondlook.study.enrollment import (
    ALL_CHECKBOX_IDS,
    CONSENT_VERSION,
    EMAIL_RE,
    GENERIC_CODE_ERROR,
    GENERIC_RESUME_ERROR,
    REQUIRED_CHECKBOX_IDS,
    SPECIALTIES,
    TOKEN_TYPE_ENROLL,
    TOKEN_TYPE_SESSION,
    StudyConsent,
    StudyInvite,
    StudyParticipant,
    consent_text_sha256,
    invite_from_code,
    invite_is_usable,
    load_consent_markdown,
    mint_enrollment_token,
    mint_session_token,
    participant_id_for_index,
    rate_limit_exceeded,
    record_failed_attempt,
    verify_token,
)
from secondlook.study.events import StudyEvent
from secondlook.study.schedule import participant_case_schedule

router = APIRouter(tags=["study-enrollment"])


STUDY_TRUSTED_IP_HEADER_ENV = "STUDY_TRUSTED_IP_HEADER"


def _client_ip(request: Request) -> str:
    trusted = os.environ.get(STUDY_TRUSTED_IP_HEADER_ENV, "").strip()
    if trusted:
        raw = request.headers.get(trusted, "").strip()
        if trusted.lower() == "x-forwarded-for":
            hops = [h.strip() for h in raw.split(",") if h.strip()]
            if hops:
                return hops[-1]
        elif raw:
            return raw
    return request.client.host if request.client else "unknown"


class EnrollCodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)


class CheckboxOut(BaseModel):
    id: str
    label: str


class EnrollCodeOut(BaseModel):
    enrollment_token: str
    consent_version: str
    consent_markdown: str
    consent_sha256: str
    required_checkboxes: list[CheckboxOut]


class EnrollConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_token: str
    consent_version: str
    consent_sha256: str
    signed_name: str
    answers: dict[str, bool]


class EnrollProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_token: str
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    registration_number: str = Field(min_length=1, max_length=100)
    specialty: str
    years_in_oncology: int = Field(ge=0, le=60)
    institution: str = Field(min_length=1, max_length=300)
    has_uptodate: bool
    has_nccn: bool
    ai_familiarity: int = Field(ge=1, le=5)


class EnrollTokenOut(BaseModel):
    token: str
    participant_id: str


class EnrollResumeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    email: str


class MeScheduleOut(BaseModel):
    participant_id: str
    reviewer_index: int
    unreviewed: bool
    items: list[ScheduleItem]
    completed_case_ids: list[str]


def _invite_id_from_enrollment_token(token: str) -> uuid.UUID:
    try:
        payload = verify_token(token, expected_type=TOKEN_TYPE_ENROLL)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired enrollment token") from None
    try:
        return uuid.UUID(str(payload["invite_id"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="invalid or expired enrollment token") from None


def require_participant_token(
    authorization: str | None = Header(default=None),
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    raw = authorization.split(" ", 1)[1].strip()
    try:
        payload = verify_token(raw, expected_type=TOKEN_TYPE_SESSION)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired token") from None
    participant_id = payload.get("participant_id")
    if not isinstance(participant_id, str) or not participant_id:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return participant_id


@router.post("/enroll/code", response_model=EnrollCodeOut)
def enroll_code(
    body: EnrollCodeIn,
    request: Request,
    session: Session = Depends(get_session),
) -> EnrollCodeOut:
    ip = _client_ip(request)
    if rate_limit_exceeded(ip):
        raise HTTPException(status_code=429, detail="too many attempts; try again later")

    invite = invite_from_code(session, body.code)
    if invite is None or not invite_is_usable(invite):
        record_failed_attempt(ip)
        raise HTTPException(status_code=404, detail=GENERIC_CODE_ERROR)

    if invite.participant_id:
        raise HTTPException(
            status_code=409,
            detail="This invite has already been used. Use /api/study/enroll/resume to continue.",
        )

    from secondlook.study.enrollment import REQUIRED_CHECKBOXES

    return EnrollCodeOut(
        enrollment_token=mint_enrollment_token(invite.id),
        consent_version=CONSENT_VERSION,
        consent_markdown=load_consent_markdown(),
        consent_sha256=consent_text_sha256(),
        required_checkboxes=[CheckboxOut(id=i, label=label) for i, label in REQUIRED_CHECKBOXES],
    )


@router.post("/enroll/consent", status_code=201)
def enroll_consent(
    body: EnrollConsentIn,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    invite_id = _invite_id_from_enrollment_token(body.enrollment_token)
    invite = session.get(StudyInvite, invite_id)
    if invite is None or not invite_is_usable(invite):
        raise HTTPException(status_code=401, detail="invalid or expired enrollment token")

    existing = session.scalars(
        select(StudyConsent).where(StudyConsent.invite_id == invite_id)
    ).first()
    if existing is not None:
        return {"status": "already_recorded"}

    if body.consent_version != CONSENT_VERSION or body.consent_sha256 != consent_text_sha256():
        raise HTTPException(status_code=422, detail="consent document version mismatch; reload and try again")

    if not body.signed_name.strip():
        raise HTTPException(status_code=422, detail="signed_name is required")

    if set(body.answers.keys()) - ALL_CHECKBOX_IDS:
        raise HTTPException(status_code=422, detail="unknown checkbox id in answers")

    for checkbox_id in REQUIRED_CHECKBOX_IDS:
        if not body.answers.get(checkbox_id):
            raise HTTPException(status_code=422, detail=f"required consent not given: {checkbox_id}")

    session.add(
        StudyConsent(
            invite_id=invite_id,
            participant_id=None,
            consent_version=body.consent_version,
            text_sha256=body.consent_sha256,
            signed_name=body.signed_name.strip(),
            answers=dict(body.answers),
            accepted_at=datetime.now(UTC),
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    )
    session.flush()
    return {"status": "recorded"}


@router.post("/enroll/profile", response_model=EnrollTokenOut)
def enroll_profile(
    body: EnrollProfileIn,
    session: Session = Depends(get_session),
) -> EnrollTokenOut:
    invite_id = _invite_id_from_enrollment_token(body.enrollment_token)
    invite = session.get(StudyInvite, invite_id)
    if invite is None or not invite_is_usable(invite):
        raise HTTPException(status_code=401, detail="invalid or expired enrollment token")

    consent = session.scalars(
        select(StudyConsent).where(StudyConsent.invite_id == invite_id)
    ).first()
    if consent is None:
        raise HTTPException(status_code=422, detail="consent must be recorded before profile")

    if invite.participant_id:
        raise HTTPException(status_code=409, detail="profile already created for this invite")

    if not EMAIL_RE.match(body.email):
        raise HTTPException(status_code=422, detail="invalid email address")
    if body.specialty not in SPECIALTIES:
        raise HTTPException(status_code=422, detail=f"specialty must be one of {sorted(SPECIALTIES)}")

    participant_id = participant_id_for_index(invite.reviewer_index)
    now = datetime.now(UTC)
    session.add(
        StudyParticipant(
            participant_id=participant_id,
            reviewer_index=invite.reviewer_index,
            full_name=body.full_name.strip(),
            email=body.email.strip(),
            phone=body.phone.strip() if body.phone else None,
            registration_number=body.registration_number.strip(),
            specialty=body.specialty,
            years_in_oncology=body.years_in_oncology,
            institution=body.institution.strip(),
            has_uptodate=body.has_uptodate,
            has_nccn=body.has_nccn,
            ai_familiarity=body.ai_familiarity,
            created_at=now,
        )
    )
    consent.participant_id = participant_id
    invite.participant_id = participant_id
    invite.used_at = now
    session.flush()
    return EnrollTokenOut(token=mint_session_token(participant_id), participant_id=participant_id)


@router.post("/enroll/resume", response_model=EnrollTokenOut)
def enroll_resume(
    body: EnrollResumeIn,
    request: Request,
    session: Session = Depends(get_session),
) -> EnrollTokenOut:
    ip = _client_ip(request)
    if rate_limit_exceeded(ip):
        raise HTTPException(status_code=429, detail="too many attempts; try again later")

    invite = invite_from_code(session, body.code)
    if invite is None or invite.participant_id is None:
        record_failed_attempt(ip)
        raise HTTPException(status_code=404, detail=GENERIC_RESUME_ERROR)

    participant = session.get(StudyParticipant, invite.participant_id)
    if participant is None or participant.email.lower() != body.email.strip().lower():
        record_failed_attempt(ip)
        raise HTTPException(status_code=404, detail=GENERIC_RESUME_ERROR)

    return EnrollTokenOut(
        token=mint_session_token(participant.participant_id),
        participant_id=participant.participant_id,
    )


@router.get("/me", response_model=MeScheduleOut)
def enroll_me(
    participant_id: str = Depends(require_participant_token),
    session: Session = Depends(get_session),
    loaded: LoadedCaseSet = Depends(get_case_set),
) -> MeScheduleOut:
    participant = session.get(StudyParticipant, participant_id)
    if participant is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    cases = loaded.case_set.cases
    case_ids = [c.case_id for c in cases]
    pairs = participant_case_schedule(participant.reviewer_index, case_ids)
    labels = {c.case_id: c.label for c in cases}

    submitted = session.scalars(
        select(StudyEvent.case_id)
        .where(
            StudyEvent.participant_id == participant_id,
            StudyEvent.event_type == "case_submitted",
        )
        .distinct()
    ).all()

    return MeScheduleOut(
        participant_id=participant_id,
        reviewer_index=participant.reviewer_index,
        unreviewed=loaded.unreviewed,
        items=[ScheduleItem(case_id=c, arm=a, label=labels[c]) for c, a in pairs],
        completed_case_ids=list(submitted),
    )


@router.post("/withdraw", status_code=204)
def enroll_withdraw(
    participant_id: str = Depends(require_participant_token),
    session: Session = Depends(get_session),
) -> None:
    participant = session.get(StudyParticipant, participant_id)
    if participant is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    if participant.withdrawn_at is None:
        participant.withdrawn_at = datetime.now(UTC)
        session.flush()


@router.get("/admin/participants.csv")
def admin_participants_csv(
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> PlainTextResponse:
    rows = session.scalars(select(StudyParticipant).order_by(StudyParticipant.participant_id)).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "participant_id",
            "reviewer_index",
            "full_name",
            "email",
            "phone",
            "registration_number",
            "specialty",
            "years_in_oncology",
            "institution",
            "has_uptodate",
            "has_nccn",
            "ai_familiarity",
            "created_at",
            "withdrawn_at",
        ]
    )
    for p in rows:
        writer.writerow(
            [
                p.participant_id,
                p.reviewer_index,
                p.full_name,
                p.email,
                p.phone or "",
                p.registration_number,
                p.specialty,
                p.years_in_oncology,
                p.institution,
                p.has_uptodate,
                p.has_nccn,
                p.ai_familiarity,
                p.created_at.isoformat(),
                p.withdrawn_at.isoformat() if p.withdrawn_at else "",
            ]
        )
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@router.get("/admin/events.csv")
def admin_events_csv(
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> PlainTextResponse:
    rows = session.scalars(
        select(StudyEvent).order_by(StudyEvent.client_ts, StudyEvent.server_ts)
    ).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "participant_id",
            "session_id",
            "case_id",
            "arm",
            "event_type",
            "payload",
            "client_ts",
            "server_ts",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                str(r.id),
                r.participant_id,
                r.session_id,
                r.case_id,
                r.arm,
                r.event_type,
                r.payload,
                r.client_ts.isoformat(),
                r.server_ts.isoformat(),
            ]
        )
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


__all__ = ["require_participant_token", "router"]