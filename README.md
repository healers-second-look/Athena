# 🧬 Athena

[![CI](https://github.com/healers-second-look/Athena/actions/workflows/ci.yml/badge.svg)](https://github.com/healers-second-look/Athena/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11-blue.svg)](pyproject.toml)

An oncologist runs out of standard genomic leads on a rare or treatment-exhausted
cancer and needs a second opinion that isn't a chatbot guessing confidently.
Athena — the engine behind **SecondLook** — tries to be that second opinion,
grounded in a real evidence graph, with every claim traceable back to a
citation or a computed method, never to a model's imagination.

Given a patient's case, it answers two questions people actually ask in tumour
boards:

1. **What's already known?** Documented clinical evidence for this gene, this
   variant, this cancer type — pulled live from a CIViC + PubMed knowledge graph,
   not recalled from an LLM's training data.
2. **What happens as the case evolves?** New pathology, a new scan, a new lab
   result — Athena remembers the case, diffs what changed, and flags exactly
   which prior findings that change invalidates.

There's a second, older half of this repo too: a structural-biology pipeline
(binding-affinity prediction, AlphaFold/AlphaMissense lookups, candidate-drug
scoring) for cases where the evidence graph comes back empty. It's real,
heavily tested, and **honestly not validated as a product claim yet** — see
[Where this stands](#-where-this-actually-stands-right-now) before you assume
it predicts anything.

---

## ⚠️ Read this before you demo anything

- **Real LLMs are not technically constrained to the retrieved evidence.** The
  system prompt tells whichever model you've configured (Claude, Gemini, a
  self-hosted one) to cite only retrieved sources and say so when it has none —
  but that's an instruction, not an enforced guardrail. Nothing in the response
  path rejects a claim the model pulled from its own training weights instead of
  the graph. Test this directly with sparse retrieval before you trust an answer.
- **Tier 2's binding-affinity prediction has not passed its own validation.**
  Across the nine-case gold standard, zero candidates were scored by docking or
  mCSM-lig (`scored_by_method: {'null': 9}`) — every result today is
  `proximity_only`. The fallback claim (that proximity alone separates resistant
  from sensitive mutations) was tested too and also missed, 7/8. Full details in
  [`ISSUES.md`](ISSUES.md) §1 — read it before anyone sees this pipeline run.
- **The Patient Timeline shows the same reference dataset for every case**, on
  purpose, until a real per-patient data source is wired in. It's real,
  published osteosarcoma treatment data, not a mock-up — but it isn't *this*
  patient's data. `src/secondlook/timeline/reference_data.py` says so on every
  call.
- **This repo is mid-merge between two architectures.** [`ARCHITECTURE.md`](ARCHITECTURE.md)
  is replacing the Tier 1/Tier 2 split you'll see below with one signal graph
  where structural prediction is just another signal, not a fallback gated on
  evidence coming up empty. Most of Tier 1 survives that merge unchanged; the
  binding-delta code is explicitly being demoted off the presented path. Don't
  be surprised the two docs disagree about what's "current" — they're describing
  before and after the same rewrite.

---

## 🚀 Quick start

The fastest path to something clickable is Docker — it brings up the knowledge
graph, the case database, the API, and the web client together:

```bash
cp .env.example .env      # then set a real ATHENA_API_KEY (see the file for how)
docker compose up -d
```

| Service | URL |
|---|---|
| Web app (chat, case dashboard, patient timeline) | http://localhost:8080 |
| API + interactive docs | http://localhost:8000/docs |
| FalkorDB graph browser | http://localhost:3000 |

No LLM key configured yet? The chat interface still works — it ships with two
deterministic offline models (`mock-outline`, `mock-terse`) precisely so the
whole surface is testable and demoable with no API key and no network. Point it
at a real model later by setting `ANTHROPIC_API_KEY`, or `ATHENA_LLM_BASE_URL` +
`ATHENA_LLM_MODEL` + `ATHENA_LLM_API_KEY` for anything speaking the OpenAI
chat-completions format — vLLM, Ollama, or Gemini's own [OpenAI-compatible
endpoint](https://ai.google.dev/gemini-api/docs/openai). See `.env.example` for
every knob.

No Docker? The genomics pipeline runs standalone, fully offline:

```bash
pip install -e ".[dev,api]"
pytest -q
```

That installs both the core package and the `api` extra (some offline tests
import `secondlook.case.models`, which needs SQLAlchemy even without a live
database) and runs the non-integration suite — everything except the tests
that need a running FalkorDB or live external APIs, which are deselected by
default and skip cleanly rather than fail when those aren't reachable. CI runs
this exact command on Python 3.11 for every PR; that's the badge at the top of
this file.

---

## 🧭 What's actually in here

**Case Memory** (`src/secondlook/case/`) — the source of truth for a patient's
case. Events append; nothing about `case_events` can be updated or deleted
through `CaseStore`, not by convention but by the class simply having no such
method, which a test asserts directly. Findings derive from folding those
events and carry their own citations; a new event can supersede an old finding,
and the dashboard shows you exactly which one and why.

**Chat / Synthesis** (`src/secondlook/chat/`, the "Synthesis" tab in the web
app) — ask a question, get an answer grounded in whatever the knowledge graph
actually retrieves for it. Every model behind the picker — the two offline
mocks, hosted Claude, or any OpenAI-compatible server — goes through the same
`complete(prompt, system=)` interface, so swapping models never touches
retrieval or prompt construction. Retrieved evidence and a plugin's own
annotations are kept in genuinely separate prompt sections; conflating them
once caused a model to cite a source that was never retrieved, which is
exactly the kind of bug this project writes an issue for before fixing.

**Patient Timeline** — a chronological view of treatment history, procedures,
imaging, MRD, flow cytometry, and lab results, reachable both from a case's own
dashboard and, more recently, as a quick-look modal straight from the chat
interface. Built against real reference data today; the seam for real
per-patient data is one function.

**Knowledge graph** (FalkorDB) — CIViC evidence and PubMed literature as a
proper graph, not a flat table: `Gene -[:HAS_VARIANT]-> Variant`, evidence
items, publications, drugs, all queryable in the browser at `:3000` or via the
chat interface's "Explore Graph" panel, which shows you the exact Cypher it
ran, not just the results.

**MCP server** (`src/secondlook/mcp_server/`) — five read-only tools
(`get_case_summary`, `get_recent_changes`, `search_evidence`, `match_trials`,
`get_access_pathways`) exposed to any MCP-speaking client. Binds to loopback
only unless you explicitly opt into remote access, and refuses to start
remotely without an API key configured — fails closed, not open.

**mCODE / FHIR export** (`src/secondlook/interop/`) — maps a case onto FHIR R4
resources shaped after mCODE. It's structurally valid FHIR, and it's honest
about not being full mCODE-conformant: real conformance needs SNOMED/LOINC/RxNorm
coding this system's underlying data doesn't carry yet, and a guessed medical
code is worse than an absent one, so every `CodeableConcept` here carries text
only.

**Structured Case Index** (`src/secondlook/index/`) — a k-anonymity-gated,
allowlist-only export path for aggregating de-identified case summaries across
patients. The gate fails *closed*: at realistic early-deployment case volumes
it will usually refuse to export, which is correct behavior, not a bug someone
should "fix" by lowering the threshold.

**Tier 1 — evidence retrieval** (`src/secondlook/tier1/`) — three retrieval
modes over the graph (exact match, relaxed same-class match, and semantic
search via sentence-transformers over evidence/publication embeddings), plus
loaders for ClinicalTrials.gov, a curated guideline knowledge base, and
US/India access-pathway registries. The one rule enforced everywhere in this
subpackage: an item with no citation URL is never returned as evidence, full
stop.

**Tier 2 — structural prediction** (`pipeline.py` and friends) — for the cases
Tier 1 comes back empty on. Validates the mutation against a canonical
sequence, pulls an AlphaMissense pathogenicity score, sources a structure
(RCSB → AlphaFold → ESM Atlas, in that order), finds candidate drugs (DGIdb →
Open Targets → ChEMBL), and scores binding-affinity change with mCSM-lig or a
Vina docking fallback — gated by a covalent-mechanism check so a covalent drug
never gets scored by a method that can't see the covalent bond at all. See the
caveats above before treating any of this as a validated prediction.

---

## 🏗️ Where this actually stands right now

This repo is honest about being two systems, not one polished product:

| Doc | What it covers |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The target design — one signal graph, no tier gating one path on another's failure. Read this to understand *why* the current split exists and what's replacing it, and its §2 for exactly which modules carry over unchanged versus which get re-wired. |
| [`docs/architecture.md`](docs/architecture.md) | The tier-based system *as built today* — Tier 1 gating Tier 2, an orchestration API, an LLM synthesis layer. Not the target; a snapshot of the current wiring. |
| [`ISSUES.md`](ISSUES.md) | Every known problem in the current implementation, with root cause and candidate fix. Non-negotiable pre-demo reading. |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | The subsystem-by-subsystem build plan the case/chat/API/web half was built against. |
| [`docs/`](docs/) | Deployment sizing, cost model, validation plans, license audit, and the rest of the specs. |

If you only read one thing before evaluating this project: **ISSUES.md §1**.
The genomics pipeline runs end to end and produces output, but that output is
not the same thing as a validated prediction, and this project would rather
you know that going in than find out from a wrong answer.

---

## 🧪 Testing

```bash
pytest -q                    # offline unit tests, no network, no live services
pytest -m integration        # hits live FalkorDB + external APIs, skips cleanly if unreachable
pytest tests/tier1           # Tier 1 only
pytest tests/chat            # chat/synthesis engine only
cd web && npm test           # 27 frontend component tests (vitest)
```

The offline suite collects on the order of a thousand test cases across both
halves of the repo and runs green on Python 3.11 in CI for every PR (the badge
up top). If you're on a newer Python locally and `hgvs`/`pysam` refuses to
build a wheel — a real, known friction point, not something wrong with your
setup — either stay on 3.11 for now or skip the modules that need it; nothing
else in the repo depends on it.

Bundle size is enforced, not just measured: `cd web && npm run build && npm run
budget` fails the build if the shipped JS/CSS grows past what a low-bandwidth
clinic connection can reasonably load.

---

## 📁 Repo map

```
src/secondlook/
├── case/          Case Memory Store — append-only events, folded findings, diffs
├── chat/          Synthesis engine — retrieval, prompt assembly, model registry
├── api/           FastAPI routes for cases, chat, timeline, findings
├── timeline/      Patient Timeline reference data + retrieval
├── query/         Read-side query layer backing the API and MCP server
├── interop/       mCODE / FHIR R4 export
├── index/         k-anonymity-gated Structured Case Index export
├── intake/        LLM-assisted, human-confirmed document → case-event extraction
├── mcp_server/    Read-only MCP tools over case data
├── synthesis/     LLM client abstraction + citation-gated generation
├── harness/       LLM decision-quality/safety evaluation harness
├── signals/       Typed evidence/trial/access-pathway signal generators
├── tier1/         Evidence retrieval — CIViC, PubMed, trials, guidelines, access pathways
└── pipeline.py    Tier 2 — structural prediction orchestrator

web/               React + Vite frontend (chat, case dashboard, timeline)
tests/             Mirrors src/ — one test package per subsystem
validation/        Gold-standard structural-prediction validation harness
docs/              Architecture, deployment, and validation specs
ISSUES.md          Every known problem and its candidate fix — read before demoing
```

---

## 🤝 Contributing

Contributions of any kind count — code, documentation, curated clinical data,
issue triage, review. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the how and
[`CONTRIBUTORS.md`](CONTRIBUTORS.md) to add yourself once something's merged.
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) and [`GOVERNANCE.md`](GOVERNANCE.md)
cover the rest.

---

## 📜 License

Athena is licensed under **AGPL-3.0** — free to run, modify, and deploy for
anyone, including large hospitals, as long as changes stay open. A separate
commercial license is available for organizations that need different terms.
See [`LICENSE.md`](LICENSE.md) for the plain-language version and
[`LICENSE`](LICENSE) for the actual legal text.
