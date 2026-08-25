# Issue #103 — driven evidence

Generated 2026-08-25 04:04 UTC by `python -m secondlook.devtools.capture_evidence`.

A real uvicorn on `http://127.0.0.1:64642`, driven over real HTTP. Every request and response is in `exchanges.json` verbatim; the assertions drawn from them are in `findings.json`.

## Coverage

| Phase | Evidenced |
| --- | --- |
| 1 — basic chat, history, zero-attachment floor | yes |
| 2 — model selection, two models, different output | yes |
| 3 — plugins change the payload | yes |
| 4 — KG context reaches the prompt | **no — FalkorDB unreachable** |
| 5 — subgraph + Cypher | **no — FalkorDB unreachable** |
| 6 — live retrieval grounding | **no — FalkorDB unreachable** |

## Phases 4-6 are not evidenced by this run

FalkorDB was not reachable, so there was no graph to query and no CIViC evidence to retrieve. That is recorded rather than faked: a stubbed graph would satisfy the letter of the requirement and defeat its purpose, and issue #103 asks specifically for the visualization *alongside the real query and data it came from*.

To evidence them, start the graph and re-run:

```bash
docker compose up -d falkordb
python -m secondlook.tier1.civic_loader     # seed CIViC evidence
python -m secondlook.devtools.capture_evidence
```

## What the run DID show: the degraded path

With the evidence store down, the surface now says so instead of reporting an empty search. Before PR #111 this rendered as *"no sources attached — attach a retrieval source"*, which blames the clinician for an outage and reads as a clinical negative.

```json
{
  "retrieval_failed": true,
  "retrieval_error": "FalkorDB unreachable: Error 61 connecting to localhost:6379. Connection refused."
}
```

The reply itself:

```
## On: What treatment options exist for EGFR T790M in NSCLC?

### Evidence search could not be run
- RETRIEVAL UNAVAILABLE -- the evidence store could not be reached (FalkorDB unreachable: Error 61 connecting to localhost:6379. Connection refused.). No search was performed. This is not a finding of 'no evidence'.
- This is NOT a finding that no evidence exists. Nothing was searched.

### Caveats
- Deterministic offline model. It restates retrieved context; it does not reason over it and must not be read as clinical advice.
```

And the Phase 5 endpoint returns `503` (service unavailable), not a 500.

## Boundary behaviour

| Case | Status |
| --- | --- |
| Unknown attachment id | 422 |
| Unknown model id | 422 |
| Empty message | 422 |
| Unconfigured model | 409 |
| History after that failure | empty — no orphaned message |

## Screenshots

This harness drives the API. The UI flow (landing → Get Started → chat → model picker → session config → View Knowledge Graph) still needs a recording against a running `vite dev`; that is the one part of the bar a script cannot produce for itself.
