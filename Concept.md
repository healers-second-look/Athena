# Athena — Concept
## Living Cancer Intelligence for Low-Resource Oncology

This document folds the OncoSphere / Case Memory / Global Memory / Evidence
Memory proposal into one coherent concept, incorporates the trial-intelligence
and emerging-evidence ideas from the referenced paper, and reframes all of it
around a specific, underserved user. It supersedes nothing in
`athena-strategy-audit.md`, `IMPLEMENTATION_PLAN.md`, or `CONCEPT_EVALUATION.md`
— it is the version of the concept that sits on top of those, written as the
document a new contributor or funder reads first.

---

## 1. The problem, stated precisely

A molecular tumor board — a room of sub-specialists who jointly reason about a
hard case's genomics, pathology, trial options, and access routes — exists at
a few dozen major cancer centers worldwide. Most oncologists treating most
cancer patients on earth do not have one down the hall. When a case exhausts
standard options, the actual bottleneck is rarely a missing drug. It is
missing *access to the reasoning process* that a specialist team would run:
knowing which second-line literature exists, which trial a patient might
plausibly qualify for, and — the piece almost nobody outside a major center's
access office knows — which regulatory pathway (compassionate use, expanded
access, named-patient import) could get an unapproved therapy to this patient
legally, in this country, this month.

**This is an expertise-distribution problem, not a data problem.** The
evidence largely already exists in open sources — CIViC, PubMed,
ClinicalTrials.gov. What doesn't exist is a system that holds a specific
patient's case in memory long enough to reason over it the way a tumor board
would, and that does so cheaply enough and locally enough to run in a public
hospital in a district that will never have its own MTB.

**Who this is for, concretely:** a general oncologist at a district or
tier-2/3 hospital — in India, or any comparable low-resource setting —
managing a rare or treatment-exhausted case alone, without a subspecialist
colleague to consult and without the budget or connectivity for a
per-case cloud-AI subscription priced for a US academic center.

---

## 2. Product definition

> **Athena is a self-hostable, open-source research memory for a hard cancer
> case. It holds the case's full history, tells the clinician exactly what
> changed and what that invalidates each time new data arrives, and matches
> the case against open trial and access-pathway registries a specialist team
> would otherwise have to know by heart — all running on infrastructure a
> resource-constrained institution can actually afford to operate.**

Three things distinguish this from "a medical chatbot," and all three follow
directly from the problem statement above, not from a wish to sound
differentiated:

1. **It remembers the case**, so a district oncologist gets tumor-board-grade
   continuity without a tumor board.
2. **It knows access pathways**, which is the single highest-value, most
   under-systematized piece of specialist knowledge in this whole problem —
   see §6.
3. **It is free to run**, architecturally — open evidence sources only, no
   proprietary data licenses, a deployment footprint sized for one server, not
   a cloud budget. See §8.

---

## 3. The three memories — finalized

The prior proposals converge on three memories plus a reasoning layer on top.
This is the version to build, with one simplification: **access-pathway
knowledge is not a fourth memory — it's a specialized region of Evidence
Memory**, because it's the same kind of object (a sourced, citable fact about
the world) as a CIViC evidence item, just from a regulatory instrument
instead of a paper.

```
                              ATHENA
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
     CASE MEMORY          EVIDENCE MEMORY        STRUCTURED CASE
   "this patient"      "what the open world      INDEX (deferred)
                         currently knows —       "what we've seen
                        papers, trials, access     across cases run
                             pathways"              through THIS
                                                     deployment"
          │                     │                     │
          └──────────┬──────────┴──────────┬──────────┘
                      ▼                     ▼
            DEPENDENCY-TRACKED        SIGNAL GENERATORS
             DIFF ENGINE         (genomics/trials/lit/pharma —
        (bidirectional — see §5)   deterministic, "OncoSphere"
                      │              UI framing, not agents)
                      ▼                     │
              CITATION GATE ◄───────────────┘
                      │
              CLINICIAN REVIEW → DECISION (recorded)
                      │
                      ▼
              back into Case Memory (loop closes)
```

### Case Memory
**What do we know about this patient, and when did we learn it?**
Event-sourced, append-only, fully specified in `IMPLEMENTATION_PLAN.md` §2.
No changes needed here — it is already the correct design.

### Evidence Memory
**What does the open world currently know, and is it still current?**
This *is* the existing `tier1/` FalkorDB graph (CIViC, PubMed) — already
built — extended in two ways this concept requires:
- **Continuously updated**, not loaded once (§7 below)
- **Includes access pathways** as a first-class node type, sourced from
  regulatory instruments, not just papers and trials (§6)

