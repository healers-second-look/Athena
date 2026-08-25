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

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from secondlook.api.auth import API_KEY_HEADER, require_api_key
from secondlook.chat.engine import run_turn
from secondlook.chat.knowledge import (
    GraphUnavailable,
    fetch_subgraph,
    is_valid_context_id,
    list_contexts,
)
from secondlook.chat.models import get_model_spec, list_models
from secondlook.chat.plugins import list_attachments, unknown_ids
from secondlook.chat.session import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    update_session,
)
from secondlook.synthesis.llm_client import LLMClientError

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


def _validate_config(
    model_id: str | None,
    attachment_ids: list[str] | None,
    context_id: str | None,
) -> None:
    """Reject unknown ids at the boundary, with 422 and a usable message.

    `unknown_ids` existed, was exported and was unit-tested, and nothing
    ever called it -- so a session could be configured with attachments
    that do not exist. Nothing errored: `apply_attachments` filters to the
    registry, so the ids sat in the session, showed as attached, and did
    nothing. A toggle that reports itself as on and has no effect is worse
    than one that is missing, because the user account for it in how they
    read the answer.
    """
    if model_id is not None:
        if get_model_spec(model_id) is None:
            known = ", ".join(spec.id for spec in list_models())
            raise HTTPException(
                status_code=422,
                detail=f"unknown model {model_id!r}; known models are {known}",
            )
    if attachment_ids:
        unknown = unknown_ids(attachment_ids)
        if unknown:
            known = ", ".join(a.id for a in list_attachments())
            raise HTTPException(
                status_code=422,
                detail=f"unknown attachment(s) {', '.join(unknown)}; known are {known}",
            )
    if context_id is not None and not is_valid_context_id(context_id):
        raise HTTPException(
            status_code=422,
            detail=(
                f"malformed context id {context_id!r}; expected 'gene:<symbol>', "
                "'disease:<name>' or 'graph:<name>'"
            ),
        )


# --- Session endpoints ---


@router.post("/sessions")
def create_session_endpoint(req: CreateSessionRequest | None = None):
    kwargs = {}
    if req:
        _validate_config(req.model_id, req.attachment_ids, req.context_id)
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
    _validate_config(
        updates.get("model_id"),
        updates.get("attachment_ids"),
        updates.get("context_id"),
    )
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
def send_turn(
    session_id: str,
    req: TurnRequest,
    x_athena_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not req.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty")

    # This is the only endpoint in the service that can spend money, and it
    # shipped with no auth at all while `cases`/`findings` writes required a
    # key -- an open proxy to the Anthropic API for anyone who could reach
    # the port.
    #
    # Gating only the paid providers rather than the whole router is
    # deliberate: the offline mock models are the entire Phase 1-6 demo, and
    # they cost nothing, reach no network, and are what a reviewer runs. They
    # stay open; the paid path does not. `require_api_key` is a no-op when
    # ATHENA_API_AUTH_DISABLED=true, so local development is unaffected.
    spec = get_model_spec(session.model_id)
    if spec is not None and spec.provider != "mock":
        require_api_key(x_athena_api_key)

    # Run the engine BEFORE recording anything. The user message used to be
    # appended first, so a turn that raised left it in history with no reply
    # -- and the client, having got a 500, resent it and duplicated it. A
    # turn either lands as a pair or does not land at all.
    try:
        result = run_turn(
            req.message,
            model_id=session.model_id,
            attachment_ids=session.attachment_ids,
            context_id=session.context_id,
        )
    except LLMClientError as exc:
        # The model is unreachable or unconfigured. That is a bad request
        # about this session's configuration, not an internal fault, and it
        # is routinely reachable: `list_models` deliberately lists models
        # this deployment cannot serve so the picker can explain them.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    user_msg = session.add_message("user", req.message)

    # Record assistant message with metadata and retrieved sources
    assistant_msg = session.add_message(
        "assistant",
        result.content,
        entities=result.entities,
        notes=result.notes,
        context_lines=result.context_lines,
        sources=result.sources,
        sources_count=result.sources_count,
        retrieval_failed=result.retrieval_failed,
        retrieval_error=result.retrieval_error,
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
        # 503, not 500: the graph store is a dependency that is down, which
        # is a different thing for a client to retry than a bug in here.
        raise HTTPException(status_code=503, detail=f"Graph unavailable: {exc}") from exc


__all__ = ["router"]
