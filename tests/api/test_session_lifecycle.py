"""Transaction boundary for API requests.

`tests/api/test_routes.py` overrides `get_store`, so `get_session` -- the only
place the commit/rollback decision is made -- never runs there. That gap is how
a version shipped in which every write through the API was silently discarded:
`CaseStore` flushes and never commits by design, and `get_session` went from
`yield` straight to `close()`, which rolls back.

The failure was invisible from the outside. Flush assigns the primary key and
the server defaults, so `POST /api/cases` answered 200 with a real id and a real
`created_at`, and the next request for that id answered 404.
"""

from __future__ import annotations

import pytest

from secondlook.api import deps


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


@pytest.fixture
def fake(monkeypatch) -> FakeSession:
    session = FakeSession()
    monkeypatch.setattr(deps, "_engine", lambda url: object())
    monkeypatch.setattr(deps, "Session", lambda engine: session)
    return session


def _drive(gen, exc: Exception | None = None):
    next(gen)
    if exc is None:
        with pytest.raises(StopIteration):
            next(gen)
    else:
        with pytest.raises(type(exc)):
            gen.throw(exc)


class TestTransactionBoundary:
    def test_a_successful_request_commits(self, fake):
        """The regression. Without this the row is flushed, the id comes back
        populated, and close() rolls it away."""
        _drive(deps.get_session())
        assert fake.calls == ["commit", "close"]

    def test_a_failing_request_rolls_back_and_does_not_commit(self, fake):
        _drive(deps.get_session(), RuntimeError("handler blew up"))
        assert fake.calls == ["rollback", "close"]
        assert "commit" not in fake.calls

    def test_the_exception_still_reaches_the_caller(self, fake):
        """Rolling back must not turn a 500 into a silent success."""
        gen = deps.get_session()
        next(gen)
        with pytest.raises(ValueError, match="boom"):
            gen.throw(ValueError("boom"))

    def test_the_session_is_always_closed(self, fake):
        _drive(deps.get_session())
        assert fake.calls[-1] == "close"


class TestEnginePooling:
    def test_one_engine_is_reused_across_requests(self, monkeypatch):
        """`create_engine` builds a connection pool. One per request meant a new
        pool and a new TCP connection every call, discarded before reuse."""
        built: list[str] = []

        def fake_create_engine(url):
            built.append(url)
            return object()

        monkeypatch.setattr("sqlalchemy.create_engine", fake_create_engine)
        deps._engine.cache_clear()
        first = deps._engine("postgresql+psycopg://x/y")
        second = deps._engine("postgresql+psycopg://x/y")
        assert first is second
        assert built == ["postgresql+psycopg://x/y"]

    def test_a_different_url_gets_its_own_engine(self, monkeypatch):
        monkeypatch.setattr("sqlalchemy.create_engine", lambda url: object())
        deps._engine.cache_clear()
        assert deps._engine("postgresql+psycopg://a/b") is not deps._engine(
            "postgresql+psycopg://c/d"
        )
