# Athena — Implementation Plan

Derived from the audit in `athena-strategy-audit.md`, written against
`itskosky/Athena` @ `5f4017b`.

**Scope of this plan:** build the R&D loop — case store, diff engine, research
memory, review record, API, and a three-screen UI — on top of the existing,
working evidence graph. It does not modify the FalkorDB spine, the retrieval
modules, or the structural pipeline, except to wrap them.

**The one-line goal:** by day 4, `POST` a new finding to a case and get back a
typed list of what changed and which prior conclusions it invalidates.

---

## 0. Preconditions — day 1, before any feature work

These are cheap and they unblock everything else.

### 0.1 Reconcile the contradictory validation story

`ISSUES.md` and `validation/results.md` currently disagree about the project's
headline result. A judge who reads both will notice.

| Document | Currently says | Reality per `validation/results.md` |
|---|---|---|
| `ISSUES.md` §1 | 0/9, `scored_by_method: {'null': 9}` | 2/9 pass; 4/9 now produce a Vina delta |
| `ISSUES.md` §2 | meeko bug is the top open fix | Already fixed — `OpenBabelReceptorPreparer` is the default |
| `ISSUES.md` §1 | "pre-commit the proximity criterion… current data suggests it passes" | Criterion **was** pre-committed and **failed 7/8** (EGFR C797S) |

**Action:** rewrite `ISSUES.md` §1 and §2 to match `validation/results.md`. Add
a dated "Status as of <date>" line at the top of both. Keep the failures — do
not soften them. This is a 45-minute documentation task and it protects the
single strongest thing you have going into Q&A.

### 0.2 Mark `ARCHITECTURE.md` as proposed, not built

It describes `athena_ultimate/` and `src/athena/…`, which do not exist. Add at
the top:

```markdown
> **Status: PROPOSED DESIGN, not implemented.** The layout in §10 describes a
> target state. The current repo is `src/secondlook/`. Sections §5 (evidence
> classes), §6 (what we don't claim), and §8 (invariants) are in force today;
> the nine-stage pipeline in §4 is not built.
```

### 0.3 Everyone commits their own work

One commit, one author, on a team project is an avoidable Q&A liability. From
day 1, each team member commits under their own identity.

---

## 1. Infrastructure and dependencies

### 1.1 `pyproject.toml`

Add a new optional group so the existing offline test suite stays fast:

```toml
[project.optional-dependencies]
api = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.2",
    "alembic>=1.14",
    "pydantic>=2.9",
    "anthropic>=0.40",
]
```

Do **not** put these in core `dependencies`. The invariant in
`ARCHITECTURE.md` §8.10 (lazy-import heavy deps so an unrelated caller never
pays for them) applies here.

### 1.2 `docker-compose.yml`

Add Postgres alongside the existing FalkorDB service — do not replace it.

```yaml
  postgres:
    image: postgres:16
    container_name: athena-postgres
    environment:
      POSTGRES_DB: athena
      POSTGRES_USER: athena
      POSTGRES_PASSWORD: athena
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U athena"]
      interval: 5s
```

### 1.3 New package layout

Additive only. Nothing existing moves.

```
src/secondlook/
├── case/                    ← NEW: the R&D loop
│   ├── __init__.py
│   ├── models.py            SQLAlchemy models
│   ├── state.py             event log → derived CaseState
│   ├── assumptions.py       typed assumption predicates  ← the crux
│   ├── diff.py              CaseState × CaseState → ChangeSet   ← the product
│   ├── questions.py         ChangeSet → Questions, with dedup
│   ├── memory.py            suppression / supersession queries
│   └── store.py             repository layer over Postgres
├── api/                     ← NEW: HTTP surface
│   ├── __init__.py
│   ├── app.py               FastAPI app
│   ├── routes_cases.py
│   ├── routes_research.py
│   └── schemas.py           Pydantic request/response
├── synthesis/               ← NEW
│   ├── __init__.py
│   ├── generate.py          the one LLM call
│   └── citation_gate.py     deterministic post-check
├── tier1/
│   └── ctgov_loader.py      ← NEW: the one new data source
└── (everything else unchanged)
```

