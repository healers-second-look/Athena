# Athena — Concept Evaluation: OncoSphere / Case Memory / Global Memory

Written against `athena-strategy-audit.md` and `IMPLEMENTATION_PLAN.md`,
which this document does not repeat — it evaluates where the three-layer
concept agrees with that prior work, where it conflicts, and redesigns the
parts that don't hold up.

**Headline verdict, stated up front so it isn't buried:** two of your three
layers are right and one is currently proposing exactly the failure mode the
prior audit warned against by name. Layer 2 (Case Memory) *is* the diff
engine and case store already designed in `IMPLEMENTATION_PLAN.md` — keep it
exactly as is, this document just confirms it's the core. Layer 1
(OncoSphere) as described — autonomous agents that "debate" and reach
"consensus" — is multi-agent-for-the-sake-of-multi-agent, and it's worth
being precise about why that's a real problem, not a style preference. Layer
3 (Global Memory) is the most interesting long-term idea and the most
dangerous near-term one; at hackathon scale it should be almost nothing.

---

## 1. Precise product definition

**For an oncologist:**
Athena keeps a structured, permanent research record for a hard cancer case.
Every time new data arrives, it tells you exactly what changed, which of your
team's prior conclusions that invalidates, and what evidence exists on the
new questions that opens up — without re-showing you what you already ruled
out.

**For a technical judge:**
An event-sourced case store with a deterministic diff engine over typed
clinical state, feeding a citation-gated retrieval pipeline against a
provenance-tracked evidence graph (CIViC, PubMed, ClinicalTrials.gov). One
LLM call per research question, constrained by the diff — not an agent
framework.

**For a non-technical judge:**
Most AI health tools answer one question and forget you asked it. Athena
remembers the whole case, notices when new results change the picture, and
tells you specifically what's now different — instead of making you start
over every time.

**For an investor:**
A structured, longitudinal clinical research record that gets more valuable
per case the longer it's used — not a chatbot wrapper, a system whose output
compounds because it remembers.

**What "OncoSphere" and "tumor board" should NOT appear in:** the technical
pitch. They're a UX metaphor (organize findings by specialist dimension), not
an architecture claim. Say what it actually is to judges who can check.

---

## 2. Validating the three-layer architecture

| Layer | Necessary? | True role |
|---|---|---|
| Persistent Case Memory | **Yes — this is the product** | State, diff, memory, supersession. Already fully designed in `IMPLEMENTATION_PLAN.md` §2–4. |
| OncoSphere AI | **Partially — as a rendering/routing metaphor, not an agent framework** | Organizes signal generators by clinical dimension. See §3 for the redesign. |
| Persistent Global Memory | **Conceptually yes, practically almost-nothing at hackathon scale** | Real long-term differentiator, real near-term risk. See §5. |

**Which is the true core?** Case Memory, unambiguously. Delete OncoSphere and
Global Memory entirely and you still have a real, differentiated, demoable
product — the retraction/supersession moment from the prior audit doesn't
need agents or cross-patient learning. Delete Case Memory and you have a
research assistant with a tumor-board skin — which is what nearly every
competing "AI health" tool already is.

**What must never cross between layers:** identifiable patient data must
never reach Global Memory in any form — not summarized, not embedded, not
"anonymized" by removing name/DOB alone (re-identification from a rare
cancer type + age + molecular profile is a real risk with small N, discussed
in §5). And Global Memory must never write *back* into a specific case's
facts — only ever surface as a separately-labeled, clearly-caveated
`contextual` signal, per the evidence-class rule already established.

---

## 3. Redesigning OncoSphere — the part that needs real pushback

### Where the instinct is right

Organizing findings by clinical dimension — genomics, pathology, trials,
literature, pharmacology — is good UX and good provenance hygiene. A
clinician scanning results wants to know "what does the trials angle say"
separately from "what does the literature say." Keep that framing.

### Where it's wrong, specifically

The brief asks *"how do we prevent agents from simply agreeing with each
other"* and *"how are conflicts resolved."* Those are the right questions to
ask about a design — and the fact that they need asking is the signal the
design is wrong. An architecture that requires a conflict-resolution
mechanism between autonomous reasoning agents is introducing a problem that a
deterministic pipeline doesn't have in the first place.

