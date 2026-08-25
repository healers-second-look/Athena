"""In-memory session store -- issue #103, Phase 1 and 3.

Sessions live in memory for the demo. Each session holds its model choice,
active attachments, KG context, and the message history.

Persistence across a refresh comes from the session id being in the URL
(`/chat/:id`): the client refetches `GET /sessions/{id}` on mount and
restores the history from here. There is no localStorage mirror -- an
earlier version of this docstring claimed one, and none exists anywhere in
`web/src`. That matters because it sets the real durability boundary: a
refresh survives, a BACKEND RESTART does not, and issue #103's Phase 1 bar
("survives a page refresh") is met by the round trip rather than by
anything on the client.

No database dependency -- the chat surface is standalone.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from secondlook.chat.models import DEFAULT_MODEL_ID


@dataclass
class Session:
    id: str
    model_id: str = DEFAULT_MODEL_ID
    attachment_ids: list[str] = field(default_factory=list)
    context_id: str | None = None
    history: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str, **meta) -> dict:
        msg = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "timestamp": time.time(),
            **meta,
        }
        self.history.append(msg)
        self.updated_at = time.time()
        return msg

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "model_id": self.model_id,
            "attachment_ids": self.attachment_ids,
            "context_id": self.context_id,
            "history": self.history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# In-memory store
_sessions: dict[str, Session] = {}


def create_session(**kwargs) -> Session:
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, **kwargs)
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> Session | None:
    return _sessions.get(session_id)


def list_sessions() -> list[Session]:
    return sorted(_sessions.values(), key=lambda s: s.updated_at, reverse=True)


def update_session(session_id: str, **kwargs) -> Session | None:
    session = _sessions.get(session_id)
    if session is None:
        return None
    for key, value in kwargs.items():
        if hasattr(session, key) and key != "id":
            setattr(session, key, value)
    session.updated_at = time.time()
    return session


def delete_session(session_id: str) -> bool:
    return _sessions.pop(session_id, None) is not None


__all__ = [
    "Session",
    "create_session",
    "delete_session",
    "get_session",
    "list_sessions",
    "update_session",
]
