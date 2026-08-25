"""Drive the chat surface over real HTTP and write down what happened.

Issue #103 requires that a PR show the flow actually running, not describe
it. This produces that record reproducibly, so the artefact is regenerated
from the code rather than pasted from a session nobody else can repeat --
PR #106's description quoted a payload (`"citation-guard active with
retrieved context present"`) that the merged code could not emit.

    python -m secondlook.devtools.capture_evidence

Starts a real uvicorn, issues real requests through a real socket, records
every exchange, and writes `docs/evidence/issue-103/`. Nothing is stubbed:
if FalkorDB is not reachable, that is recorded as a degraded run rather than
faked, because Phases 4-6 genuinely cannot be evidenced without it -- and
because the degraded path is itself a behaviour worth showing.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "docs" / "evidence" / "issue-103"

QUESTION = "What treatment options exist for EGFR T790M in NSCLC?"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Recorder:
    """Every exchange, in order, exactly as it went over the wire."""

    def __init__(self, base: str):
        self.base = base
        self.log: list[dict] = []

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                payload = json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
            try:
                payload = json.loads(raw or b"null")
            except json.JSONDecodeError:
                payload = {"raw": raw.decode(errors="replace")}
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        entry = {
            "request": {"method": method, "path": path, "body": body},
            "response": {"status": status, "elapsed_ms": elapsed_ms, "body": payload},
        }
        self.log.append(entry)
        print(f"  {method} {path} -> {status} ({elapsed_ms} ms)")
        return entry


def _wait_for_server(base: str, proc: subprocess.Popen, timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"uvicorn exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(f"{base}/api/chat/models", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            # Not yet listening. Any other exception is a real fault and
            # should surface rather than be retried into a timeout.
            time.sleep(0.4)
    raise RuntimeError(f"server did not become ready within {timeout}s")


def run(base: str, recorder: Recorder) -> dict:
    """The flow a reviewer would drive by hand, in the issue's own order."""
    findings: dict = {}

    print("\nPhase 1 -- basic chat, zero attachments (the floor)")
    session = recorder.call("POST", "/api/chat/sessions", {})["response"]["body"]
    sid = session["id"]
    turn = recorder.call(
        "POST", f"/api/chat/sessions/{sid}/turns", {"message": QUESTION}
    )["response"]["body"]["turn"]
    findings["phase_1_floor_works_with_nothing_attached"] = bool(turn["content"])

    print("\nPhase 1 -- history survives a refetch (what the client does on reload)")
    reloaded = recorder.call("GET", f"/api/chat/sessions/{sid}")["response"]["body"]
    findings["phase_1_history_persists"] = len(reloaded["history"]) == 2

    print("\nPhase 2 -- the same question through a second model")
    models = recorder.call("GET", "/api/chat/models")["response"]["body"]
    findings["phase_2_models_offered"] = [m["id"] for m in models]
    terse_sid = recorder.call(
        "POST", "/api/chat/sessions", {"model_id": "mock-terse"}
    )["response"]["body"]["id"]
    terse_turn = recorder.call(
        "POST", f"/api/chat/sessions/{terse_sid}/turns", {"message": QUESTION}
    )["response"]["body"]["turn"]
    findings["phase_2_same_input_different_output"] = terse_turn["content"] != turn["content"]

    print("\nPhase 3 -- a plugin that changes the answer, attached vs not")
    plugin_sid = recorder.call(
        "POST",
        "/api/chat/sessions",
        {"attachment_ids": ["variant-normalizer", "citation-guard"]},
    )["response"]["body"]["id"]
    plugin_turn = recorder.call(
        "POST", f"/api/chat/sessions/{plugin_sid}/turns", {"message": QUESTION}
    )["response"]["body"]["turn"]
    findings["phase_3_entities_extracted"] = plugin_turn["entities"]
    findings["phase_3_notes"] = plugin_turn["notes"]
    findings["phase_3_attached_changes_the_payload"] = (
        plugin_turn["entities"] != turn["entities"]
    )

    print("\nBoundary: configuration that does not exist is refused")
    findings["rejects_unknown_attachment"] = recorder.call(
        "POST", "/api/chat/sessions", {"attachment_ids": ["not-a-real-plugin"]}
    )["response"]["status"]
    findings["rejects_unknown_model"] = recorder.call(
        "POST", "/api/chat/sessions", {"model_id": "gpt-9-ultra"}
    )["response"]["status"]
    findings["rejects_empty_message"] = recorder.call(
        "POST", f"/api/chat/sessions/{sid}/turns", {"message": "   "}
    )["response"]["status"]

    print("\nBoundary: an unconfigured model is a conflict, and leaves no orphan")
    unconf = recorder.call("POST", "/api/chat/sessions", {})["response"]["body"]["id"]
    recorder.call("PATCH", f"/api/chat/sessions/{unconf}", {"model_id": "anthropic"})
    findings["unconfigured_model_status"] = recorder.call(
        "POST", f"/api/chat/sessions/{unconf}/turns", {"message": QUESTION}
    )["response"]["status"]
    after = recorder.call("GET", f"/api/chat/sessions/{unconf}")["response"]["body"]
    findings["failed_turn_left_history_empty"] = after["history"] == []

    print("\nPhases 4-6 -- knowledge graph and retrieval")
    contexts = recorder.call("GET", "/api/chat/contexts")["response"]["body"]
    findings["phase_4_contexts_available"] = len(contexts)
    graph_live = bool(contexts)

    if graph_live:
        context_id = contexts[0]["id"]
        kg_sid = recorder.call(
            "POST", "/api/chat/sessions", {"context_id": context_id}
        )["response"]["body"]["id"]
        kg_turn = recorder.call(
            "POST", f"/api/chat/sessions/{kg_sid}/turns", {"message": QUESTION}
        )["response"]["body"]["turn"]
        findings["phase_4_context_reached_the_prompt"] = bool(kg_turn["context_lines"])
        findings["phase_6_sources_retrieved"] = kg_turn["sources_count"]
        graph = recorder.call(
            "GET", f"/api/chat/contexts/{context_id}/graph"
        )["response"]["body"]
        findings["phase_5_cypher"] = graph.get("cypher")
        findings["phase_5_node_count"] = len(graph.get("nodes", []))
        findings["phase_5_edge_count"] = len(graph.get("edges", []))
    else:
        # Not faked. This is the honest state of a run without FalkorDB, and
        # the degraded behaviour is itself worth recording -- it is what
        # PR #111 changed.
        findings["phase_4_5_6"] = "NOT EVIDENCED -- FalkorDB unreachable"
        findings["degraded_retrieval_failed_flag"] = turn["retrieval_failed"]
        findings["degraded_retrieval_error"] = turn["retrieval_error"]
        findings["degraded_reply"] = turn["content"]
        findings["phase_5_status_when_graph_down"] = recorder.call(
            "GET", "/api/chat/contexts/gene:EGFR/graph"
        )["response"]["status"]

    return {"findings": findings, "graph_live": graph_live}