Three concrete failure modes, not hypothetical:

1. **Consensus without justification.** Multi-agent "debate" setups
   reliably converge toward agreement under mild social/framing pressure
   regardless of which position is actually better supported — the same
   sycophancy dynamic that shows up in single-model RLHF, amplified by
   agents mirroring each other's confidence. A "verified by three agents"
   badge is not evidence; it's theater that *looks* like evidence, which is
   worse than no badge.
2. **Nondeterminism where the product needs determinism.** `IMPLEMENTATION_PLAN.md`
   §13 makes the diff engine's determinism a P0 invariant precisely because
   the whole memory claim depends on it. An orchestrator making autonomous
   routing decisions about which agents to invoke, in what order, reintroduces
   exactly the nondeterminism you spent effort designing out of the layer
   that matters.
3. **Cost and demo risk with no corresponding capability gain.** Every one of
   the "agent" roles in the brief — genomics, trials, literature, pharmacology —
   maps directly onto an existing, working, deterministic function:
   `tier1/retrieval.py`, the (soon-to-exist) `ctgov_loader.py`, PubMed
   retrieval. Wrapping each in an autonomous agent with its own reasoning
   loop doesn't add a capability; it adds five more places for the demo to
   time out or hallucinate a step, for a benefit that doesn't exist yet.

### The redesign

**OncoSphere is `ARCHITECTURE.md`'s Stage 7 signal generators, running in
parallel, framed for the UI by clinical dimension — not autonomous agents.**

```
                    ChangeSet (from the diff engine)
                              │
        ┌──────────┬─────────┼─────────┬──────────┐
        ▼          ▼         ▼         ▼          ▼
   Genomics    Trials    Literature  Pharma    (Structural,
   generator   generator  generator  generator  when relevant)
   [Cypher]    [REST]     [Cypher+   [Cypher]   [existing
                           embed]                Tier 2]
        └──────────┴─────────┼─────────┴──────────┘
                              ▼
                    Independent Signals, each carrying
                    its own evidence_class (§5 of
                    ARCHITECTURE.md) — never merged,
                    never made to "agree"
                              ▼
                    Deterministic synthesis: juxtapose,
                    don't resolve. Disagreement is
                    SHOWN, not adjudicated by a model.
                              ▼
                       Clinician decides
```

Each "specialist" is a typed function: `(ChangeSet, Question) -> list[Signal]`.
No reasoning loop, no tool-calling autonomy, no persuasion between them. If
two signals conflict — CIViC says sensitive, a recent paper suggests
resistance — **that conflict is rendered directly to the clinician as a
labeled disagreement.** This is safer, cheaper, faster, and more honest than
having agents argue it out and present a single answer.

**Where an LLM legitimately belongs here:** rephrasing a generator's
structured output into readable prose, and only that, per the existing rule
in `IMPLEMENTATION_PLAN.md` §6 — the *content* of what to look for comes from
the ChangeSet and the retrieved items, never from an agent's own initiative.

**One thing worth keeping from the brief:** an **evidence verification**
step. Not as a debating agent — as the deterministic citation gate that
already exists in `IMPLEMENTATION_PLAN.md` §7 (`enforce_citations`). That's
your "evidence verifier," and it's better than an agent because it can't be
talked out of its job.

---

## 4. Persistent Case Memory — confirming the design, adding the four-way split

This layer is already correctly designed. Restating it here in the brief's
own framing, because getting the Facts/Evidence/Interpretation/Hypothesis/
Decision separation exactly right is worth being explicit about:

| Category | Example | Where it lives | Who/what can write it |
|---|---|---|---|
| **Patient fact** | "EGFR T790M, sequenced 14 Feb" | `case_events` (append-only) | Clinician/extraction-with-confirmation only. **Never an LLM unattended.** |
| **Scientific evidence** | "CIViC Level B: osimertinib sensitivity" | `findings.evidence_class = documented` | Retrieval only, citation-gated |
| **AI interpretation** | "This pattern is consistent with acquired resistance" | `findings.evidence_class = computed`, or a distinct `interpretation` field | LLM, always labeled, always subordinate, always tied to ≥1 fact + ≥1 evidence item |
| **Hypothesis** | "Consider re-biopsy to confirm histologic transformation" | `questions` (open, unanswered) | Generated from a `Change`, never asserted as a finding |
| **Clinical decision** | "Investigating; will order re-biopsy" | `decisions` | Clinician only, `action` + mandatory `reason` |