### Structured Case Index
**What have we seen across cases run through this specific deployment?**
Deliberately the smallest, slowest-growing memory, exactly as scoped in
`CONCEPT_EVALUATION.md` §5. It is *not* a global cross-institution memory at
launch — each self-hosted deployment accumulates its own index, locally,
which is also the correct privacy posture for a system that promises
institutions their patient data doesn't leave the building.

---

## 4. Signal generators, not agents

Restated from `CONCEPT_EVALUATION.md` §3 because it is load-bearing here too:
the "OncoSphere" specialist framing (genomics / trials / literature /
pharmacology / access) is a **UI organizing principle over deterministic
retrieval functions**, not an autonomous multi-agent system. This matters
doubly in a low-resource framing — every additional autonomous LLM reasoning
loop is marginal cost per case that a resource-constrained deployment cannot
absorb. Five agents "discussing" a case can mean five to fifteen LLM calls;
five typed retrieval functions plus one synthesis call is one or two.

---

## 5. The diff engine, generalized — the actual product

`IMPLEMENTATION_PLAN.md` §3 designs the diff engine over *patient* state
change. The paper's "47 active cases affected" idea and this concept's
Evidence Memory both point at the same underlying mechanism from the other
direction: **a `Finding`'s assumptions can be broken by a change in Evidence
Memory just as easily as a change in Case Memory.**

This is one mechanism, not two:

```python
# Every Finding already carries typed Assumptions (IMPLEMENTATION_PLAN.md §3.1)
# Extend the Assumption protocol to depend on EITHER state:

class Assumption(Protocol):
    def holds(self, case: CaseState, evidence: EvidenceSnapshot) -> bool: ...
    def describe(self) -> str: ...

# A patient-state assumption (already designed):
NoAlterationIn(gene="EGFR")               # broken by new sequencing

# An evidence-state assumption (new — the reverse direction):
NoStrongerEvidenceThan(civic_id="EID123") # broken by a new CIViC/PubMed item
                                           # for the same gene+variant+drug
                                           # at a higher evidence level
```

When a case's finding is created, it registers **which evidence items it
depends on**, not just which patient facts. When Evidence Memory ingests
something new, the system doesn't re-run every case — it looks up which
registered assumptions reference the changed gene/variant/drug (an indexed
lookup, not a scan) and re-evaluates only those. This is what makes *"this
new paper affects 47 active cases"* a real, deterministic, cheap query
instead of a re-analysis of every case in the institution — which matters
enormously for cost in a low-resource deployment.

**This closes the loop the paper describes** — clinical trials and emerging
treatments are fragmented and hard to discover proactively — with the same
mechanism already built for patient-side change detection, not a second
system.

---

## 6. Access-pathway intelligence — the highest-value, lowest-cost component

Already identified in `ARCHITECTURE.md` §4 stage 6 as the highest-value
component in the whole system; this concept promotes it because the
low-resource framing makes clear *why*: **the therapy that mattered most in
the case that inspired this project was reachable through a regulatory route
that existed and worked — and the binding constraint was that nobody knew the
route existed.** That is exactly the kind of tacit specialist knowledge a
district oncologist has no way to access, and it is a curation problem, not a
research problem — cheap to build relative to its value.

Modeled as `AccessPathway` nodes in Evidence Memory, each citing its
regulatory instrument: on-label, off-label, recruiting trial (with an
eligibility pre-screen from §"Trial Intelligence" below), expanded access /
compassionate use (**US FDA Form 3926**; **India CDSCO compassionate-use and
named-patient import**), named-patient import, manufacturer access programme.
**India-first, and LMIC-first generally** — this is precisely the
`config_version`-tracked, YAML-scoped pattern already used for
`civic_scope.yaml`; the same discipline extends naturally to access-pathway
coverage by country.

---

## 7. Continuously updated Evidence Memory, and the trial-intelligence layer

Two extensions to the existing, working `tier1/` graph, both inspired by the
paper and both additive:

**Continuous ingestion.** CIViC, PubMed, and ClinicalTrials.gov are polled on
a schedule (not real-time streaming — unnecessary cost for a resource-
constrained deployment) and diffed against the existing graph using the same
provenance discipline already in `graph_schema.py`
(`with_provenance`/`with_enrichment_provenance`). New or changed items trigger
the reverse-diff in §5.

**Trial eligibility matching, not trial search.** Rather than returning a
list of trials matching a gene, the system matches the case's structured
state against each trial's parsed inclusion/exclusion criteria and buckets
results:

