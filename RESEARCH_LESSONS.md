# Athena — Lessons From Existing Research

Source: Consensus AI findings (Desai 2026, Ferber 2025, Ismayilov 2025,
Hoier 2024, Chebrolu 2025, Liu 2026, Tamborero 2022). This is not a paper
summary — every point below is stated as **what the research did → what we
learn → how it changes Athena**, and nothing here duplicates
`Subsystems.md` or `NEW_SUBSYSTEMS.md`; it's the reasoning that produced
those two new subsystems (P, Q) and the reasoning that explicitly did *not*
produce a third (the multi-agent question).

---

## What has already been proven to work

**Tool-grounded LLM calls, not free generation.**
→ Ferber 2025 found base LLMs scoring 30.3% on clinical decision-making
tasks and tool-augmented LLMs scoring 87.2% on the same tasks.
→ *What we learn:* the gap between grounded and ungrounded LLM output isn't
marginal, it's the difference between a system that mostly fails and one
that mostly works. This isn't new information for Athena's core design —
every LLM call site in `IMPLEMENTATION_PLAN.md` is already deliberately
retrieval-constrained — but it's the first external evidence that this
specific design choice, not just "using an LLM," is what makes the
difference.
→ *How it changes Athena:* it justifies building subsystem P (evaluation
harness) to actually *measure* the grounded-vs-ungrounded gap for Athena's
own prompts rather than assuming the same 30→87 point improvement transfers.
Assumption is not evidence; measure it.

**Structured guideline context injection for standard cases.**
→ Ismayilov 2025 and Hoier 2024 found that injecting structured guideline
context produces safe, accurate recommendations for standard-of-care cases.
→ *What we learn:* the pattern that works is *structured* injection — a
retrieved, typed guideline record fed into a constrained prompt — not
open-ended "here's the case, what does the guideline say" generation.
→ *How it changes Athena:* this is the concrete mechanism behind subsystem
Q, and it closes a real gap — `ARCHITECTURE.md` names the standard-of-care
guard as the system's most important safety check but never specified how
Athena would actually know what standard-of-care *is* for a case.

**EHR/document-integrated intake reduces real adoption friction.**
→ Chebrolu 2025 found 75% less manual data entry and 40% less prep time at
scale with EHR-integrated case presentation.
→ *What we learn:* intake friction is not a minor UX concern — it's large
enough to be a headline finding on its own, which reframes "manual form
entry" from an acceptable MVP shortcut to a real barrier worth solving early,
especially for the time-constrained clinicians this project targets.
→ *How it changes Athena:* produced subsystem R. Manual entry stays as the
fallback path (and the correct hackathon-stage default — it's simpler and
has no extraction-accuracy risk), but document ingestion should move up the
roadmap sooner than "someday" once the core loop is proven.

**Standardization improves consistency across sites.**
→ Tamborero 2022 found that molecular profiling portals standardizing NGS
interpretation and reporting improved consistency across multi-center
networks.
→ *What we learn:* the value here is specifically *interoperability*, not
just "have a good UI" — consistency comes from a shared structured format
multiple institutions can read, not from any one institution's dashboard
being well-designed.
→ *How it changes Athena:* produced subsystem S, deliberately scoped as an
export concern (mCODE/FHIR) layered on top of the existing local case store,
not a reason to centralize data across deployments — that would conflict
with `Concept.md` §8.5's privacy posture, and standardization doesn't
require centralization.

---

## What has not worked / common failure modes

**Ungrounded LLM clinical reasoning fails most of the time, not
occasionally.**
Ferber 2025's 30.3% baseline is itself the failure-mode data point — an LLM
reasoning about a clinical case without tool access gets it right well under
a third of the time. This is direct, external confirmation of why this
project's citation-gate discipline (`IMPLEMENTATION_PLAN.md` §7) and
"no evidence, no claim" rule aren't excess caution — they're addressing a
failure mode with a measured, large magnitude.

**This batch of findings skews toward "what works" — worth naming the
honest limit of what it tells us.** None of the six findings report a
negative result or a specific failure mode in the way, for example,
`validation/results.md` reports the structural-prediction pipeline's own
2/9 and 7/8 failures. Don't read the absence of reported failure modes here
as evidence that these approaches have none — it's more likely a
publication-bias artifact (positive results get published and indexed more
readily) than evidence of a solved problem. Treat every "what works" finding
above as a hypothesis to validate against Athena's own eval harness
(subsystem P), not a result to inherit uncritically.

---

## Architectural patterns we should adopt

1. **Structured context injection over free-form prompting**, everywhere an
   LLM touches clinical reasoning — this is now the pattern with the
   strongest direct evidentiary support (Ferber, Ismayilov, Hoier) and it's
   already Athena's design default; treat any future LLM-touching subsystem
   proposal that doesn't follow this pattern as a red flag.
2. **Pre-committed, measured evaluation of LLM subsystems**, generalizing
   `validation.py`'s existing discipline for the structural pipeline to
   every LLM call site (subsystem P). The project already knows how to do
   this rigorously in one domain; the gap was applying it everywhere the LLM
   touches output.
3. **Confirmation-gated automated intake** (subsystem R) — extract, don't
   auto-commit. This is consistent with, not a departure from, the existing
   rule that the LLM never writes to the case store directly.
4. **Interoperability as export, not centralization** (subsystem S) —
   standardize the *format* data leaves a deployment in, without requiring
   data to leave the deployment by default.

---

## Approaches we should avoid

