"""CLI to create, list, and revoke study invite codes.

Plaintext codes are printed only by ``create`` — nowhere else.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from secondlook.api.deps import database_url
from secondlook.study.enrollment import (
    StudyInvite,
    generate_invite_code,
    hash_invite_code,
    participant_id_for_index,
)


def _engine():
    return create_engine(database_url())


def _next_free_indices(session: Session, count: int, start: int | None) -> list[int]:
    used = set(session.scalars(select(StudyInvite.reviewer_index)).all())
    indices: list[int] = []
    candidate = start if start is not None else 0
    while len(indices) < count:
        while candidate in used:
            candidate += 1
        indices.append(candidate)
        used.add(candidate)
        candidate += 1
    return indices


def create_invites(
    session: Session,
    n: int,
    *,
    expires_days: int | None = None,
    start_index: int | None = None,
    pepper: str | None = None,
) -> list[tuple[int, str]]:
    """Create ``n`` invites; return (reviewer_index, display_code) pairs."""
    indices = _next_free_indices(session, n, start_index)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=expires_days) if expires_days is not None else None
    out: list[tuple[int, str]] = []
    for idx in indices:
        display, normalized = generate_invite_code()
        invite = StudyInvite(
            code_hash=hash_invite_code(normalized, pepper=pepper),
            reviewer_index=idx,
            created_at=now,
            expires_at=expires_at,
            revoked=False,
        )
        session.add(invite)
        out.append((idx, display))
    session.flush()
    return out


def list_invites(session: Session) -> list[StudyInvite]:
    return list(session.scalars(select(StudyInvite).order_by(StudyInvite.reviewer_index)).all())


def revoke_invite(session: Session, reviewer_index: int) -> bool:
    invite = session.scalars(
        select(StudyInvite).where(StudyInvite.reviewer_index == reviewer_index)
    ).first()
    if invite is None:
        return False
    invite.revoked = True
    session.flush()
    return True


def _cmd_create(args: argparse.Namespace) -> int:
    engine = _engine()
    with Session(engine) as session:
        pairs = create_invites(
            session,
            args.n,
            expires_days=args.expires_days,
            start_index=args.start_index,
        )
        session.commit()
    for idx, code in pairs:
        pid = participant_id_for_index(idx)
        print(f"{idx}\t{code}\t(future {pid})")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    del args
    engine = _engine()
    with Session(engine) as session:
        rows = list_invites(session)
    for invite in rows:
        status = "revoked" if invite.revoked else "active"
        if invite.participant_id:
            status = f"used:{invite.participant_id}"
        exp = invite.expires_at.isoformat() if invite.expires_at else "-"
        print(f"{invite.reviewer_index}\t{status}\texpires={exp}")
    return 0


def _cmd_revoke(args: argparse.Namespace) -> int:
    engine = _engine()
    with Session(engine) as session:
        ok = revoke_invite(session, args.index)
        if not ok:
            print(f"no invite at reviewer_index={args.index}", file=sys.stderr)
            session.rollback()
            return 1
        session.commit()
    print(f"revoked reviewer_index={args.index}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage study invite codes")
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create", help="Create new invite codes")
    create_p.add_argument("--n", type=int, required=True)
    create_p.add_argument("--expires-days", type=int, default=None)
    create_p.add_argument("--start-index", type=int, default=None)
    create_p.set_defaults(func=_cmd_create)

    list_p = sub.add_parser("list", help="List invites (no plaintext codes)")
    list_p.set_defaults(func=_cmd_list)

    revoke_p = sub.add_parser("revoke", help="Revoke invite by reviewer index")
    revoke_p.add_argument("--index", type=int, required=True)
    revoke_p.set_defaults(func=_cmd_revoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
