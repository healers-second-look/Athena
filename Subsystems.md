# Athena — Subsystems

Fifteen independently buildable subsystems. Each section is written so a team
that has read only `Concept.md` and this entry can start work without asking
the rest of the project anything except the stated interface contract. Where
a subsystem is already fully specified elsewhere in the repo's planning docs,
this file gives the summary + delta and points to the source rather than
duplicating hundreds of lines.

**Every subsystem is held to the six principles in `Concept.md` §8** — open
data sources only, minimal LLM calls, self-hostable, model-agnostic LLM
layer, no cross-deployment data sharing, regionally configurable. Restated
per-subsystem only where a subsystem has a specific instance of that
constraint worth calling out.

**Legend for the "Status" field:** `BUILT` (exists in `src/secondlook/` and
should not be rewritten), `SPEC'D` (fully designed in a prior doc, ready to
implement), `NEW` (designed for the first time in this document).

---

## A. Evidence Graph Spine

**Status:** `BUILT`, needs the continuous-ingestion extension in §7 of
`Concept.md`.

**Purpose:** the FalkorDB knowledge graph — genes, variants, diseases, drugs,
evidence items, publications, trials, access pathways. Everything else reads
from this; almost nothing should write to it except the loaders below.

**Interfaces**
- *In:* CIViC GraphQL, PubMed E-utilities, ClinicalTrials.gov v2 REST,
  curated access-pathway CSV/YAML (see subsystem J)
- *Out:* Cypher queries via `graph_connection.py`; typed retrieval functions
  in `tier1/retrieval.py` and `tier1/semantic_retrieval.py`

**Already built, do not rebuild:** `graph_schema.py` (node/edge types,
provenance helpers), `civic_loader.py`, `civic_verify.py`, `pubmed_loader.py`,
`retrieval.py` (Modes 1–2). `semantic_retrieval.py` (Mode 3) is written but
**unverified end to end** — verify before depending on it; `sentence-
transformers` pulls ~2GB, so budget for it explicitly in a low-resource
deployment sizing decision, and design the fallback path (normalized-string
matching) to be genuinely adequate, not a placeholder.

**New work for this subsystem:**
1. **Scheduler.** A cron-style job (not real-time streaming — unnecessary
   infra cost) that re-runs the loaders for the configured scope, diffs
   against existing nodes, and writes only changes through
   `with_enrichment_provenance()`.
2. **Change event emission.** Every write that changes an existing node
   (not just creates one) emits an `EvidenceChangeEvent{node_type, node_id,
   old_props, new_props, source, retrieved_at}` — this is the input to
   subsystem G (Emerging Evidence Radar). Emit even when nothing downstream
   is listening yet; don't couple the loaders to the radar's existence.

**Deliverables:** `tier1/scheduler.py`, `tier1/change_events.py`, a
documented cron interval per source (CIViC evidence changes slowly — weekly
is enough; trial recruitment status changes faster — daily is reasonable),
and an updated `civic_scope.yaml`-style config per new source.

**Caveats:** CIViC has unstable uptime historically — confirm before
scheduling assumes a fixed cadence works. CTRI's programmatic access mode is
unverified (`ARCHITECTURE.md` §9.3) — don't build the scheduler's retry logic
assuming CTRI behaves like ClinicalTrials.gov's clean REST API until this is
confirmed.

**Harness:** shape-verification tests per source (`civic_verify.py`'s
pattern — assert on parsed structure, never a status code alone), run against
live APIs, marked `@pytest.mark.integration` per the existing convention.

---

## B. Structural / Computational Signal Engine (Tier 2)

**Status:** `BUILT`, demoted from product claim per validation failure.

**Purpose:** opt-in structural signal (binding-site proximity; AlphaMissense
pathogenicity) for the minority of cases with a missense mutation in a
druggable pocket. Not a product-facing prediction — a caveated measurement.