---

## 2. Data model

Postgres holds **the case**. FalkorDB holds **the world**. They join at exactly
one place: `Finding.evidence_ref`.

### 2.1 Core principle — append-only

`CaseEvent` is never updated or deleted. Current state is *derived* by folding
the event log. This gives you the decision timeline ("what was known when") for
free, and makes the diff engine trivially testable because it's a pure function
of two derived states.

### 2.2 Schema

```sql
-- A case. No PHI: no name, no DOB, no MRN.
CREATE TABLE cases (
    id              UUID PRIMARY KEY,
    label           TEXT NOT NULL,          -- "Case A — synovial sarcoma"
    age_years       INT,                    -- P0
    cancer_type     TEXT NOT NULL,          -- P0
    primary_site    TEXT,
    histology       TEXT,
    doid            TEXT,                   -- joins to Disease in FalkorDB
    created_at      TIMESTAMPTZ NOT NULL
);

-- Append-only. The source of truth.
CREATE TABLE case_events (
    id              UUID PRIMARY KEY,
    case_id         UUID NOT NULL REFERENCES cases(id),
    event_type      TEXT NOT NULL,          -- see taxonomy below
    payload         JSONB NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL,   -- clinical date (when it happened)
    recorded_at     TIMESTAMPTZ NOT NULL,   -- system date (when we learned)
    source_document TEXT,
    recorded_by     TEXT,
    CONSTRAINT no_update CHECK (true)       -- enforced in the repository layer
);
CREATE INDEX ON case_events (case_id, occurred_at);

-- A research question. Deduped against prior questions.
CREATE TABLE questions (
    id              UUID PRIMARY KEY,
    case_id         UUID NOT NULL REFERENCES cases(id),
    text            TEXT NOT NULL,
    status          TEXT NOT NULL,          -- open|answered|suppressed|rejected
    priority        INT NOT NULL,
    triggered_by    JSONB,                  -- the Change that generated it
    suppressed_by   UUID REFERENCES questions(id),  -- dedup target
    created_at      TIMESTAMPTZ NOT NULL
);

-- A cited finding answering a question. Joins to the graph.
CREATE TABLE findings (
    id              UUID PRIMARY KEY,
    question_id     UUID NOT NULL REFERENCES questions(id),
    claim           TEXT NOT NULL,
    evidence_class  TEXT NOT NULL,          -- documented|computed|regulatory|contextual
    evidence_ref    JSONB NOT NULL,         -- {source, civic_id|pmid|nct_id, url}
    evidence_level  TEXT,
    assumptions     JSONB NOT NULL,         -- list[Assumption]  ← the crux
    status          TEXT NOT NULL,          -- active|superseded
    superseded_by   UUID REFERENCES case_events(id),
    superseded_note TEXT,
    created_at      TIMESTAMPTZ NOT NULL
);

-- The clinician's review. This is what makes it a loop.
CREATE TABLE decisions (
    id              UUID PRIMARY KEY,
    finding_id      UUID NOT NULL REFERENCES findings(id),
    action          TEXT NOT NULL,          -- investigating|deferred|rejected
    reason          TEXT NOT NULL,          -- required, even for "investigating"
    decided_by      TEXT NOT NULL,
    decided_at      TIMESTAMPTZ NOT NULL
);
```

### 2.3 Event taxonomy — keep it to five

Resist adding more. Five covers the demo and every additional type multiplies
diff-engine test surface.

| `event_type` | `payload` shape |
|---|---|
| `ALTERATION_OBSERVED` | `{gene, variant, variant_type, assay, tested_on}` |
| `BIOMARKER_MEASURED` | `{name, value, unit, measured_on}` |
| `TREATMENT_LINE` | `{regimen, line, action: started\|stopped, reason}` |
| `DISEASE_ASSESSMENT` | `{status: response\|stable\|progression, sites, assessed_on}` |
| `CLINICAL_QUESTION` | `{text}` |