**Autonomous self-modifying prompts, even though the outcome data is
positive.**
Liu 2026 reports real, positive results from self-evolving prompt systems —
improved guideline concordance, fewer safety violations over time. The
outcome is good; the mechanism is the problem. A system that edits its own
prompts unattended is fundamentally incompatible with this project's
determinism invariant (`IMPLEMENTATION_PLAN.md` §13: *"the diff engine is
deterministic and never calls an LLM… if a change set differs between two
runs on identical input, that is a P0 bug"*) extended to every subsystem
that touches clinical output — a system whose own behavior silently drifts
run to run is exactly as undesirable as a diff engine that does. **The right
way to capture Liu 2026's actual benefit is subsystem P**: version every
prompt change explicitly, evaluate it against a held-out set before and
after, require a human to approve the change. Same destination — improving
concordance over time — reached deterministically and auditably instead of
autonomously.

**Adopting multi-agent tumor-board framing on the strength of Desai 2026
alone.**
Desai 2026 reports high utility ratings and time savings from multi-agent
tumor board simulation. This is a real, positive finding, and it's worth
taking seriously rather than dismissing — but it doesn't isolate *why* the
simulation performed well. High utility ratings and time savings are
equally consistent with two different explanations: (a) autonomous
multi-agent reasoning is genuinely doing something a single pipeline can't,
or (b) users respond well to output *organized by specialist perspective*,
regardless of whether specialist "agents" produced it or a single
deterministic pipeline did. `CONCEPT_EVALUATION.md` §3 already made the
architectural bet that (b) is doing most of the work, for reasons
independent of this finding — nondeterminism cost, agent-consensus theater,
and per-case LLM-call cost, which matters doubly under `Concept.md` §8's
low-resource cost constraints. **Decision: keep the deterministic Signal
Generator Layer (`Subsystems.md` §E), keep the specialist-dimension UI
framing that Desai's finding suggests is genuinely valuable, and do not
adopt agent autonomy.** If a future evaluation (subsystem P, applied to this
specific question) shows the deterministic version underperforms an
agentic one on a real utility metric, that's grounds to revisit — but the
decision shouldn't flip on the strength of one external paper whose
mechanism isn't isolated from a confound this project already has a
principled reason to avoid.

---

## Important technical decisions

1. **Guideline knowledge base sourcing is licensing-first, not
   scraping-first.** NCCN is out (restrictive license, already excluded
   project-wide). ESMO/ASCO full guideline text availability is mixed and
   unverified for redistribution. The realistic decision, stated plainly in
   subsystem Q: hand-curate a versioned guideline knowledge base for the
   specific cancer types in scope, the same pattern already used for
   `civic_scope.yaml` and the access-pathway registry — not an automated
   scrape of a document whose license status is unclear.
2. **Grounding happens before generation, verification happens after.**
   Ferber's evidence is about grounding *going in* to a call; the existing
   citation gate (`IMPLEMENTATION_PLAN.md` §7) verifies *coming out*. Keep
   both — one doesn't substitute for the other, and neither of these two new
   subsystems changes that boundary.
3. **Every prompt/extraction-model version gets a stable ID, tracked
   through subsystem P's eval harness**, before it's trusted for a new
   subsystem (R's document extraction, Q's guideline matching, or an
   existing one). This was implied but not enforced anywhere before this
   research pass; subsystem P makes it a checked requirement.

---

## Important clinical/safety considerations

1. **The exhaustion-assessment safety gate needed real technical backing,
   and didn't have it.** This is the single most consequential finding from
   this research pass. `ARCHITECTURE.md` and `Concept.md` both call the
   standard-of-care guard the system's most important safety mechanism, and
   until subsystem Q, nothing in the fifteen existing subsystems actually
   determined what "standard of care" meant for a given case. Treat closing
   this gap as more urgent than any of the other three new subsystems.
2. **Safety-violation tracking should be continuous and audited, not
   self-correcting.** Liu 2026's positive concordance/safety results are
   worth pursuing through subsystem P's monitoring function specifically —
   log every violation, review it, version the fix — never through a
   mechanism that adjusts its own behavior in response to violations without
   a human in the loop.
3. **Standardized reporting has a safety dimension, not just an
   interoperability one.** Tamborero's multi-center consistency finding
   implies that non-standardized reporting is itself a source of
   interpretation error at the point a case moves between clinicians or
   institutions — worth stating explicitly as a reason subsystem S matters
   beyond convenience, for whenever it gets prioritized.

---

## Gaps Athena can potentially address

None of these six findings describe a system that does what
`IMPLEMENTATION_PLAN.md` §3 and `Concept.md` §5 make the actual core of
Athena:

- **Persistent, dependency-tracked invalidation of prior conclusions.** Every
  finding here is about a single consultation's quality (better tool use,
  better guideline grounding, faster intake, more standardized output) — none
  addresses a system that remembers a specific case over time and knows
  which of its own prior conclusions a new piece of data breaks. This
  remains the differentiated claim in the whole project, and this research
  pass didn't surface a competing or prior approach to it.
- **Bidirectional evidence-change alerting** (subsystem G / `Concept.md` §5's
  reverse-diff) — nothing here addresses proactively notifying an existing
  case when new external evidence affects it; every finding is about
  improving a single forward analysis.
- **Low-resource, access-pathway-first framing.** None of these six papers
  address the specific problem `Concept.md` §1 centers — an oncologist
  without institutional specialist access. Chebrolu's efficiency gains and
  Tamborero's standardization both help adoption in such a setting
  indirectly, but the access-pathway registry (`Subsystems.md` §J) remains
  something this research pass found no precedent for, which is worth
  reading as confirmation it's genuine white space rather than a gap in this
  particular literature search.