**Interfaces**
- *In:* `gene`, `mutation` (validated HGVS), optional `restrict_to_drugs`
- *Out:* `StructuralSignal` node, `evidence_class="computed"`, no citation
  field, mandatory disclaimer text

**Already built, do not rebuild:** everything in `structure.py`,
`mutation_validation.py`, `alphamissense.py`, `rcsb.py`, `covalent.py`,
`ligand_identity.py`, `proximity.py`, `vina_dock.py`, `mcsm_lig.py`,
`labeling.py`.

**New work:** none required for the core concept. If a team has spare
capacity, the one legitimate open item is extending the gold-standard set
beyond the current nine cases — but this is explicitly optional and must not
compete for time against subsystems C–G.

**Caveats — carry forward verbatim, do not soften:** binding-affinity delta
failed pre-committed validation (2/9 vs 70% threshold). Proximity failed its
own pre-committed criterion (7/8). Neither ships as a scored claim. Both stay
in-repo, tested, invoked only when Case Memory (subsystem C) explicitly
requests it for a specific finding.

**Deliverables:** none — this subsystem's deliverable is "leave it alone,"
which is itself worth stating so a new team doesn't rediscover and re-attempt
the binding-delta claim.

---

## C. Case Memory Store

**Status:** `SPEC'D` in full in `IMPLEMENTATION_PLAN.md` §2. Summary here;
read that document for the actual schema and code.

**Purpose:** the event-sourced record of one patient's case. Append-only.
Current state is derived by folding the event log.

**Interfaces**
- *In:* `POST /cases`, `POST /cases/{id}/events` (subsystem L)
- *Out:* `CaseState` (derived), full event timeline, to subsystems D, E, K

**Deliverables:** Postgres schema (`cases`, `case_events`, `questions`,
`findings`, `decisions` — full DDL in `IMPLEMENTATION_PLAN.md` §2.2), the
five-type event taxonomy, `state.py` (event fold), `store.py` (repository
layer enforcing append-only at the code level, not just a DB constraint
comment).

**Caveats:** no PHI in the schema — no name, DOB, or MRN, per
`patient-schema-mvp.md` §7. Enforce this with a schema-level test that fails
CI if a disallowed column name is added, not just a code-review convention.

**Low-resource note:** Postgres, not a managed database service — runs on
the same commodity server as FalkorDB. No reason for this subsystem to
require anything beyond a single VM.

---

## D. Dependency-Tracked Diff Engine

**Status:** core mechanism `SPEC'D` in `IMPLEMENTATION_PLAN.md` §3;
**bidirectional extension `NEW`** in `Concept.md` §5.

**Purpose:** the actual product. Pure, deterministic, no I/O, no LLM. Detects
what changed in Case Memory *or* Evidence Memory and which prior findings
that invalidates.

**Interfaces**
- *In:* `CaseState(t-1)`, `CaseState(t)`, `active_findings` (from C),
  `EvidenceSnapshot` reference (from A), `EvidenceChangeEvent` stream (from A)
- *Out:* `ChangeSet{changes, supersessions, unchanged_reason}` (patient-side),
  `AffectedCasesReport{finding_ids, evidence_change, affected_case_ids}`
  (evidence-side — the "47 cases affected" query)

**Deliverables**
1. `case/assumptions.py` — the `Assumption` protocol, extended per
   `Concept.md` §5 to accept both `case` and `evidence` state:
   ```python
   class Assumption(Protocol):
       def holds(self, case: CaseState, evidence: EvidenceSnapshot) -> bool: ...
       def describe(self) -> str: ...
       def evidence_keys(self) -> frozenset[tuple[str, str]]:
           """(gene, variant) or (gene, drug) pairs this assumption is
           sensitive to — used to index findings for the reverse-lookup
           in step 3, so a new evidence item triggers re-evaluation of
           only the findings that could possibly be affected, not a scan
           of every active finding in the system."""
   ```
2. `case/diff.py` — patient-side `compute_diff()`, exactly as specified in
   `IMPLEMENTATION_PLAN.md` §3.3.
