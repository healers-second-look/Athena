"""Shared FastAPI dependencies. No business logic."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from functools import lru_cache

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from secondlook.case.store import CaseStore
from secondlook.signals.registry import dispatch

DEFAULT_DATABASE_URL = "postgresql+psycopg://athena:athena@localhost:5432/athena"


def database_url() -> str:
    """ATHENA_DATABASE_URL, normalised to the psycopg (v3) driver.

    Hosted Postgres (Railway, Neon, Render) hands out ``postgres://`` or
    ``postgresql://`` URLs, which SQLAlchemy maps to psycopg2 -- not installed
    here. Rewriting the scheme lets the platform's URL be pasted as-is.
    """
    url = os.environ.get("ATHENA_DATABASE_URL", DEFAULT_DATABASE_URL)
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@lru_cache(maxsize=4)
def _engine(url: str):
    """One engine (and connection pool) per URL for the process lifetime.

    Creating an engine per request opened a fresh pool every time, which a
    hosted Postgres with a small connection cap runs out of quickly.
    """
    from sqlalchemy import create_engine

    return create_engine(url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    engine = _engine(database_url())
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
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
    from secondlook.tier1.graph_connection import connect_graph

    return connect_graph()


def get_llm_client():
    from secondlook.synthesis.llm_client import get_llm_client as _get_llm_client

    return _get_llm_client()


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
