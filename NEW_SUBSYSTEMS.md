# Athena — New / Additional Subsystems (Addendum)

Derived from Consensus AI research findings (Desai 2026, Ferber 2025,
Ismayilov 2025, Hoier 2024, Chebrolu 2025, Liu 2026, Tamborero 2022). This
file is strictly additive to `Subsystems.md` (subsystems A–O) — nothing in
that file is modified. Continues the lettering as P–S.

**Screened out, and why — stated up front per the "don't force additions"
instruction:** the Desai 2026 finding (multi-agent tumor board simulation →
high utility + time savings) is **not** turned into a new subsystem. It's
real evidence, but it's evidence for an architecture
(`Subsystems.md` §E / `CONCEPT_EVALUATION.md` §3) that this project already
considered and deliberately rejected, for reasons unrelated to whether it
works — determinism, cost, and consensus-theater risk. Reopening that
decision belongs in a design discussion, not a new subsystem file. It's
addressed directly in `RESEARCH_LESSONS.md` instead.

---

## P. LLM Decision-Quality & Safety Monitoring Harness

**Priority: P0**

### Why this subsystem is needed
Two findings point at the same underlying gap from different angles.
Ferber 2025 shows base LLMs perform poorly at clinical decision-making
without tool grounding (30.3%) and dramatically better with it (87.2%) —
meaning tool-augmentation isn't a nice-to-have, it's the difference between
a system that mostly fails and one that mostly works, and that gap needs to
be *measured* for Athena's specific decision points, not assumed. Liu 2026
shows that tracking guideline concordance and safety violations over time
materially improves outcomes. **Athena currently has no equivalent of
`validation.py`'s pre-committed-criteria discipline for its LLM-touching
subsystems** (E's generator phrasing, F's criteria extraction, I's
synthesis) — that rigor exists for the structural pipeline (subsystem B)
and nowhere else.

### What problem it solves
Without this, subsystems E, F, and I ship on the assumption that
tool-grounded LLM calls are safe and accurate, rather than on measured
evidence — the exact gap the project's own validation discipline exists to
close everywhere else in the codebase.

### Inputs / Outputs
- *In:* every LLM call site's `(prompt, tool_results, output)` triple, tagged
  with `generator_version`/`prompt_template_id` (per
  `CONCEPT_EVALUATION.md` §4)
- *Out:* a per-subsystem accuracy/concordance report against a held-out,
  hand-labeled test set; a running safety-violation log; a pass/fail against
  a pre-committed threshold, in the same shape as `validation/results.md`

### Core functionality
```python
# harness/llm_eval.py
@dataclass(frozen=True)
class EvalCase:
    input: dict                # case/question context
    expected: dict              # hand-labeled correct output shape
    tolerance: dict | None      # for non-exact-match fields

@dataclass(frozen=True)
class EvalResult:
    subsystem: str              # "signals.trials" | "synthesis.generate" | ...
    prompt_template_id: str
    pass_rate: float
    threshold: float             # PRE-COMMITTED before the run, never after
    safety_violations: list[str] # non-empty entries are P0 blockers
    verdict: Literal["PASS", "FAIL", "BLOCKED_BY_SAFETY_VIOLATION"]
```
Tool-grounded vs. ungrounded comparison runs are the specific pattern from
Ferber 2025 worth replicating internally: run each subsystem's prompts both
with and without retrieval/tool access on the same eval set, and report the
delta. If a subsystem shows no meaningful lift from grounding, that's a
signal the retrieval isn't actually being used by the model — worth knowing
before shipping, not after.

**Explicitly not built:** autonomous prompt self-modification. Liu 2026's
gains are worth pursuing through **versioned, human-reviewed prompt
iteration evaluated against this harness**, never through a system that
edits its own prompts unattended — that would violate the determinism
invariant this entire architecture is built around
(`IMPLEMENTATION_PLAN.md` §13, extended in `Subsystems.md` §D).

### Key interfaces / dependencies
- Reads from subsystems E, F, I (every LLM call site)
- Shares its pass/fail reporting shape with subsystem B's existing
  `validation.py`/`run_gold_standard.py` pattern — same team, same
  discipline, different domain
- Safety-violation definitions should be co-owned with subsystem N
  (Governance) and subsystem Q below (guideline concordance is one
  category of safety violation)