3. `case/evidence_diff.py` — **new**, the reverse direction:
   ```python
   def compute_affected_findings(
       change_event: EvidenceChangeEvent,
       finding_index: FindingsByEvidenceKey,   # inverted index, see below
   ) -> AffectedCasesReport:
       """Deterministic. Looks up findings whose assumptions declared
       sensitivity to (change_event.gene, change_event.variant_or_drug)
       via evidence_keys(), re-evaluates only those against the new
       EvidenceSnapshot, returns superseded findings grouped by case."""
   ```
4. `case/finding_index.py` — an inverted index (`(gene, variant_or_drug) ->
   set[finding_id]`), maintained incrementally as findings are created —
   **this is what makes "which cases does this new paper affect" a cheap
   indexed lookup instead of an O(all active cases) scan**, which is the
   detail that makes this affordable at scale in a low-resource deployment.

**Tests:** everything in `IMPLEMENTATION_PLAN.md` §3.4, plus: a new evidence
item for gene X does not trigger re-evaluation of a finding indexed under
gene Y · the inverted index stays correct after 1,000 findings are added and
50 are marked superseded (no drift) · the 100-run determinism test applies to
`compute_affected_findings` too, not just `compute_diff`.

**Caveat, stated as an invariant:** this subsystem never calls an LLM. If a
future contributor is tempted to have a model "decide" whether an assumption
still holds, that is the specific mistake this document exists to prevent —
see `IMPLEMENTATION_PLAN.md` §13, invariant 11.

---

## E. Signal Generator Layer ("OncoSphere" dimensions)

**Status:** `SPEC'D` in `CONCEPT_EVALUATION.md` §3 and §11.

**Purpose:** parallel, typed, deterministic-or-light-LLM functions per
clinical dimension, framed in the UI as tumor-board specialties. **Not
autonomous agents** — no reasoning loop, no tool-calling initiative, no
inter-generator negotiation.

**Interfaces**
- *In:* `(ChangeSet, Question)` — the diff engine decides *what* to
  investigate; a generator decides *how* to investigate its own dimension
- *Out:* `list[Signal]`, each `evidence_class`-tagged per `ARCHITECTURE.md`
  §5, never merged across generators into a false consensus

**Deliverables:** `signals/genomics.py` (wraps subsystem A retrieval),
`signals/trials.py` (wraps subsystem F), `signals/literature.py` (wraps
subsystem A's PubMed/semantic retrieval), `signals/pharmacology.py` (wraps
existing `chembl_enrich.py`/`dgidb.py`), `signals/registry.py` — a typed
dispatch table keyed on `ChangeKind`, **not** an orchestrator with autonomous
routing.

**Explicit non-goal, stated so it isn't rebuilt by accident:** no agent
framework dependency. No LangGraph, CrewAI, AutoGen, or equivalent. A
dict-based dispatch table is the correct implementation, not a placeholder
for something more sophisticated later — see `CONCEPT_EVALUATION.md` §3 for
the full reasoning.

**Conflict handling:** when two generators' signals disagree (CIViC says
sensitive, a recent paper suggests resistance), render both, labeled,
side by side. No resolution step, no confidence-weighted averaging.

---

## F. Clinical Trial Intelligence & Eligibility Matcher

**Status:** `NEW`. This is the concrete build behind `Concept.md` §7's
compatibility-bucket example.

**Purpose:** match a case's structured state against parsed trial
eligibility criteria and bucket results by compatibility, with the specific
criterion cited per trial — not a keyword search.

**Interfaces**
- *In:* `CaseState` (age, cancer_type, stage, alterations, treatment
  history), trial records from subsystem A (`Trial` nodes, already declared
  in `graph_schema.py`)
- *Out:* `TrialMatchResult{trial_id, bucket: highly_compatible |
  needs_verification | probably_incompatible, matched_criteria: list[str],
  unresolved_criteria: list[str], violated_criteria: list[str]}`