---

## 3. The diff engine — the single most important component

`src/secondlook/case/diff.py`. **Pure functions. No I/O. No LLM. No database
access.** It takes two `CaseState` objects and returns a `ChangeSet`. This
constraint is what makes it fully unit-testable offline, consistent with the
existing suite's DI discipline.

### 3.1 The crux: typed assumptions

This is the mechanism that makes the demo's wow moment real rather than
hardcoded, so it's worth getting right.

Every `Finding` records the assumptions it depends on, as **structured
predicates over case state** — not prose. When state changes, re-evaluate every
active finding's assumptions. Any that now evaluate false → the finding is
superseded, automatically, with a machine-generated reason.

```python
# src/secondlook/case/assumptions.py
from dataclasses import dataclass
from typing import Protocol

class Assumption(Protocol):
    def holds(self, state: "CaseState") -> bool: ...
    def describe(self) -> str: ...

@dataclass(frozen=True)
class NoAlterationIn:
    gene: str
    def holds(self, state):
        return not any(a.gene == self.gene for a in state.alterations)
    def describe(self):
        return f"no known alteration in {self.gene}"

@dataclass(frozen=True)
class BiomarkerBelow:
    name: str
    threshold: float
    def holds(self, state):
        v = state.biomarkers.get(self.name)
        return v is None or v.value < self.threshold
    def describe(self):
        return f"{self.name} below {self.threshold}"

@dataclass(frozen=True)
class DrugNotYetTried:
    drug: str
    def holds(self, state):
        return self.drug.lower() not in {t.regimen.lower() for t in state.treatments}
    def describe(self):
        return f"{self.drug} not previously administered"

@dataclass(frozen=True)
class DiseaseNotProgressing:
    def holds(self, state):
        return state.latest_assessment != "progression"
    def describe(self):
        return "disease not recorded as progressing"
```

Four assumption types is enough. Add more only when a demo case needs one.

### 3.2 Change taxonomy — four types

```python
# src/secondlook/case/diff.py
from dataclasses import dataclass
from enum import Enum

class ChangeKind(str, Enum):
    NEW_ALTERATION       = "new_alteration"
    BIOMARKER_SHIFT      = "biomarker_shift"
    TREATMENT_LINE_CHANGE= "treatment_line_change"
    DISEASE_PROGRESSION  = "disease_progression"

@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    summary: str              # "EGFR T790M newly observed (14 Feb)"
    detail: dict
    triggering_event_id: str

@dataclass(frozen=True)
class Supersession:
    finding_id: str
    broken_assumption: str    # from Assumption.describe()
    triggering_event_id: str
    note: str

@dataclass(frozen=True)
class ChangeSet:
    changes: tuple[Change, ...]
    supersessions: tuple[Supersession, ...]
    unchanged_reason: str | None   # populated when empty — never a silent gap

    @property
    def is_empty(self) -> bool:
        return not self.changes and not self.supersessions
```

### 3.3 The function