### Relevant research
Ferber 2025 (tool-augmented vs. base LLM accuracy gap); Liu 2026 (concordance
and safety-violation tracking over time).

---

## Q. Guideline-Grounded Exhaustion Assessment

**Priority: P0**

### Why this subsystem is needed
`ARCHITECTURE.md` stage 2 ("Exhaustion assessment") and `Concept.md` §11
both already state that surfacing exploratory options to a patient who
hasn't tried standard first-line therapy is dangerous, and call this the
single most important safety guard in the system — but neither document
specifies *how Athena actually determines what the standard-of-care option
is* for a given case. Today that determination has no technical backing at
all. Ismayilov 2025 and Hoier 2024 show that injecting structured guideline
context produces safe, accurate recommendations for standard cases — this
is the concrete mechanism the exhaustion-assessment stage has been missing.

### What problem it solves
Closes the gap between "we said this is our top safety guard" and "we have
no system that actually knows what the guideline recommends." Without it,
subsystem D's exhaustion-assessment stage is a policy statement, not a
working gate.

### Inputs / Outputs
- *In:* `CaseState` (cancer_type, stage, molecular profile, treatment
  history), a structured guideline knowledge base (below)
- *Out:* `ExhaustionAssessment{status: exhausted | not_exhausted | unknown,
  untried_standard_option: GuidelineRecommendation | None, citation}` — feeds
  directly into subsystem D's routing logic, and per `ARCHITECTURE.md`
  stage 2, an untried standard option must surface **first and loudly**

### Core functionality
Structured context injection, not free generation — this is the specific
pattern the research supports, and it's the same discipline already used
elsewhere in this project (deterministic retrieval feeding a constrained LLM
call, never an open-ended one):

```python
def assess_exhaustion(
    case: CaseState,
    guideline_kb: GuidelineKnowledgeBase,
) -> ExhaustionAssessment:
    """Retrieve the guideline recommendation(s) matching case.cancer_type +
    case.stage + case.molecular_profile as STRUCTURED records (not free
    text), compare against case.treatment_history. If a recommended
    standard option has NOT been tried and no documented contraindication
    exists, return not_exhausted with the untried option cited. LLM is used
    only to phrase the explanation, never to decide the match.
    """
```

**Guideline knowledge base — build this carefully, licensing-first:** NCCN
is explicitly excluded project-wide (`docs/data-sources.md`) — restrictive,
paid license, incompatible with `Concept.md` §8's open-source principle.
ESMO/ASCO guideline *summaries* have mixed availability; do not assume
scrapeable full text is licensed for redistribution. **The realistic v1
source is a hand-curated, versioned knowledge base** — same
`config_version`-tracked YAML pattern as `civic_scope.yaml` and subsystem J's
access-pathway files — seeded by a clinician on the team for the specific
cancer types in scope, not an automated scrape of a licensed guideline
document. This is a curation-heavy subsystem, like subsystem J, and should
be staffed accordingly.

### Key interfaces / dependencies
- Feeds subsystem D directly (exhaustion status changes routing/framing)
- Guideline KB loader follows subsystem A's shape-verification and
  provenance conventions
- Validated through subsystem P's harness — guideline-concordance is
  exactly the metric Liu 2026 measured, and it's the right ongoing check
  for this subsystem specifically

### Relevant research
Ismayilov 2025, Hoier 2024 (structured guideline injection → safe, accurate
standard-case recommendations).

---

## R. Automated Case Intake / Document Ingestion Pipeline

**Priority: P1**

### Why this subsystem is needed
`IMPLEMENTATION_PLAN.md` and `patient-schema-mvp.md` currently treat
structured manual entry as the primary intake path, with document extraction
as an unstructured "nice to have." Chebrolu 2025's finding — EHR-integrated
case presentation cuts manual data entry by 75% and prep time by 40% at
scale — is a large enough effect to justify formalizing intake as its own
subsystem rather than leaving it as an afterthought, particularly given
`Concept.md`'s low-resource framing: a district oncologist without support
staff feels a 40% prep-time reduction far more than a well-staffed academic
center would.

### What problem it solves
Manual structured entry of the six P0 fields is a real adoption barrier when
a clinician is already time-constrained. This subsystem turns "attach a
pathology or sequencing report" into structured `CaseEvent`s automatically,
with the clinician confirming rather than typing.