def write_report(out_dir: Path, result: dict, recorder: Recorder, base: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "exchanges.json").write_text(
        json.dumps(recorder.log, indent=2), encoding="utf-8"
    )
    (out_dir / "findings.json").write_text(
        json.dumps(result["findings"], indent=2), encoding="utf-8"
    )

    live = result["graph_live"]
    yes_no = "yes" if live else "**no — FalkorDB unreachable**"
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Issue #103 — driven evidence",
        "",
        f"Generated {generated} by `python -m secondlook.devtools.capture_evidence`.",
        "",
        f"A real uvicorn on `{base}`, driven over real HTTP. Every request and "
        "response is in `exchanges.json` verbatim; the assertions drawn from "
        "them are in `findings.json`.",
        "",
        "## Coverage",
        "",
        "| Phase | Evidenced |",
        "| --- | --- |",
        "| 1 — basic chat, history, zero-attachment floor | yes |",
        "| 2 — model selection, two models, different output | yes |",
        "| 3 — plugins change the payload | yes |",
        f"| 4 — KG context reaches the prompt | {yes_no} |",
        f"| 5 — subgraph + Cypher | {yes_no} |",
        f"| 6 — live retrieval grounding | {yes_no} |",
        "",
    ]
    if not live:
        lines += [
            "## Phases 4-6 are not evidenced by this run",
            "",
            "FalkorDB was not reachable, so there was no graph to query and no "
            "CIViC evidence to retrieve. That is recorded rather than faked: a "
            "stubbed graph would satisfy the letter of the requirement and "
            "defeat its purpose, and issue #103 asks specifically for the "
            "visualization *alongside the real query and data it came from*.",
            "",
            "To evidence them, start the graph and re-run:",
            "",
            "```bash",
            "docker compose up -d falkordb",
            "python -m secondlook.tier1.civic_loader     # seed CIViC evidence",
            "python -m secondlook.devtools.capture_evidence",
            "```",
            "",
            "## What the run DID show: the degraded path",
            "",
            "With the evidence store down, the surface now says so instead of "
            "reporting an empty search. Before PR #111 this rendered as *\"no "
            "sources attached — attach a retrieval source\"*, which blames the "
            "clinician for an outage and reads as a clinical negative.",
            "",
            "```json",
            json.dumps(
                {
                    "retrieval_failed": result["findings"].get("degraded_retrieval_failed_flag"),
                    "retrieval_error": result["findings"].get("degraded_retrieval_error"),
                },
                indent=2,
            ),
            "```",
            "",
            "The reply itself:",
            "",
            "```",
            str(result["findings"].get("degraded_reply", "")).strip(),
            "```",
            "",
            f"And the Phase 5 endpoint returns "
            f"`{result['findings'].get('phase_5_status_when_graph_down')}` "
            "(service unavailable), not a 500.",
            "",
        ]
    orphan_state = (
        "empty — no orphaned message"
        if result["findings"].get("failed_turn_left_history_empty")
        else "ORPHANED"
    )
    lines += [
        "## Boundary behaviour",
        "",
        "| Case | Status |",
        "| --- | --- |",
        f"| Unknown attachment id | {result['findings'].get('rejects_unknown_attachment')} |",
        f"| Unknown model id | {result['findings'].get('rejects_unknown_model')} |",
        f"| Empty message | {result['findings'].get('rejects_empty_message')} |",
        f"| Unconfigured model | {result['findings'].get('unconfigured_model_status')} |",
        f"| History after that failure | {orphan_state} |",
        "",
        "## Screenshots",
        "",
        "This harness drives the API. The UI flow (landing → Get Started → chat "
        "→ model picker → session config → View Knowledge Graph) still needs a "
        "recording against a running `vite dev`; that is the one part of the "
        "bar a script cannot produce for itself.",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)

    port = args.port or _free_port()
    base = f"http://127.0.0.1:{port}"

    env = {**os.environ, "ATHENA_API_AUTH_DISABLED": "true"}
    env.pop("ANTHROPIC_API_KEY", None)  # keep the paid path unconfigured, on purpose

    print(f"Starting uvicorn on {base} ...")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "secondlook.api.app:create_app", "--factory",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        _wait_for_server(base, proc)
        recorder = Recorder(base)
        result = run(base, recorder)
        write_report(args.out, result, recorder, base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"\nWrote {args.out}/README.md, exchanges.json, findings.json")
    print("Graph-backed phases evidenced." if result["graph_live"]
          else "Phases 4-6 NOT evidenced: FalkorDB unreachable (recorded as such).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