```python
def compute_diff(
    previous: CaseState,
    current:  CaseState,
    active_findings: tuple[Finding, ...],
    *,
    biomarker_thresholds: dict[str, float],
) -> ChangeSet:
    """Pure. Deterministic. Same inputs -> byte-identical output, always."""
    changes = []

    # 1. New alterations
    prev_alts = {(a.gene, a.variant) for a in previous.alterations}
    for alt in current.alterations:
        if (alt.gene, alt.variant) not in prev_alts:
            changes.append(Change(
                kind=ChangeKind.NEW_ALTERATION,
                summary=f"{alt.gene} {alt.variant} newly observed",
                detail={"gene": alt.gene, "variant": alt.variant,
                        "assay": alt.assay},
                triggering_event_id=alt.event_id,
            ))

    # 2. Biomarker crossing a configured threshold (not any change — a crossing)
    for name, cur in current.biomarkers.items():
        prev = previous.biomarkers.get(name)
        thresh = biomarker_thresholds.get(name)
        if prev is None or thresh is None:
            continue
        if (prev.value < thresh) != (cur.value < thresh):
            changes.append(Change(
                kind=ChangeKind.BIOMARKER_SHIFT,
                summary=f"{name} crossed {thresh} ({prev.value} -> {cur.value})",
                detail={"name": name, "from": prev.value, "to": cur.value,
                        "threshold": thresh},
                triggering_event_id=cur.event_id,
            ))

    # 3. Treatment line changes
    # 4. Disease assessment changes
    #    ... same shape

    # 5. Supersession — re-evaluate every active finding's assumptions
    supersessions = []
    for finding in active_findings:
        for assumption in finding.assumptions:
            if not assumption.holds(current):
                supersessions.append(Supersession(
                    finding_id=finding.id,
                    broken_assumption=assumption.describe(),
                    triggering_event_id=_event_that_broke(assumption, current),
                    note=(f"This finding assumed {assumption.describe()}. "
                          f"That is no longer true."),
                ))
                break

    return ChangeSet(
        changes=tuple(changes),
        supersessions=tuple(supersessions),
        unchanged_reason=None if (changes or supersessions)
                         else "No tracked field changed between these states.",
    )
```

Note `unchanged_reason` — this follows the existing repo invariant
(`ARCHITECTURE.md` §8.1): never a silent gap, always empty-*with-reason*.

### 3.4 Tests — write these before the implementation

`tests/case/test_diff.py`, minimum 30 cases, all offline:

- New alteration detected · identical states produce empty ChangeSet with a
  reason · re-adding an existing alteration is not a change · biomarker moving
  *within* a band is not a change · biomarker crossing in either direction is ·
  threshold absent → no change emitted · treatment started / stopped · disease
  progression recorded · **supersession fires when `NoAlterationIn` breaks** ·
  supersession does *not* fire for an unrelated finding · a finding with zero
  assumptions is never superseded · multiple broken assumptions on one finding
  produce exactly one supersession · determinism: run 100× on the same input,
  assert identical output.

That last one matters. It's the property the whole product rests on.

---

## 4. Research memory

`src/secondlook/case/memory.py`. Two responsibilities.

### 4.1 Question suppression

Before creating a question, check it against every prior question on the case:

```python
def suppress_duplicates(
    new_questions: list[str],
    prior: list[Question],
    *,
    embed_fn,                      # injected — reuse tier1.semantic_retrieval.embed_text
    similarity_threshold: float = 0.88,
) -> tuple[list[str], list[tuple[str, Question]]]:
    """Returns (kept, [(suppressed_text, matched_prior_question)]).

    Suppressed questions are RETURNED, never dropped silently — the UI shows
    the count, and that count is the demo's second-order wow moment.
    """
```

Threshold 0.88 is a starting point — tune it on your seed cases and **write the
chosen value down with the date and the cases it was tuned on.** Do not tune it
during the demo.

If `sentence-transformers` remains blocked (`ISSUES.md` §10), fall back to
normalized-string + gene-symbol overlap matching. Ship the fallback first; it's
adequate for two seeded cases and removes a dependency risk from the demo path.

### 4.2 Supersession application

```python
def apply_supersessions(session, change_set: ChangeSet) -> int:
    """Mark findings superseded. Returns count. Never deletes."""
```

Findings are never deleted — they're marked `superseded` and rendered struck
through. The historical record is the point.

---

## 5. API surface

`src/secondlook/api/`. Thin. All real logic lives in `case/` and `tier1/`.

| Method | Route | Does |
|---|---|---|
| `POST` | `/api/cases` | Create case from the 6 P0 fields |
| `GET` | `/api/cases/{id}` | Case + derived current state + timeline |
| `POST` | `/api/cases/{id}/events` | Append event → **run diff** → return `ChangeSet` |
| `GET` | `/api/cases/{id}/changes` | Most recent ChangeSet |
| `POST` | `/api/cases/{id}/research` | ChangeSet → questions → retrieval → findings |
| `GET` | `/api/cases/{id}/queue` | Questions: open / answered / suppressed counts |
| `GET` | `/api/findings/{id}` | Finding + full provenance chain |
| `POST` | `/api/findings/{id}/decision` | Record clinician review |
| `GET` | `/api/cases/{id}/brief` | Tumour-board brief (HTML print view) |

