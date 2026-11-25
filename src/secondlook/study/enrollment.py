"""Study enrollment: invites, consent, participant profiles, session tokens.

Identifying details live only in ``study_participants``; events keep the
pseudonymous ``participant_id``. Plaintext invite codes are never stored or
logged — only a peppered SHA-256 hash.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, TIMESTAMP, Boolean, Index, Integer, Text, Uuid, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class EnrollmentBase(DeclarativeBase):
    """Metadata for study *participant* (clinician) records, kept apart on purpose.

    POLICY.md section 5.4 forbids direct identifiers in the patient-record
    schema (``secondlook.case.models.Base``), and a schema test enforces that.
    Enrolled doctors must give their name, email and registration number to
    consent, so those tables cannot live there -- they sit on this separate
    metadata instead. Study events stay on the case Base and carry only the
    pseudonymous participant id; nothing here may ever hold patient data.
    """


CODE_PEPPER_ENV = "STUDY_CODE_PEPPER"
SESSION_SECRET_ENV = "STUDY_SESSION_SECRET"
REQUIRE_ENROLLMENT_ENV = "STUDY_REQUIRE_ENROLLMENT"
CASES_PER_ARM_ENV = "STUDY_CASES_PER_ARM"

INVITE_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
INVITE_CODE_PATTERN = re.compile(
    r"^ATH-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{2}$"
)

CONSENT_VERSION = "0.1"
CONSENT_FILENAME = "athena-vs-usual-care-consent-v0.1.md"

REQUIRED_CHECKBOXES: tuple[tuple[str, str], ...] = (
    ("read_understood", "I have read and understood the participant information above."),
    (
        "voluntary_withdraw",
        "I understand that participation is voluntary and I may withdraw at any time.",
    ),
    (
        "synthetic_not_advice",
        "I understand that all cases are synthetic and that study outputs are not clinical advice.",
    ),
    (
        "data_use",
        "I consent to the collection and use of my data as described above.",
    ),
)

OPTIONAL_CHECKBOXES: tuple[tuple[str, str], ...] = (
    (
        "screen_recording",
        "I consent to optional screen recording during the study sessions.",
    ),
)

ALL_CHECKBOX_IDS = frozenset(id_ for id_, _ in REQUIRED_CHECKBOXES + OPTIONAL_CHECKBOXES)
REQUIRED_CHECKBOX_IDS = frozenset(id_ for id_, _ in REQUIRED_CHECKBOXES)

SPECIALTIES = frozenset(
    {
        "medical_oncology",
        "surgical_oncology",
        "radiation_oncology",
        "oncology_resident",
        "other",
    }
)

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

GENERIC_CODE_ERROR = "Invalid or unusable invite code."
GENERIC_RESUME_ERROR = "Could not resume with the details provided."

ENROLLMENT_TOKEN_MINUTES = 30
SESSION_TOKEN_DAYS = 14

TOKEN_TYPE_ENROLL = "enroll"
TOKEN_TYPE_SESSION = "session"


def enrollment_required() -> bool:
    return os.environ.get(REQUIRE_ENROLLMENT_ENV, "").strip().lower() in {"1", "true", "yes"}


def _require_pepper() -> str:
    pepper = os.environ.get(CODE_PEPPER_ENV, "").strip()
    if not pepper:
        raise RuntimeError(f"{CODE_PEPPER_ENV} is unset; invite codes cannot be verified.")
    return pepper


def _require_session_secret() -> str:
    secret = os.environ.get(SESSION_SECRET_ENV, "").strip()
    if not secret:
        raise RuntimeError(f"{SESSION_SECRET_ENV} is unset; session tokens cannot be issued.")
    return secret


def normalize_invite_code(code: str) -> str:
    return code.upper().replace(" ", "").replace("-", "")


def format_invite_code(normalized: str) -> str:
    """Display form ATH-XXXX-XX from 7-char body (ATH + 4 + 2) or 6 random chars."""
    body = normalized
    if body.startswith("ATH"):
        body = body[3:]
    if len(body) != 6:
        raise ValueError("invite code body must be 6 characters")
    return f"ATH-{body[:4]}-{body[4:]}"


def generate_invite_code() -> tuple[str, str]:
    """Return (display_code, normalized_form) for storage hashing."""
    chars = "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(6))
    normalized = f"ATH{chars}"
    return format_invite_code(normalized), normalized


def hash_invite_code(normalized: str, *, pepper: str | None = None) -> str:
    pepper = pepper or _require_pepper()
    return hashlib.sha256(f"{pepper}{normalized}".encode()).hexdigest()


def participant_id_for_index(reviewer_index: int) -> str:
    return f"P{reviewer_index + 1:02d}"


class StudyInvite(EnrollmentBase):
    __tablename__ = "study_invites"
    __table_args__ = (Index("ix_study_invites_code_hash", "code_hash", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    reviewer_index: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    participant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class StudyParticipant(EnrollmentBase):
    __tablename__ = "study_participants"

    participant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    reviewer_index: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_number: Mapped[str] = mapped_column(Text, nullable=False)
    specialty: Mapped[str] = mapped_column(Text, nullable=False)
    years_in_oncology: Mapped[int] = mapped_column(Integer, nullable=False)
    institution: Mapped[str] = mapped_column(Text, nullable=False)
    has_uptodate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_nccn: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ai_familiarity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class StudyConsent(EnrollmentBase):
    __tablename__ = "study_consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invite_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    participant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_version: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    signed_name: Mapped[str] = mapped_column(Text, nullable=False)
    answers: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


def consent_markdown_path() -> Path:
    served = Path(__file__).resolve().parent / "consent" / CONSENT_FILENAME
    if served.is_file():
        return served
    repo = Path(__file__).resolve().parents[3] / "docs" / "research" / CONSENT_FILENAME
    return repo


def load_consent_markdown() -> str:
    return consent_markdown_path().read_text(encoding="utf-8")


def consent_text_sha256() -> str:
    return hashlib.sha256(load_consent_markdown().encode()).hexdigest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def mint_token(payload: dict[str, Any], *, secret: str | None = None) -> str:
    secret = secret or _require_session_secret()
    body = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(sig)}"


def verify_token(token: str, *, expected_type: str, secret: str | None = None) -> dict[str, Any]:
    secret = secret or _require_session_secret()
    try:
        body, sig_part = token.rsplit(".", 1)
    except ValueError as exc:
        raise InvalidToken("malformed token") from exc
    expected_sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    try:
        given_sig = _b64url_decode(sig_part)
    except Exception as exc:
        raise InvalidToken("malformed token") from exc
    if not hmac.compare_digest(expected_sig, given_sig):
        raise InvalidToken("invalid token")
    try:
        payload = json.loads(_b64url_decode(body))
    except Exception as exc:
        raise InvalidToken("malformed token") from exc
    if payload.get("typ") != expected_type:
        raise InvalidToken("invalid token type")
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or time.time() > float(exp):
        raise InvalidToken("token expired")
    return payload


class InvalidToken(ValueError):
    pass


def mint_enrollment_token(invite_id: uuid.UUID) -> str:
    exp = time.time() + ENROLLMENT_TOKEN_MINUTES * 60
    return mint_token({"typ": TOKEN_TYPE_ENROLL, "invite_id": str(invite_id), "exp": exp})


def mint_session_token(participant_id: str) -> str:
    exp = time.time() + SESSION_TOKEN_DAYS * 86400
    return mint_token({"typ": TOKEN_TYPE_SESSION, "participant_id": participant_id, "exp": exp})


def invite_from_code(session: Session, code: str) -> StudyInvite | None:
    normalized = normalize_invite_code(code.strip())
    if not normalized.startswith("ATH") or len(normalized) != 9:
        return None
    code_hash = hash_invite_code(normalized)
    return session.scalars(select(StudyInvite).where(StudyInvite.code_hash == code_hash)).first()


def invite_is_usable(invite: StudyInvite, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if invite.revoked:
        return False
    if invite.expires_at is not None:
        expires_at = invite.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            return False
    return True


@dataclass
class RateLimitBucket:
    failures: int = 0
    window_start: float = 0.0


_RATE_LIMIT: dict[str, RateLimitBucket] = {}
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 3600.0


def reset_rate_limits() -> None:
    _RATE_LIMIT.clear()


def record_failed_attempt(client_ip: str) -> int:
    now = time.time()
    bucket = _RATE_LIMIT.get(client_ip)
    if bucket is None or now - bucket.window_start >= _RATE_LIMIT_WINDOW:
        bucket = RateLimitBucket(failures=0, window_start=now)
    bucket.failures += 1
    _RATE_LIMIT[client_ip] = bucket
    return bucket.failures


def rate_limit_exceeded(client_ip: str) -> bool:
    bucket = _RATE_LIMIT.get(client_ip)
    if bucket is None:
        return False
    now = time.time()
    if now - bucket.window_start >= _RATE_LIMIT_WINDOW:
        return False
    return bucket.failures >= _RATE_LIMIT_MAX


def cases_per_arm_for_usual_vs(case_count: int) -> int:
    raw = os.environ.get(CASES_PER_ARM_ENV, "4").strip()
    try:
        requested = int(raw)
    except ValueError:
        requested = 4
    return max(1, min(requested, case_count // 2))


__all__ = [
    "ALL_CHECKBOX_IDS",
    "CONSENT_VERSION",
    "EMAIL_RE",
    "GENERIC_CODE_ERROR",
    "GENERIC_RESUME_ERROR",
    "InvalidToken",
    "OPTIONAL_CHECKBOXES",
    "REQUIRED_CHECKBOXES",
    "REQUIRED_CHECKBOX_IDS",
    "SPECIALTIES",
    "StudyConsent",
    "StudyInvite",
    "StudyParticipant",
    "cases_per_arm_for_usual_vs",
    "consent_text_sha256",
    "enrollment_required",
    "format_invite_code",
    "generate_invite_code",
    "hash_invite_code",
    "invite_from_code",
    "invite_is_usable",
    "load_consent_markdown",
    "mint_enrollment_token",
    "mint_session_token",
    "normalize_invite_code",
    "participant_id_for_index",
    "rate_limit_exceeded",
    "record_failed_attempt",
    "reset_rate_limits",
    "verify_token",
]
