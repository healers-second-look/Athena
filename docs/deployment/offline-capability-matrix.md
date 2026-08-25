# Offline / Air-Gapped Capability Matrix

Many low-resource deployments this project targets have **intermittent,
not absent, connectivity** — the framing issue #16 itself uses. This
matrix states plainly what still works with no network connection and
what doesn't, per subsystem, based on reading each subsystem's actual
code — not a blanket "yes" or "no" claim about the whole system.

**This is not a claim of a tested, formal air-gapped mode.** Most rows
below were never actually run with networking disabled to confirm
degraded behavior end-to-end; this matrix is built from what each
subsystem's own code and docstrings say about its network dependencies.
Treat "works offline" below as "has no code path that makes a network
call for this operation," not as "verified under an actual air-gap
test" — **except the Evidence Memory reading row, which *was* corrected
by actually running it live** (see the note on that row) after the
first pass of this document got it wrong.

| Subsystem | Works fully offline? | Detail |
|---|---|---|
| **Case Memory Store** (Postgres) | **Yes** | Local database. Creating cases, recording events, folding `CaseState` — no network call anywhere in `case/state.py`, `case/store.py`. |
| **Dependency-Tracked Diff Engine** | **Yes** | `case/diff.py` is pure by explicit design invariant — "never calls an LLM," no I/O of any kind. Fully offline by construction, not by accident. |
| **Evidence Memory — reading** | **Conditional — corrected, see below** | The first pass of this document said "Yes," based on `tier1/retrieval.py`'s keyword-based retrieval never making a network call. That's true of `retrieval.py`, but it isn't the path the real dispatch table actually uses: `signals/literature.py` (wired into every single `ChangeKind`, see issue #99) calls **semantic** (embedding-based) retrieval unconditionally instead, via `tier1/semantic_retrieval.py`. That module downloads its embedding model (`sentence-transformers/all-MiniLM-L6-v2`, ~90 MB) from Hugging Face **the first time it runs in a given container's lifetime** — confirmed live: a freshly-created container's first `/research` call took ~47s and required real network access; killing that access before the first call would make it fail. Once loaded, the model stays in memory for that process (fast, no further network calls) — but a container **restart** only survives if the on-disk cache persists (it does, since restart keeps the writable layer), while a full **recreate** (redeploy, image update) wipes that cache and needs the network again. No Docker volume currently persists this cache across recreates, and the model isn't baked into the image at build time — so a genuinely air-gapped redeploy of the `api` service will fail its first `/research` call until one of those is fixed. Tracked as a real, live-confirmed gap, not a hypothetical one. |
| **Evidence Memory — ingesting new evidence** | **No** | `civic_loader.py`, `pubmed_loader.py`, and the scheduler (`tier1/scheduler.py`) reach CIViC, PubMed, and ClinicalTrials.gov's live APIs. No connectivity means no new evidence — the graph stays exactly as current as its last successful sync. |
| **Trial eligibility matching** | **Yes** | `signals/trial_matching.py`'s `match_trials()` docstring states it explicitly: "no LLM calls, no network, no I/O." Matches previously-extracted criteria against a case. |
| **Trial data ingestion** (`ctgov_loader.py`) | **No** | Same shape as evidence ingestion above — needs ClinicalTrials.gov's live API. |
| **Access Pathway Registry** | **Yes** | Curated, checked-in YAML (`access_pathways/`), read locally by `access_pathway_loader.py`. No network call in the loader. |
| **Guideline-Grounded Exhaustion Assessment** | **Yes** | Same shape — checked-in `guideline_kb/` YAML, `assess_exhaustion()` is a pure function taking the loaded KB as a parameter. |
| **Structured Case Index** | **Yes** | Operates on already-stored case data. |
| **Synthesis (LLM-generated answers)** | **Conditional** | With `ATHENA_LLM_ENABLED=false` (see `.env.example`): fully offline, deterministic citable-items path, no degradation to a broken feature — this is a real, designed fallback, not just "the feature breaks." With the default hosted Anthropic API: **no**, needs internet. With a **self-hosted** OpenAI-compatible model (`ATHENA_LLM_PROVIDER=openai_compatible`, pointed at a local vLLM/Ollama instance): **yes**, genuinely offline-capable, though the model-serving hardware itself is a separate, real requirement. |
| **Citation Verification Gate** | **Yes** | Pure post-check against already-retrieved citable items; no network call. |
| **Tier 2 structural prediction** (binding/docking) | **No** | Depends on UniProt, RCSB PDB, AlphaFold DB, and (for the fallback path) the mCSM-lig web server or ESM Atlas — all live external services. Not part of the `docker-compose.yml` stack this deployment guide covers, and not offline-capable as currently built. |
| **Frontend (web client)** | **Yes**, once loaded | The built bundle is fully self-contained (see `vite.config.js`'s bundling decisions — no CDN dependency, no external font/script loading). Talks to the local `api` container only. |
| **REST API** | **Yes** | No outbound network call itself — its own dependencies are what may or may not be offline-capable (case memory: yes; evidence reads: yes; synthesis: conditional, see above). |

## The honest summary

**Recording a case, tracking what changed, matching against already-known
trials/access-pathways/guidelines, and getting a citation-checked answer
if `ATHENA_LLM_ENABLED=false` or a self-hosted model is configured — all
work with zero network connectivity, once the embedding model used by
evidence retrieval has been loaded at least once (see the corrected row
above).**

**Pulling in new evidence, new trials, structural predictions,
hosted-LLM synthesis, or the very first `/research` call after a fresh
deploy/redeploy of the `api` service — all require connectivity when
they run**, but none of them block the offline-capable features above
from working afterward. A clinic with intermittent connectivity can
sync when a connection is available and keep working on existing
case/evidence data the rest of the time.

## Explicitly not built

A dedicated "air-gapped mode" flag, startup check, or UI indicator that
tells a clinician "you're offline right now, here's what that means for
this specific action" does not exist. This document is the current
substitute for that — a real air-gapped-mode feature (if wanted) would
be new work, not a repackaging of what's here.

A genuinely air-gapped-from-first-boot deployment also isn't built yet:
the embedding model download on first `/research` call (see the
corrected Evidence Memory row above) means the very first deploy of the
`api` service needs one successful outbound connection to Hugging Face
before evidence retrieval works at all, and that requirement resets on
every redeploy since nothing persists the model cache across container
recreation. Two independent fixes would close this, neither done here:
bake the model into the image at build time (trades image size for
zero runtime network dependency), and/or mount a persistent volume for
the Hugging Face cache directory so a recreate doesn't lose it even
without baking.