**The key endpoint is `POST /events`.** It returns the ChangeSet synchronously.
That single response — `2 changes, 1 supersession` — is the demo.

Reuse `docs/api-contracts.md`'s existing result-item shapes and its
`failures[]` rule verbatim. That spec is good and already written; don't
redesign it.

---

## 6. Question generation

`src/secondlook/case/questions.py`. **The ChangeSet decides what to ask about;
the LLM only phrases it.** Never let the LLM decide *whether* something is
worth asking — that's the diff engine's job, and it must be deterministic.

```python
QUESTION_TEMPLATES = {
    ChangeKind.NEW_ALTERATION: [
        "What documented evidence exists for {gene} {variant} in {cancer_type}?",
        "Are there recruiting trials matching {gene} {variant}?",
        "Does {gene} {variant} confer resistance to any component of the "
        "current regimen?",
    ],
    ChangeKind.BIOMARKER_SHIFT: [
        "What does {name} crossing {threshold} imply for treatment options "
        "in {cancer_type}?",
    ],
    ChangeKind.DISEASE_PROGRESSION: [
        "What resistance mechanisms are documented for {last_regimen} in "
        "{cancer_type}?",
    ],
    ChangeKind.TREATMENT_LINE_CHANGE: [
        "What options are documented after {line} line {regimen} in "
        "{cancer_type}?",
    ],
}
```

Templates fill deterministically from the `Change.detail` dict. The LLM call is
optional polish (rephrase for readability) and **the demo must work with it
disabled** — set `ATHENA_LLM_ENABLED=false` and verify the whole flow still
runs. That's your insurance against an API outage on stage.

---

## 7. Synthesis and the citation gate

`src/secondlook/synthesis/`. One LLM call per question, then a deterministic
gate.

```python
# citation_gate.py
def enforce_citations(
    synthesis_text: str,
    retrieved_items: list[dict],
) -> tuple[str, list[str], int]:
    """Returns (accepted_text, cited_ids, dropped_sentence_count).

    Every sentence must carry >=1 citation marker resolving to an item
    actually present in retrieved_items. Sentences that don't are REMOVED
    and COUNTED. The count is returned and rendered — never silently
    swallowed. Mirrors tier1/retrieval.py's existing `filtered_count`.
    """
```