**Technical approach — deliberately NLP-extraction-then-match, not
generative matching:**
1. **Criteria extraction** (one-time per trial, cached): parse
   `eligibility_criteria` free text from ClinicalTrials.gov into a small set
   of structured predicate types — `AGE_RANGE`, `PRIOR_THERAPY_EXCLUDES(drug)`,
   `BIOMARKER_REQUIRES(name, op, value)`, `ECOG_MAX(n)`,
   `DISEASE_STAGE_REQUIRES(...)`, `UNPARSEABLE` (explicit fallback — never
   silently dropped, per the project's standing "no silent gaps" rule).
   LLM-assisted extraction is appropriate *here* (one call per trial,
   cached forever, human-spot-checked on a sample) because it's a one-time
   structuring cost, not a per-patient-per-query cost — this is exactly the
   place in the system where an LLM call is cheap in aggregate.
2. **Matching** (per case, per query — must be fast and free): pure
   predicate evaluation against `CaseState`, zero LLM calls. A criterion that
   references a case field not yet recorded → `needs_verification`, not a
   guess.
3. **Bucketing:** `highly_compatible` = all extracted criteria evaluate true;
   `probably_incompatible` = ≥1 criterion evaluates false; `needs_verification`
   = ≥1 `UNPARSEABLE` or data-missing criterion and none evaluate false.

**Deliverables:** `tier1/ctgov_loader.py` (populate `Trial` nodes — closes
`ISSUES.md` §5), `tier1/criteria_extraction.py` (the one-time LLM-assisted
parse + cache + human-spot-check harness), `signals/trials.py`'s matching
logic (pure predicate evaluation, no LLM).

**Caveats:** criteria extraction accuracy is unvalidated until the team
builds a spot-check harness — **do not ship the bucketing as authoritative
without a documented sample-accuracy check**, the same discipline
`validation-plan.md` already applies to the structural pipeline. CTRI's
programmatic access is unverified (subsystem A caveat) — the India-specific
version of this subsystem is gated on that being resolved first.

**Harness:** a labeled test set of ~30 real trial eligibility sections,
hand-annotated with the correct extracted predicates, checked into
`tests/trials/fixtures/` — extraction accuracy against this set is the
subsystem's own pre-committed validation criterion, following the project's
existing pattern.

---

## G. Emerging Evidence Radar

**Status:** `NEW`, but the mechanism is entirely subsystem D's reverse
direction (§D deliverable 3) — this subsystem is the **alerting UI and
delivery** on top of an already-built engine, not a new detection mechanism.

**Purpose:** when Evidence Memory changes, proactively notify the clinicians
on every affected case, rather than waiting for them to ask.

**Interfaces**
- *In:* `AffectedCasesReport` (from D)
- *Out:* an `Alert` row per affected case (`case_id`, `finding_id`,
  `evidence_change_summary`, `created_at`, `acknowledged: bool`), surfaced on
  the case dashboard (subsystem M) and optionally via a low-bandwidth channel
  (§M note)

**Deliverables:** `case/alerts.py` (writes `Alert` rows from an
`AffectedCasesReport`, deduplicated so the same evidence change doesn't
re-alert on every scheduler run), a dashboard badge, and — deliberately last
priority — an optional notification channel (email/SMS) for institutions that
want push rather than pull.

**Caveat:** an alert is **not** a new synthesized finding — it points at the
existing superseded finding and the new evidence item, cited, and lets the
clinician decide whether to trigger fresh research (subsystem E/I). Do not
have this subsystem auto-generate a new synthesis; that's subsystem I's job,
invoked explicitly, not implicitly.

---

## H. Citation Verification Gate

**Status:** `SPEC'D` in `IMPLEMENTATION_PLAN.md` §7. Summary only.

**Purpose:** deterministic post-generation check that every sentence in an
LLM-generated synthesis maps to a retrieved item ID; anything that doesn't is
removed and the removal is counted, never silent.

**Deliverables:** `synthesis/citation_gate.py`, exactly as specified.

**Why this is its own subsystem rather than folded into I:** it's a small,
fully deterministic, independently testable unit with zero LLM dependency of
its own, and treating it as separable means a team can build and fully test
it before subsystem I's LLM integration exists at all — write the gate
against synthetic LLM output first.

---

## I. Synthesis & Question Generation

**Status:** `SPEC'D` in `IMPLEMENTATION_PLAN.md` §6–7.

**Purpose:** the entire LLM-touching surface of the product, deliberately
narrow — question phrasing from `ChangeSet` templates, and synthesis prose
from retrieved items, gated by subsystem H.

**Interfaces**
- *In:* `ChangeSet` (from D), `list[Signal]` (from E), `Question`
- *Out:* phrased `Question` text, gated synthesis prose with citations

**Deliverables:** `case/questions.py` (templates, per
`IMPLEMENTATION_PLAN.md` §6), `synthesis/generate.py` (the one LLM call per
question), an `ATHENA_LLM_ENABLED` flag that degrades gracefully to
template-only output with the flag off — **this must be a real, tested code
path, not an aspiration**, because it's both the demo-reliability mechanism
and the low-resource deployment's "no LLM budget yet" mode.

**Low-resource-specific deliverable:** an abstraction boundary
(`synthesis/llm_client.py`) behind which a hosted API or a self-hosted
open-weight model can sit interchangeably. **State the open question
honestly rather than resolving it by assumption:** which open-weight models
produce adequate citation-constrained synthesis is unvalidated; this
subsystem's team should run subsystem H's gate against candidate open models
and report the accepted-sentence rate before recommending one for
low-resource default deployment.

---

## J. Access Pathway Registry

**Status:** `NEW`, prioritized per `Concept.md` §6 as the highest
value-per-effort component in the whole system.

**Purpose:** curated, citable regulatory/access routes — on-label, off-label,
recruiting trial, expanded access / compassionate use, named-patient import,
manufacturer programme — modeled as first-class nodes in Evidence Memory.

**Interfaces**
- *In:* hand-curated seed data (see below), cross-referenced against
  subsystem F's trial data
- *Out:* `AccessPathway` node type (add to `graph_schema.py`'s
  `ALL_NODE_TYPES`, alongside `TRIAL`), queryable from subsystem E

**Technical approach — curated, not scraped, per `ARCHITECTURE.md` §9.1:**
seed as versioned YAML, same pattern as `civic_scope.yaml`:

```yaml
# access_pathways/india.yaml
config_version: "2026-08-23.1"
country: IN
regulator: CDSCO
pathways:
  - pathway_type: compassionate_use
    instrument: "CDSCO New Drugs and Clinical Trials Rules, 2019 — Rule 36"
    description: >-
      Compassionate use / named-patient import for serious/life-threatening
      conditions with no satisfactory alternative therapy in India.
    precedent_examples: []   # populate as real, citable precedents are found
    source_url: "..."
```

```yaml
# access_pathways/us.yaml
country: US
regulator: FDA
pathways:
  - pathway_type: expanded_access_individual
    instrument: "FDA Form 3926 — Individual Patient Expanded Access"
    ...
```

**Deliverables:** `access_pathways/<country>.yaml` seeds (start with India +
US, expand by deployment region per `Concept.md` §8.6), a loader mirroring
`civic_loader.py`'s shape-verification discipline, and the crucial
distinguishing field: **`precedent_strength: theoretical | granted_before`**
— per `ARCHITECTURE.md` §6, "expanded access has been granted for this agent
before" is a materially different claim from "a pathway theoretically
exists," and the two must never render identically.

**Caveat:** this is a curation-heavy subsystem, not an engineering-heavy one.
The right team for it includes someone with regulatory-affairs or
access-office familiarity, not purely engineers — flag this explicitly when
staffing it.

---

## K. Structured Case Index

**Status:** `SPEC'D` in `CONCEPT_EVALUATION.md` §5, deliberately narrow.

**Purpose:** deterministic structural-similarity lookup across cases run
through *this specific deployment* — not a cross-institution or global
system, and not a learned-pattern claim.

**Deliverables:** `index/export.py` (allowlisted field export + a
k-anonymity gate that fails closed below threshold — build and test this
even though it will not pass any real export until deployment volume is
large enough), `index/similarity.py` (structured field-overlap scoring, per
`CONCEPT_EVALUATION.md` §5's `find_similar_cases` signature).

**Caveat, restated because it is the single easiest place for this whole
project to overclaim:** no embedding-based "whole case similarity," no
outcome-correlation claim, ever, until real N and real governance exist.
Every result must show exactly which fields matched and the N it's drawn
from, on screen, not just in documentation.

---

## L. API + MCP Interface Layer

**Status:** REST API `SPEC'D` in `IMPLEMENTATION_PLAN.md` §5; **MCP server
`NEW`**.

**Purpose:** the REST API is the system of record for all writes (case
creation, event append, decisions). The MCP layer is an **additive,
read-only** interface that lets any MCP-compatible client — Claude Desktop,
Claude Code, or a third-party clinical tool — query a case or the evidence
graph directly, without Athena needing to build or maintain a full custom
frontend for every deployment context.

**Why this matters specifically for the low-resource framing:** a full
custom frontend (subsystem M) is real, ongoing engineering cost. A read-only
MCP server exposing the same underlying queries lets a resource-constrained
deployment get a usable interface — through an existing chat client the
clinician may already have — before the dedicated frontend is fully built,
and keeps working alongside it afterward for anyone who prefers a chat
interface to a dashboard.

**Interfaces**
- *In:* MCP tool calls over the standard MCP transport
- *Out:* structured tool results, identical underlying data to the REST API

**Deliverables:** `mcp_server/` using the official open-source MCP Python
SDK, with a **small, explicitly read-only tool set**:

```python
# mcp_server/tools.py
get_case_summary(case_id: str) -> CaseSummary
get_recent_changes(case_id: str, since: str | None = None) -> ChangeSet
search_evidence(gene: str, variant: str | None, cancer_type: str | None) -> list[EvidenceItem]
match_trials(case_id: str) -> list[TrialMatchResult]
get_access_pathways(drug: str, country: str) -> list[AccessPathway]
```

**Explicit non-goal:** no write tools (`create_case`, `append_event`,
`record_decision` stay REST-only, confirmed by a clinician through the actual
UI). An MCP tool that lets an arbitrary chat client write clinical decisions
into a case is a safety problem this subsystem must not introduce — this
boundary is a hard requirement, not a v1-scoping convenience.

**Caveat:** this subsystem is a genuine cost-reduction lever for adoption,
but it is not a substitute for subsystem M's dashboard — the change-banner
strikethrough visual, which is the product's clearest single differentiator,
does not exist in a text-only chat client. Build both.

---

## M. Frontend / Low-Bandwidth Client Layer

**Status:** `SPEC'D` in `IMPLEMENTATION_PLAN.md` §9, with a low-resource
extension here.

**Purpose:** the three screens already designed — Case Dashboard, Research
Queue, Finding Detail — plus a bandwidth/device budget appropriate to the
deployment context this concept targets.

**Deliverables:** unchanged from `IMPLEMENTATION_PLAN.md` §9, plus:
1. A documented performance budget (target: usable on a low-end Android
   device over an intermittent 3G connection — this is a real constraint in
   many of the settings this concept targets, not a nice-to-have).
2. Server-rendered fallback for the Finding Detail and Brief views
   specifically — these are read-mostly and benefit least from a heavy
   client bundle.

**Explicitly deferred, not built:** a dedicated SMS/USSD interface. Worth
naming as a real future direction for the lowest-resource settings (no
smartphone, intermittent connectivity) but out of scope until the core
product is validated — flagging it here so it's a known, considered
omission rather than an unconsidered gap.

---

## N. Governance, De-identification & Privacy Gate

**Status:** `SPEC'D` in `CONCEPT_EVALUATION.md` §5 and
`patient-schema-mvp.md` §7. Summary only.

**Purpose:** the allowlist and k-anonymity enforcement that governs anything
moving from Case Memory toward the Structured Case Index (subsystem K), and
the no-PHI schema discipline in Case Memory itself (subsystem C).

**Deliverables:** the allowlist table from `CONCEPT_EVALUATION.md` §5,
implemented as a checked, tested function (`index/export.py`, shared with
subsystem K) rather than a policy document alone. A schema-level CI check
(subsystem C's caveat) that rejects any new column matching a disallowed-PHI
pattern.

**Caveat, stated once more because it is easy to build past accidentally:**
with hackathon/early-deployment case volumes, the k-anonymity threshold check
should **fail closed** — block export — essentially always. That is the
correct behavior, not a bug to work around.

---

## O. Open-Source Deployment & Cost Architecture

**Status:** `NEW`. This subsystem's deliverable is documentation and
tooling, not application logic — but it's what makes every other subsystem's
"self-hostable" claim real rather than aspirational.

**Purpose:** a deployment a resource-constrained institution can actually
stand up and afford to run.

**Deliverables**
1. **`docker-compose.yml` extended** to the full stack (FalkorDB, Postgres,
   API, frontend, and an optional local-model-serving container) — one
   command to a running instance, matching the existing convention of the
   current compose file covering FalkorDB alone.
2. **Hardware sizing guide** — documented minimum/recommended spec (CPU, RAM,
   disk) for a single-server deployment at small (one hospital), medium
   (regional network), scale. Write this from actual measurement against the
   seeded demo cases, not estimation.
3. **Cost model** — a simple worksheet: fixed infra cost (server/hosting) +
   marginal LLM cost per case (bounded by design principle 2 in `Concept.md`
   §8) at hosted-API pricing vs. self-hosted-model pricing, so an institution
   can actually budget before adopting.
4. **License audit** — a checked-in table of every dependency and data
   source with its license, enforced by CI (fail the build if a new
   dependency with an incompatible license is added) — this operationalizes
   design principle 1 rather than leaving it as a one-time manual check.
5. **Air-gapped / offline-first mode assessment** — many low-resource
   deployments have intermittent, not absent, connectivity. Document which
   subsystems degrade gracefully offline (Case Memory — fully; Evidence
   Memory — read cached, can't ingest new) and which don't (subsystem I's
   hosted-LLM path) — an honest capability matrix, not a claim of full
   offline operation unless and until that's actually built and tested.

**Caveat:** this subsystem is easy to under-resource because it produces no
visible feature. It is the difference between "open source" as a license
file and "open source" as something a district hospital's IT staff can
actually run — treat it as a first-class deliverable, not an afterthought
before a public release.

---

## Build-order guidance across subsystems

Not a rigid sequence — several can run in parallel once their interface
contracts (the "Interfaces" section of each) are agreed — but the
dependency structure is:

```
A (Evidence Graph) ──────┬──► E (Signal Generators) ──► I (Synthesis) ──► H (Gate)
                          │
C (Case Memory) ──────────┼──► D (Diff Engine) ──► G (Radar)
                          │         │
F (Trial Intelligence) ◄──┘         └──► K (Case Index) ◄── N (Governance)
      │
J (Access Pathways) ──────────────────────────────────────► E
                                                              │
                                              L (API/MCP) ◄───┴──► M (Frontend)
                                                              │
                                              O (Deployment) ─┘ wraps everything
```

**The one hard sequencing rule, carried over from `IMPLEMENTATION_PLAN.md`
§11:** subsystem D (the diff engine) is the load-bearing component every
other novel piece of this concept depends on, directly or through its
inverted index. If it's not built and tested first, every other team is
building against a contract that doesn't exist yet.