```
17 potentially relevant trials
 3  highly compatible        — all structured criteria satisfied
 8  requires verification    — criteria reference data not in the case
                               (e.g. a lab value not yet recorded)
 6  probably incompatible    — a structured criterion is directly violated
                               (e.g. prior-therapy exclusion)
```

Each bucket states *why*, per trial, citing the specific criterion. This is
squarely a curated NLP-extraction-then-match problem, not a generative one —
see `Subsystems.md` §F for the concrete build.

---

## 8. Open source and low-resource deployment — design principles

These constraints apply across every subsystem in `Subsystems.md`, stated
once here as the standard each is held to:

1. **No licensed data sources.** CIViC, PubMed, ClinicalTrials.gov, CTRI —
   open or free. NCCN, OncoKB, DrugBank, MdrDB — explicitly excluded from any
   shipped path, per `docs/data-sources.md` and `ARCHITECTURE.md` §6, and
   doubly so here: a licensing cost that's a rounding error for a US hospital
   system is often prohibitive for the institutions this is built for.
2. **One or two LLM calls per research question, never per agent.** Directly
   bounds marginal per-case cost. Stated as a hard design rule, not an
   optimization to revisit later.
3. **Self-hostable on commodity infrastructure.** FalkorDB (open source,
   Redis-based — lighter than a Neo4j Enterprise deployment) + Postgres, both
   run comfortably on a single mid-spec server. No managed-cloud-only
   dependency in the required path.
4. **Model-agnostic LLM layer.** The synthesis and question-phrasing calls
   (`IMPLEMENTATION_PLAN.md` §6–7) are the only LLM-dependent subsystem.
   Architect them behind one interface so a deployment can point at a hosted
   API *or* a self-hosted open-weight model, trading latency/quality for
   near-zero marginal cost. **State plainly: which open-weight models are
   adequate for citation-constrained synthesis is a real open question the
   team must validate, not an assumption to ship on.**
5. **Deployments don't share patient data by default.** The Structured Case
   Index is per-deployment, not centralized — see §3. This is a privacy
   requirement and a low-resource-adoption requirement at once: an
   institution asked to send patient data to a shared cloud service will
   often say no, for good reason.
6. **Regional configurability, not global-first coverage.** `civic_scope.yaml`
   already demonstrates the pattern — versioned, auditable, disease-scoped
   config. A deployment for a region with a high burden of specific cancers
   configures its scope accordingly rather than the project attempting global
   coverage before any single deployment is solid.

---

## 9. What "state of the art" honestly means here

Not: out-predicting binding-affinity tools — that path was tried, validated
against a pre-committed threshold, and failed (`validation/results.md`); it
stays out of the product per `ARCHITECTURE.md` §6.

**The credible SOTA claim: the most complete, open-source, self-hostable,
citation-enforced, case-memory-aware oncology research system designed for
institutions without their own molecular tumor board.** This is achievable
because it's a largely uncontested niche — existing well-funded competitors
build for the institutions that already have specialist access and can afford
per-seat cloud pricing; almost nobody is building the deterministic,
cheap-to-run, self-hostable version for the setting where the need is
greatest. Being first-and-rigorous in an underserved niche is a real SOTA
claim; being more accurate than FDA-track predictive models is not one this
project should make.

---

## 10. What Athena explicitly is not

- Not a diagnostic tool, not a treatment recommender — every output is
  evidence and hypothesis for a clinician to weigh, per the evidence-class
  discipline throughout `ARCHITECTURE.md` §5.
- Not a binding-affinity or drug-response predictor — that claim failed
  validation and is permanently out.
- Not a multi-agent system, despite the "tumor board" framing — see §4.
- Not a cross-institution learning system at launch — the Structured Case
  Index is local to each deployment.
- Not free of the LLM-cost-per-case question — it minimizes it structurally,
  but does not eliminate it, and that tradeoff must be validated against real
  deployment budgets, not assumed away.

---

## 11. Success looks like

Not "more accurate than a specialist" — a lower, more honest, and more
achievable bar, appropriate to what a memory-and-retrieval system can
actually promise:

- A district oncologist reaches a documented, cited research direction on a
  hard case **without a specialist referral**, in minutes instead of the
  weeks a real MTB review often takes.
- When new data arrives, the clinician sees **exactly what changed**, not a
  fresh case dump to re-read from scratch.
- An access pathway the clinician did not know existed gets surfaced, cited,
  at least once per meaningful deployment period — this is the single metric
  worth tracking above all others, because it's the clearest evidence the
  system closed a real expertise gap rather than just summarizing PubMed
  faster.
- The deployment runs, self-hosted, within infrastructure the institution
  already has or can affordably add — no per-case cloud-AI line item that
  scales against patient volume in a way a public hospital budget can't
  absorb.