### Inputs / Outputs
- *In:* uploaded documents — pathology reports, sequencing/NGS reports,
  clinical notes (free text or scanned/OCR'd)
- *Out:* proposed `CaseEvent` objects (matching subsystem C's five-type
  taxonomy), each flagged `pending_confirmation` until a clinician approves

### Core functionality
```python
def extract_case_events(
    document: UploadedDocument,
    document_type: Literal["pathology", "sequencing", "clinical_note"],
) -> list[ProposedCaseEvent]:
    """LLM-assisted structured extraction, ALWAYS human-confirmed before
    committing to case/store.py -- per the existing rule that the LLM
    never writes to the case store directly (IMPLEMENTATION_PLAN.md S:5).
    Returns typed events with a confidence flag per field; low-confidence
    fields are highlighted for review, not silently accepted.
    """
```
One extraction model/prompt per `document_type`, versioned
(`generator_version`) and evaluated through subsystem P's harness before
being trusted at any real scale — Chebrolu's reported gains are a reason to
build this, not a reason to skip validating it for Athena's own documents.

### Key interfaces / dependencies
- Writes proposed events only — subsystem C's repository layer remains the
  sole path to committed state, unchanged
- Feeds subsystem M (frontend) a confirmation UI, not a silent auto-commit
- Evaluated by subsystem P (extraction-accuracy eval set, same pattern as
  subsystem F's criteria-extraction harness in `Subsystems.md` §F)

### Relevant research
Chebrolu 2025 (EHR-integrated case presentation — 75% reduction in manual
entry, 40% reduction in prep time at scale).

---

## S. Standardized Molecular Report & Interoperability Export

**Priority: P2**

### Why this subsystem is needed
Every existing output subsystem (M's dashboard, M's brief export) is
human-readable, for one clinician on one case. Tamborero 2022's finding —
molecular profiling portals that standardize NGS interpretation and
reporting *across multi-center networks* — points at a different problem:
machine-readable interoperability, so Athena's structured findings can move
between institutions, feed a hospital's own EHR, or support a referral to
another center, rather than living only inside Athena's own dashboard.

### What problem it solves
`Concept.md` §8.5 deliberately keeps each Athena deployment's data local —
correct for privacy, but it means a case has no standard way to travel with
a patient referred elsewhere, or to be consumed by a receiving institution's
own systems. This is a real gap at the point where the low-resource
framing's actual use case — a district hospital referring a case onward, or
participating in a regional network — becomes relevant.

### Inputs / Outputs
- *In:* a case's derived `CaseState` + active `Finding`s (from subsystem C)
- *Out:* a structured export in an existing interoperability standard —
  **mCODE** (Minimal Common Oncology Data Elements, an HL7 FHIR implementation
  guide purpose-built for oncology) is the right target rather than
  inventing a bespoke schema, since it's open, oncology-specific, and
  already has EHR-vendor adoption to interoperate against

### Core functionality
```python
def export_mcode(case: CaseState, findings: list[Finding]) -> FHIRBundle:
    """Map CaseState fields (cancer_type/histology -> Primary Cancer
    Condition, molecular alterations -> Genomic Variant, treatment_history
    -> Cancer-Related Medication/Procedure) onto mCODE FHIR resources.
    Read-only export -- this subsystem never imports/writes case state
    from an external FHIR source; that's a separate, larger integration
    decision explicitly out of scope here.
    """
```

### Key interfaces / dependencies
- Reads from subsystem C only; does not touch subsystems D–K
- A natural pairing with subsystem L's API layer as an additional export
  endpoint, not a new service
- Should be sequenced **after** the core loop (subsystems C–I) is solid —
  this is a scale/interop concern, not a hackathon-stage or MVP-blocking one

### Relevant research
Tamborero 2022 (standardized NGS interpretation/reporting across
multi-center networks).

---

## Priority summary

| Subsystem | Priority | One-line justification |
|---|---|---|
| P — LLM Eval & Safety Monitoring Harness | **P0** | No current validation discipline for the LLM-touching subsystems; safety-critical |
| Q — Guideline-Grounded Exhaustion Assessment | **P0** | The project's own stated top safety guard currently has no implementation |
| R — Automated Case Intake Pipeline | P1 | Large, evidence-backed adoption-friction reduction; not safety-blocking |
| S — Standardized Molecular Report Export | P2 | Real value at scale/multi-center; not needed for the core loop or a hackathon demo |