This is a gate, not a prompt instruction. `docs/api-contracts.md` already
specifies the rule ("enforce with a post-generation check… don't rely on the
prompt alone") — this implements it.

Prompt constraints for the synthesis call:
- Input is only the retrieved items. No case data beyond the question text.
- Output must be sentences each ending with `[ref:<item_id>]`.
- Never assert a treatment recommendation; describe evidence only.

---

## 8. ClinicalTrials.gov loader

`src/secondlook/tier1/ctgov_loader.py`. The one new external source. The
`Trial` NodeType is **already declared** in `graph_schema.py` with
`registry_id`, `registry`, `status`, `phase`, `locations`, `country_codes`,
`eligibility_url` — populate it.

- Endpoint: ClinicalTrials.gov API v2, REST, free, no auth.
- Query by condition (from `cancer_type`) + intervention/other-term (gene symbol).
- Filter to recruiting/not-yet-recruiting.
- Route every node write through `with_provenance(source="ClinicalTrials.gov")`.
- Verify parsed response *shape* before loading, mirroring `civic_verify.py` —
  invariant §8.6: a status code is not a shape check. Write
  `ctgov_verify.py` in the same shape.

**When this lands, delete the caveat string** in `tier1_adapter._classify`
("Trial half of the strong-hit rule not evaluated") — `ISSUES.md` §5 closes.

---

## 9. Frontend

Plain React + Vite. No design system. Three screens plus a print view.

| Screen | Route | Must show |
|---|---|---|
| **Case Dashboard** | `/cases/:id` | Timeline of events (clinical dates), current state panel, **change banner** |
| **Research Queue** | `/cases/:id/queue` | Open questions by priority; **"N suppressed as already answered"** as a visible count |
| **Finding Detail** | `/findings/:id` | Claim, evidence class badge, full provenance chain (clickable to PubMed/CIViC), review buttons |
| **Brief** | `/cases/:id/brief` | Server-rendered HTML, print stylesheet |

### 9.1 The change banner — give this real design time

This is the wow moment; everything else can be ugly.

```
┌────────────────────────────────────────────────────────────┐
│  ⚠  3 CHANGES SINCE 02 JAN                                 │
│                                                            │
│  + EGFR T790M newly observed            (sequencing 14 Feb)│
│  ↑ PD-L1 crossed 50%  (35% → 62%)       (IHC 14 Feb)       │
│                                                            │
│  ⊘ 2 PRIOR FINDINGS SUPERSEDED                             │
│    ~~Finding #7: osimertinib-naive, EGFR-TKI candidate~~   │
│       This finding assumed no known alteration in EGFR.    │
│       That is no longer true. → 14 Feb sequencing          │
└────────────────────────────────────────────────────────────┘
```

The strikethrough must be literal `text-decoration: line-through`, visible
from the back of the room.

### 9.2 Evidence class rendering — structurally distinct

Per `ARCHITECTURE.md` §5, four classes, visually unmistakable:

| Class | Border | Accent | Carries |
|---|---|---|---|
| `documented` | Solid | Green | Clickable citation URL, always |
| `computed` | Dashed | Amber | Method + version + disclaimer, **no citation field at all** |
| `regulatory` | Solid | Blue | Instrument cited; precedent stated separately |
| `contextual` | Dotted | Grey | Visually subordinate; can never drive an option |

The `computed` card must have **no place** for a citation — not an empty one.
`graph.py` already enforces this in the data model; the UI must not reintroduce
the ambiguity.

---

## 10. Seed data

Two synthetic cases, committed as YAML under `seeds/`. No real PHI, ever, and
say "synthetic" on the demo slide.

**Case A — the demo case.** In-scope sarcoma so Tier 1 actually returns real
CIViC hits (the loaded scope is 17 sarcoma DOIDs — check `civic_scope.yaml`
and pick a disease and gene that genuinely resolve against your loaded graph).

```yaml
# seeds/case_a.yaml
case:
  label: "Case A — synthetic"
  age_years: 34
  cancer_type: "Synovial sarcoma"
  doid: "5485"
events:
  # --- Day 0 state (pre-loaded, so the demo opens with memory) ---
  - type: ALTERATION_OBSERVED
    occurred_at: 2026-01-02
    payload: {gene: "...", variant: "...", assay: "NGS panel"}
  - type: TREATMENT_LINE
    occurred_at: 2026-01-05
    payload: {regimen: "...", line: 1, action: stopped, reason: progression}
  # --- Day 47 delta (injected LIVE during the demo) ---
  - type: ALTERATION_OBSERVED
    occurred_at: 2026-02-14
    inject_at_demo: true
    payload: {gene: "...", variant: "...", assay: "NGS panel"}
```

**Critical:** run the Day-0 research pass *before* the demo and persist the
results, so the dashboard opens with 4 questions, ~11 findings, and 3 recorded
decisions already present. Starting from an empty case destroys the entire
premise.

Pick the Day-47 alteration specifically so it breaks a `NoAlterationIn`
assumption on a Day-0 finding. Verify the supersession fires, repeatedly,
before demo day.

---

## 11. Day-by-day

| Day | Work | Done when |
|---|---|---|
| **1** | §0 reconciliation. Deps, Postgres in compose, package skeleton. | `docker compose up` brings both DBs; `pytest` still green |
| **2** | `models.py`, `store.py`, alembic migration, `state.py` (event fold). | Can create a case, append events, derive state |
| **3** | **`assumptions.py` + `diff.py` + 30 tests.** Nothing else. | `pytest tests/case/test_diff.py` green, including the determinism test |
| **4** | FastAPI app; `POST /events` returns a real ChangeSet. Wrap existing `retrieve_exact`/`retrieve_relaxed`. | **`curl` a new alteration, get back changes + supersessions** |
| **5** | `questions.py` templates + `memory.py` suppression (string fallback first). | Queue endpoint returns open + suppressed counts |
| **6** | `synthesis/` + citation gate + `ATHENA_LLM_ENABLED=false` path. | Findings carry real citations; gate drops and counts uncited sentences |
| **7** | `ctgov_loader.py` + `ctgov_verify.py`; drop the `_classify` caveat string. | Trial nodes in graph; `ISSUES.md` §5 closed |
| **8** | Dashboard screen + **change banner**. | Banner renders with strikethrough |
| **9** | Queue + Finding Detail screens; evidence-class styling. | Provenance chain clicks through to a real PMID |
| **10** | Seed both cases; run and persist the Day-0 pass. | Dashboard opens with memory present |
| **11** | Brief print view. Proximity as one caveated signal. Cache every demo-path call. | Demo runs with network off |
| **12** | **Rehearse 5×, end to end, timed.** | Same output every run |
| **13** | Buffer. | |
| **14** | Slides; Q&A prep on "how is this not ChatGPT" and "what failed validation". | |

---

## 12. Demo-path hardening

`src/secondlook/cache.py` already exists and already marks cached payloads as
cached on read (never trusting the flag from disk). Use it on **every**
external call in the demo path.

Pre-demo checklist — extend the existing five in `README.md` §7:

```bash
# 6. Postgres reachable
docker exec athena-postgres pg_isready -U athena

# 7. Diff engine determinism
pytest tests/case/test_diff.py -q | tail -1

# 8. Demo runs with the LLM disabled
ATHENA_LLM_ENABLED=false python -m secondlook.api.smoke_demo

# 9. Demo runs with external network blocked (cache only)
ATHENA_OFFLINE=true python -m secondlook.api.smoke_demo

# 10. Supersession fires on the seeded Day-47 event
pytest tests/case/test_seed_case_a.py -q | tail -1
```

Check 10 is the one that matters. If the supersession doesn't fire, there is no
demo.

---

## 13. Invariants — carried over, do not renegotiate

All ten in `ARCHITECTURE.md` §8 remain in force. Three apply with particular
force to the new code:

1. **No evidence, no claim — and no silent gaps.** Every empty result carries a
   reason (`ChangeSet.unchanged_reason`), every filtered item is counted and
   returned (`suppress_duplicates`, `enforce_citations`).
2. **Dependency injection everywhere.** `compute_diff` takes state objects, not
   a session. `suppress_duplicates` takes `embed_fn`. This is why the suite runs
   offline, and the new code must not break it.
3. **A status code is not a shape check.** `ctgov_verify.py` asserts on parsed
   structure, like `civic_verify.py`.

And one new invariant specific to the loop:

11. **The diff engine is deterministic and never calls an LLM.** If a change
    set differs between two runs on identical input, that is a P0 bug. The
    entire product claim — that Athena remembers and can tell you what changed —
    depends on the diff being reproducible.

---

## 14. Explicitly not in this plan

Named so nobody re-litigates them mid-week:

- `ARCHITECTURE.md` stages 4 (modality mapping), 6 (access pathways), 8
  (combination reasoning)
- Cohort/TCGA contextual targets
- Expression-data target discovery — the real Sid mechanism, and a project in
  itself
- Binding-affinity delta as an output (failed validation 2/9)
- Proximity as a validated classifier (failed 7/8) — ships as a *measurement
  with its caveat*, if at all
- Multi-agent orchestration, agentic search loops
- Auth, multi-tenancy, EHR integration, DICOM, mobile
- CTRI (access mode unverified — `ARCHITECTURE.md` §9.3; don't gate a demo on it)
- Anything MdrDB-derived (licence is academic-only and non-transferable)
