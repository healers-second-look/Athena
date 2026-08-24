"""Shared FastAPI dependencies. No business logic."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from functools import cache

from fastapi import Depends, HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from secondlook.case.store import CaseStore
from secondlook.signals.registry import dispatch

DEFAULT_DATABASE_URL = "postgresql+psycopg://athena:athena@localhost:5432/athena"


@cache
def _engine(url: str) -> Engine:
    """One engine per URL, for the life of the process.

    `create_engine` builds a connection pool. Building one per request meant a
    new pool -- and a new TCP connection to Postgres -- on every call, and
    discarding it before it could be reused, which is the opposite of what a
    pool is for.
    """
    from sqlalchemy import create_engine

    return create_engine(url)


def get_session() -> Iterator[Session]:
    """A request-scoped session that COMMITS when the request succeeds.

    It previously yielded and then went straight to `session.close()`. Close
    rolls back an open transaction, and `CaseStore` deliberately flushes
    without ever committing -- it leaves transaction control to its caller,
    which is this function. So every write through the API was discarded.

    It did not look like a failure, which is why it survived. The flush had
    already assigned the primary key and the server defaults, so the response
    came back fully populated with a real id and a real `created_at`. The
    caller saw a successful create; the row was never there. The next request
    for that id returned 404.

    No test caught it because `tests/api/test_routes.py` overrides `get_store`
    with a store built on its own session, so this function -- the only place
    the transaction boundary is decided -- never executes under test.
    """
    session = Session(_engine(os.environ.get("ATHENA_DATABASE_URL", DEFAULT_DATABASE_URL)))
    try:
        yield session
        session.commit()
    except Exception:  # noqa: BLE001 -- re-raised, not swallowed
        # The handler already failed; the request must not half-persist.
        session.rollback()
        raise
    finally:
        session.close()


def get_store(session: Session = Depends(get_session)) -> CaseStore:
    return CaseStore(session)


def get_existing_case(case_id: uuid.UUID, store: CaseStore = Depends(get_store)):
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no case with id {case_id}")
    return case


def get_existing_finding(finding_id: uuid.UUID, store: CaseStore = Depends(get_store)):
    finding = store.get_finding(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail=f"no finding with id {finding_id}")
    return finding


def get_graph():
    return None


def get_llm_client():
    return None


def get_dispatch():
    return dispatch


__all__ = [
    "get_dispatch",
    "get_existing_case",
    "get_existing_finding",
    "get_graph",
    "get_llm_client",
    "get_session",
    "get_store",
]