This is precisely `IMPLEMENTATION_PLAN.md` §2.2's schema. No new tables
needed — the brief's five-way distinction maps onto the four tables already
designed, with `interpretation` as a field on `findings` rather than a new
table (a `computed`-class finding *is* an AI interpretation by definition;
don't fork the model).

**One addition worth making:** stamp every LLM-touched row with
`generator_version` and `prompt_template_id`, mirroring the existing
`STRUCTURAL_SIGNAL.pipeline_version`/`labeling_version` convention in
`graph_schema.py`. If an interpretation turns out wrong, you need to know
which prompt version produced it.

---

## 5. Persistent Global Memory — the dangerous one, redesigned narrow

### The honest technical problem

Real pattern-learning across cases needs real N. A hackathon has two or three
synthetic seed cases. **There is no statistically meaningful pattern to
learn from three data points**, and presenting one as if there were is
exactly the "confident nonsense" failure mode `ARCHITECTURE.md` §4 already
names for cohort-derived targets: *"this gene is overexpressed in this
tumor type" does not establish it's a druggable target for this patient* —
the same warning applies one level up to *"cases like this responded well"*
built on n=3.

### The redesign: rename it, and shrink its claim to what's actually true

**Rename "Global Memory" to something that doesn't imply learning:
"Structured Case Index"** (or, if you want a name with more product
weight later, "De-identified Case Knowledge Graph" — but not yet, and not
until it's actually a graph of more than a handful of cases). "Memory"
implies the system remembers and reasons across cases the way it reasons
within one; at hackathon scale it should do neither.

**What it should actually do at hackathon scale: deterministic structural
similarity, not learned pattern discovery.**

```python
def find_similar_cases(
    case: CaseState,
    corpus: list[DeidentifiedCaseSummary],
    *,
    weights: dict[str, float],   # visible, adjustable — same rule as
) -> list[SimilarCase]:          # ARCHITECTURE.md §9 stage 9 scorecards
    """Structured field overlap (same gene+variant class, same cancer_type,
    overlapping treatment history) -> a ranked list, EACH result showing
    exactly which fields matched. No embedding-based 'semantic similarity
    of the whole case' — that's an unfalsifiable claim with three cases in
    the corpus. No claim about outcome correlation. No claim about what
    'usually happens'. Just: these two structured profiles overlap on X, Y, Z.
    """
```

Rendered as: **"1 structurally similar case in this corpus — matches on
gene, variant class, and prior treatment; outcome not shown because N=1 is
not a pattern."** That last clause matters — say the limitation in the UI,
not just in your own head.

### What can move from Case Memory → this index, and what never can

| Can move (aggregated/structural only) | Can never move |
|---|---|
| Gene + variant *type* (not raw HGVS string, to reduce re-identifiability at low N) | Age (exact), only a decade bucket |
| Cancer type, disease stage bucket | Any free-text note, source document, or extraction |
| Treatment-line outcome category (responded/progressed/stopped-for-toxicity) | Dates (use elapsed intervals, never calendar dates) |
| Which evidence items/CIViC IDs were found relevant | Case label, any identifier traceable to the originating case |
| — | Anything below a k-anonymity threshold (with N=2–3 hackathon cases, **the honest answer is: nothing moves yet — flag this explicitly rather than fake a threshold check**) |

**Governance, stated plainly for the hackathon:** with only synthetic seed
cases, there is no real de-identification problem to solve yet, and no real
consent/governance framework to build — say that directly rather than
building an elaborate privacy pipeline for data that doesn't exist. What you
*should* build is the schema and the interface that would enforce it once
real cases exist: a `case_summary_export()` function with an explicit
allowlist of fields (the left column above), a k-anonymity check that
currently always fails-safe (blocks export below threshold) — implemented
and tested, even though it never actually runs against real data this week.
That's a legitimate, honest "designed for it, not certified" claim, same
posture as the PHI section in the prior audit.

### Terminology recommendation

Use **"Structured Case Index"** for the hackathon-scale version you actually
build. Reserve **"De-identified Oncology Case Graph"** as the stated future
name, explicitly conditional on real case volume and a real governance
review — put both terms on the slide, one labeled "today," one labeled
"future," so nobody can accuse you of overclaiming.

---

## 6. The complete loop, corrected

```
Patient data arrives
        │
        ▼
  Case Memory (event log, append-only)
        │
        ▼
  Diff Engine  ◄── 100% deterministic, no LLM, no agents
        │  → ChangeSet: new changes + supersessions
        ▼
  Question Generator (templates seeded by ChangeSet, LLM phrases only)
        │  → deduped/suppressed against prior questions
        ▼
  Signal Generators (parallel, deterministic + light LLM per generator,
        │  "OncoSphere" as UI framing — genomics / trials / literature /
        │  pharma dimensions)
        ▼
  Independent Signals, each evidence_class-tagged, never merged into
  false consensus — disagreement rendered, not resolved
        │
        ▼
  Citation Gate (deterministic verification, not an agent)
        │
        ▼
  Structured Case Index lookup (optional, clearly caveated, N-aware)
        │
        ▼
  Clinician Review → Decision (recorded, reasoned)
        │
        ▼
  New event → Case Memory ─────────────┐
        │                              │
        ▼                              │
  (loop continues) ◄────────────────────┘
        │
        ▼ (only if governed export criteria are met — not yet, at hackathon scale)
  De-identified structural summary → Structured Case Index
```

The brief's loop and this one differ in exactly one place: "Agent Debate /
Verification" is replaced with "independent signals, disagreement rendered."
Everything else in the brief's loop survives.

---

## 7. The real moat

Ranked by how hard each is to replicate, and by when it starts existing.

| Candidate moat | Real? | When |
|---|---|---|
| **Case memory + diff engine + supersession history** | **Yes** | Exists from day 1 of real use |
| **Evidence provenance chain (fact → evidence → interpretation → decision, with dates)** | **Yes** | Exists from day 1 |
| **Research-question history / suppression** | Yes, compounding | Grows with use |
| Structured case index (once real cases exist, real N, real governance) | **Yes — the long-term version of "global memory"** | Only after real deployment and real consent infrastructure — 12+ months out, not a hackathon claim |
| The agent architecture itself | **No** | Anyone can wrap the same APIs in agents in a weekend |
| The LLM | **No** | Commodity |
| The evidence graph (CIViC + PubMed) | **No, on its own** | Public data, anyone can load it |

**Say it this way to an investor:** *"Our moat isn't the AI — it's that every
case we run makes the next case at that institution faster to reason about,
because the record of what was already asked and already ruled out doesn't
reset. That compounds. A chatbot session does not."*

---

## 8. Hackathon MVP — revised must/nice/don't

This supersedes the MVP list in the prior audit only where OncoSphere/Global
Memory change it; the case-memory core is identical.

### MUST BUILD
Everything in `IMPLEMENTATION_PLAN.md` §13, unchanged: case store, diff
engine (day 3, non-negotiable), research memory, FastAPI wrapper, citation
gate, three screens, ClinicalTrials.gov loader, two seeded cases.

**Plus, reframed from OncoSphere:** the four parallel signal generators
(genomics/trials/literature/pharma) as typed functions feeding into
Finding Detail — already covered by "wrap existing retrieval," just labeled
in the UI by dimension so the tumor-board framing is visible without being
architecturally real agents.

### NICE TO HAVE
**Structured Case Index** — the deterministic structural-similarity lookup
in §5, over your 2–3 seeded synthetic cases. Cheap (it's a filter + score
over fields you already have), and it demonstrates the third layer honestly
if there's time. Label every result with exactly which fields matched.

### DO NOT BUILD
- Autonomous multi-agent orchestration, agent-to-agent "debate," any
  consensus-resolution mechanism between model calls
- Any claim of cross-case pattern learning, similarity beyond structured
  field overlap, or outcome correlation — you don't have the N
- A generic "de-identification pipeline" for data that doesn't exist yet —
  build the allowlist/export function, don't build fake privacy theater
  around synthetic data
- Federated learning, differential privacy — genuinely out of scope; naming
  them in a hackathon pitch without an implementation is a credibility risk,
  not a strength

---

## 9. The wow moment — and why the brief's version isn't demo-honest

The brief's proposed wow moment is: *"Athena found this pattern because it
exists across multiple previously de-identified cases."* **Don't build to
this.** With two or three synthetic seed cases, "pattern across multiple
cases" is not a pattern, it's an anecdote dressed as one, and a technical
judge who asks "how many cases is that pattern based on" will end the demo's
credibility in one sentence.

**The real wow moment is unchanged from the prior audit — the retraction.**
A Day-0 finding struck through on screen, with a machine-generated reason
("this assumed no known alteration in EGFR; that's no longer true"), driven
by the typed-assumption mechanism in `IMPLEMENTATION_PLAN.md` §3.1. That
moment needs zero agents and zero cross-case data, and it's the one thing in
this entire concept that a stateless chatbot structurally cannot produce.

**If you build the Structured Case Index, its honest wow moment is smaller
and should be presented as smaller:** *"1 structurally similar case in our
index — same variant class, same treatment-exhaustion pattern."* Said
plainly, with the N visible, this is still interesting to a judge, because
it's the first sentence of what the real Global Memory becomes — but it's a
promise about the architecture's future, not a claim about intelligence
today. Frame it exactly that way on the slide: "here's the seam where
cross-case learning will attach, once we have real cases and real
governance" — architecture credit, not capability credit.

---

## 10. One-sentence definitions

1. *(Technical)* "An event-sourced case store with a deterministic diff
   engine over a citation-gated evidence retrieval pipeline."
2. *(Technical)* "State, diff, and provenance for a cancer case — the parts
   a chatbot has no schema for."
3. *(Clinical)* "Athena tells your team exactly what changed since you last
   looked, and what that invalidates."
4. *(Clinical)* "A permanent, structured second brain for a hard case that
   never forgets what you already tried and why it didn't work."
5. *(Investor)* "A longitudinal clinical research record that compounds in
   value with every case run through it."
6. *(Investor)* "We're not selling an AI model. We're selling institutional
   memory for complex cancer cases."
7. *(Hackathon-friendly)* "ChatGPT forgets your case the moment you close
   the tab. Athena doesn't — and it tells you what changed."
8. *(Hackathon-friendly)* "The system that says 'here's what's now wrong
   about what we told you last week, and why.'"
9. *(Extremely simple)* "A memory for cancer cases that gets smarter every
   time something changes."
10. *(Extremely simple)* "Athena remembers your case so your team doesn't
    have to start over every time."

**Strongest: #7.** It states the differentiator against the exact competitor
a judge is silently comparing you to, in one sentence, without jargon, and
it's true today with zero hedging.

---

## 11. Final architecture, mapped to the repo

No changes to the FalkorDB spine, retrieval modules, or structural pipeline
beyond what `IMPLEMENTATION_PLAN.md` already specifies. This section only
adds the OncoSphere-as-generators framing and the Structured Case Index.

```
src/secondlook/
├── case/                    (unchanged from IMPLEMENTATION_PLAN.md)
├── api/                     (unchanged)
├── synthesis/
│   ├── generate.py          (unchanged — one LLM call, ChangeSet-seeded)
│   └── citation_gate.py     (unchanged — THIS is your "evidence verifier")
├── signals/                 ← NEW, replaces the word "agents" with functions
│   ├── genomics.py          wraps tier1/retrieval.py
│   ├── trials.py            wraps tier1/ctgov_loader.py (new)
│   ├── literature.py        wraps tier1/pubmed_loader.py + semantic_retrieval.py
│   ├── pharmacology.py      wraps chembl_enrich.py, dgidb.py
│   └── registry.py          typed dispatch table, NOT an orchestrator with
│                             autonomous routing — the ChangeSet decides
│                             which generators run, deterministically
├── index/                   ← NEW, Structured Case Index (nice-to-have)
│   ├── export.py            allowlisted field export + k-anonymity gate
│   │                        (fails closed at hackathon N)
│   └── similarity.py        deterministic structured-field scoring
└── tier1/ctgov_loader.py    (unchanged from IMPLEMENTATION_PLAN.md)
```

**Explicitly not added:** no agent framework dependency (no LangGraph, no
CrewAI, no AutoGen). `signals/registry.py` is a dict of typed functions and a
dispatch based on `ChangeKind` — this is a deliberate, load-bearing choice,
not a shortcut. Adding an agent framework here would reintroduce exactly the
nondeterminism §3 argues against, for zero added capability at this stage.

**Keep / change / remove / add, summary:**

| | |
|---|---|
| **Keep unchanged** | FalkorDB graph spine, all of Tier 1/2 retrieval and structural code, `covalent.py`, provenance helpers, validation harness |
| **Keep, reframe in docs only** | `ARCHITECTURE.md`'s Stage 7 signal generators — this *is* OncoSphere, correctly designed there already, just not named that |
| **Add** | Everything in `IMPLEMENTATION_PLAN.md` (case/, api/, synthesis/) + `signals/` (thin wrappers, no new logic) + `index/` (nice-to-have) |
| **Do not add** | Any multi-agent orchestration framework or library |
| **Remove/demote** | `tier1_contract.py`/`tier1_adapter.py` (per prior audit — the cross-repo seam is gone) |

---

## 12. Final verdict

**Is this a strong product concept?** The Case Memory layer is a genuinely
strong, defensible concept and it's already correctly scoped in your own
prior planning docs. The other two layers, as literally described in this
brief, would weaken it — OncoSphere by adding architectural risk with no
capability gain, Global Memory by inviting a claim you cannot support at
hackathon N. Redesigned as in §3 and §5, all three become coherent, and the
concept as a whole is strong.

**Is the three-layer architecture coherent?** Only after the redesign. As
originally written, Layer 1 solves a problem the deterministic pipeline
doesn't have, and Layer 3 claims a capability the data doesn't support.
Coherent version: Layer 1 = organized deterministic retrieval, Layer 2 =
the actual product, Layer 3 = an honestly-labeled seam for the future.

**Which part is genuinely novel?** The typed-assumption supersession
mechanism (§3.1 of `IMPLEMENTATION_PLAN.md`) and the structural,
non-blurrable separation of evidence classes (`ARCHITECTURE.md` §5,
already built in `graph.py`). Neither is something a general-purpose
chatbot or a typical medical-RAG wrapper has, because neither has a schema
for "this specific prior conclusion is now false, and here's the exact
predicate that broke."

**Which part is already being done by existing healthcare AI companies?**
Cited literature synthesis (Perplexity-style, OpenEvidence, and others do
this well). Trial matching (multiple existing tools). A tumor-board-style
multi-specialist framing (several startups already pitch exactly this
metaphor). None of the existing players, as far as this audit can determine
from the repo and the brief alone, ship a deterministic diff-and-supersede
mechanism over a persistent structured case — that's the actual white space.

**What would make Athena look like a generic AI wrapper?** Shipping
OncoSphere as literal autonomous debating agents with a consensus score. It
would look like exactly the "multi-agent for the sake of multi-agent"
pattern a technical judge has seen fail in a dozen other hackathon demos
this year, and the consensus number would be the first thing a sharp
question dismantles.

**What would make it look like a genuinely new system?** The struck-through
finding. Nothing else in this document comes close to doing that work.

**What to build for the hackathon:** Case Memory (mandatory), the four
signal generators reframed as OncoSphere's UI dimensions (cheap, mostly
already-written wrappers), the citation gate as your "evidence verifier."
Structured Case Index only if time remains, presented at the N you actually
have.

**What to absolutely not build:** an agent orchestration framework, agent
debate/consensus logic, or any claim — verbal or in the UI — that Athena has
learned a cross-case pattern. You have zero real N. Say so if asked, and
show the architecture that will earn the claim later instead of pretending
to have earned it now.
