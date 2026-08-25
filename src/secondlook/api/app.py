"""Athena REST API (issue #59). MCP is a different transport over `query/`."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from secondlook.api.auth import configure_auth
from secondlook.api.routes import cases, findings
from secondlook.api.routes import chat as chat_routes
from secondlook.api.routes import timeline as timeline_routes

DEFAULT_BIND_HOST = "127.0.0.1"

# docker-compose.yml deliberately serves the frontend (nginx, port 8080) and
# this API (port 8000) on different ports -- see web/Dockerfile's comment on
# why VITE_API_BASE has to be a browser-reachable URL, not Docker's internal
# DNS. Different ports means different origins by browser rules, so without
# CORS headers here, every fetch the frontend makes is blocked before it
# reaches any route -- confirmed live (issue #100), not assumed: the API's
# own responses looked fine over curl, which doesn't enforce CORS, while the
# actual built frontend in an actual browser failed on every single request.
#
# Two frontends share this API: the nginx-served case dashboard (Subsystem
# M, port 8080 by default) and the chat interface (issue #103), run via
# `vite dev` on its default ports (5173/5174) during active development --
# neither is optional, so both are in the default list.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:8080,http://localhost:5173," "http://localhost:5174,http://127.0.0.1:5173"
)


def _cors_origins() -> list[str]:
    raw = os.environ.get("ATHENA_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    configure_auth()
    app = FastAPI(
        title="Athena REST API",
        version="1.0.0",
        description=(
            "System of record for case writes. Auth is an API key on POST routes; "
            "MCP remote bind uses a separate ATHENA_MCP_API_KEY bearer token."
        ),
    )
    # allow_methods includes PATCH/DELETE for the chat session endpoints
    # (routes/chat.py: PATCH /sessions/{id}, DELETE /sessions/{id}) --
    # the cases/findings routes only ever needed GET/POST, but a CORS
    # preflight rejection on PATCH/DELETE would silently break session
    # editing and deletion from the chat frontend the same way issue #100
    # silently broke every request before CORSMiddleware existed at all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Athena-Api-Key"],
    )
    app.include_router(cases.router)
    app.include_router(findings.router)
    app.include_router(chat_routes.router)
    app.include_router(timeline_routes.router)
    return app


def main(argv: list[str] | None = None) -> int:
    del argv
    import uvicorn

    host = os.environ.get("ATHENA_API_HOST", DEFAULT_BIND_HOST)
    port = int(os.environ.get("ATHENA_API_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port)
    return 0
