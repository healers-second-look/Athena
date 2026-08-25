"""Chat API routes -- issue #103, Phases 1-6.

Endpoints:
  POST   /api/chat/sessions              -- create a session
  GET    /api/chat/sessions              -- list sessions
  GET    /api/chat/sessions/{id}         -- get session
  PATCH  /api/chat/sessions/{id}         -- update config (model, attachments, context)
  DELETE /api/chat/sessions/{id}         -- delete session
  POST   /api/chat/sessions/{id}/turns   -- send a message, get a reply

  GET    /api/chat/models                -- available models
  GET    /api/chat/attachments           -- available plugins/skills/modes
  GET    /api/chat/contexts              -- available KG contexts
  GET    /api/chat/contexts/{context_id}/graph -- Phase 5 FalkorDB subgraph & Cypher
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from secondlook.chat.engine import run_turn
from secondlook.chat.knowledge import GraphUnavailable, fetch_subgraph, list_contexts
from secondlook.chat.models import list_models
from secondlook.chat.plugins import list_attachments
from secondlook.chat.session import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    update_session,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# --- Pydantic schemas ---


class CreateSessionRequest(BaseModel):
    model_id: str | None = None
    attachment_ids: list[str] | None = None
    context_id: str | None = None


class UpdateSessionRequest(BaseModel):
    model_id: str | None = None
    attachment_ids: list[str] | None = None
    context_id: str | None = None


class TurnRequest(BaseModel):
    message: str


# --- Session endpoints ---


@router.post("/sessions")
def create_session_endpoint(req: CreateSessionRequest | None = None):
    kwargs = {}
    if req:
        if req.model_id:
            kwargs["model_id"] = req.model_id
        if req.attachment_ids is not None:
            kwargs["attachment_ids"] = req.attachment_ids
        if req.context_id is not None:
            kwargs["context_id"] = req.context_id
    session = create_session(**kwargs)
    return session.as_dict()


@router.get("/sessions")
def list_sessions_endpoint():
    return [s.as_dict() for s in list_sessions()]


@router.get("/sessions/{session_id}")
def get_session_endpoint(session_id: str):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.as_dict()


@router.patch("/sessions/{session_id}")
def update_session_endpoint(session_id: str, req: UpdateSessionRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    session = update_session(session_id, **updates)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.as_dict()


@router.delete("/sessions/{session_id}")
def delete_session_endpoint(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


# --- Turn endpoint (Phases 1-4 & 6) ---


@router.post("/sessions/{session_id}/turns")
def send_turn(session_id: str, req: TurnRequest):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Record user message
    user_msg = session.add_message("user", req.message)

    # Run the engine
    result = run_turn(
        req.message,
        model_id=session.model_id,
        attachment_ids=session.attachment_ids,
        context_id=session.context_id,
    )

    # Record assistant message with metadata and retrieved sources
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

    return {
        "user_message": user_msg,
        "assistant_message": assistant_msg,
        "turn": result.as_dict(),
    }


# --- Catalog endpoints ---


@router.get("/models")
def get_models():
    return [m.as_dict() for m in list_models()]


@router.get("/attachments")
def get_attachments():
    return [a.as_dict() for a in list_attachments()]


@router.get("/contexts")
def get_contexts():
    return [c.as_dict() for c in list_contexts()]


# --- Phase 5 Graph Subgraph endpoint ---


@router.get("/contexts/{context_id:path}/graph")
def get_context_graph(context_id: str):
    """Fetch nodes, edges, and Cypher query for `context_id` (Phase 5)."""
    try:
        return fetch_subgraph(context_id)
    except GraphUnavailable as exc:
        raise HTTPException(status_code=500, detail=f"Graph query failed: {exc}") from exc


__all__ = ["router"]
