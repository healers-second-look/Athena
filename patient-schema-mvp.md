# Athena — Minimum Viable Patient Representation

Written against what Athena actually is today (per the repo): Tier 1 queries a
CIViC-backed graph keyed on `gene` + `hgvs_p` (+ optional `disease`), Tier 2
runs structural analysis keyed on `gene` + `mutation`. Neither tier currently
consumes treatment history, clinical question, performance status, or
anything longitudinal — that machinery doesn't exist yet. This document
designs the **product-level MVP schema**, which is necessarily broader than
what the code strictly requires today, and says explicitly where the two
diverge, so the gap is a known design decision and not a surprise later.

---

## 1. The true non-negotiables (P0) — six, not twenty-five

1. **Cancer type** (primary site + histology)
2. **Stage / extent of disease** (localized vs. metastatic, + met sites if any)
3. **Molecular profile** — the alteration(s) found, or an explicit "not yet
   tested"
4. **Treatment history** — what's been tried and what happened to it (line,
   drug, outcome — not full dose/date granularity)
5. **Current clinical question** — what the doctor actually wants answered
6. **Age** (or at minimum a pediatric/adult bucket)

Everything else — performance status, organ function, full genomic panel
detail, imaging, family history — makes Athena's output *better*, but Athena
can still produce a defensible, citable research direction without it, and a
physician still reviews and filters before anything reaches a patient. That's
the line: **P0 = the query literally cannot be formed or is meaningless
without it.** Not "P0 = would help."

---

## 2. Why each P0 parameter is essential

### Cancer type (primary site + histology)
**What it represents:** the disease identity — where the tumor arose and what
kind of tissue it resembles.
**Why Athena needs it:** it's the primary filter on every downstream source —
CIViC evidence items, trial eligibility criteria, and guideline applicability
are all disease-scoped. Athena's own Tier 1 activation logic (`strong_hit` /
`weak_hit` / `no_hit`) is disease-conditioned.
**What breaks without it:** a gene/mutation query with no disease context
returns evidence from unrelated cancers — a BRAF V600E hit in melanoma
literature is not directly transferable to a BRAF V600E colorectal case
(different response rates, different approved lines).
**Loop stages depending on it:** literature/trial retrieval, evidence
filtering, guideline applicability.

### Stage / extent of disease
**What it represents:** whether the disease is localized, locally advanced,
or metastatic, and where.
**Why Athena needs it:** most trials and expanded-access pathways are
explicitly gated on stage ("metastatic or unresectable" is a near-universal
eligibility clause). It also determines whether curative-intent guidelines
even apply — a Stage I and a Stage IV case of the same cancer type are
different research problems.
**What breaks without it:** Athena could surface a trial or guideline the
patient is categorically ineligible for, which is worse than surfacing
nothing — it wastes clinical time and erodes trust in the tool.
**Loop stages depending on it:** trial matching, evidence filtering, clinical
context framing.

### Molecular profile (known alterations, or explicit "not yet tested")
**What it represents:** the actionable biological finding(s) — the thing a
therapy would actually target.
**Why Athena needs it:** this is the literal join key into both tiers today
— `gene` + `mutation` is what `run_tier2()` and
`Tier1RetrievalPolicy.decide()` require to run at all. It's not just
important, it's the mechanical entry point.
**What breaks without it:** nothing runs. There is no query to form. This is
the one parameter where "Athena cannot work" is not a figure of speech.
**Loop stages depending on it:** everything — retrieval, structural
plausibility, hypothesis generation.

### Treatment history (line, drug, outcome)
**What it represents:** what has already been tried and how the disease
responded.
**Why Athena needs it:** this is what makes a case an *R&D* case rather than
a first-line lookup. Athena's whole trigger condition, per the founder-mode
framing already in the repo, is "standard of care exhausted." Without
knowing what failed, Athena has no way to know it should be looking beyond
guideline-first-line answers, and risks re-surfacing a drug the patient
already progressed on.
**What breaks without it:** duplicate or clinically inappropriate suggestions
— recommending a drug the patient was already intolerant to or already
progressed on is a credibility-destroying failure mode, not a minor
inefficiency.
**Loop stages depending on it:** resistance/response analysis, hypothesis
generation, "what's left to try" framing.

### Current clinical question
**What it represents:** the specific thing the doctor wants researched right
now.
**Why Athena needs it:** without a target, "search everything" produces
noise, not a hypothesis. A structured graph can traverse in many directions;
the clinical question is what tells Athena which traversal is the useful
one — "is there a targeted option for this fusion" is a different query
shape than "why did this patient progress on osimertinib."
**What breaks without it:** Athena degenerates into a generic literature dump
— technically correct, practically unusable, and the opposite of the
"decisive, citable" system the repo's own architecture rule demands.
**Loop stages depending on it:** output framing, synthesis, hypothesis
prioritization.

### Age (or pediatric/adult bucket)
**What it represents:** which regulatory, guideline, and trial universe
applies.
**Why Athena needs it:** pediatric and adult oncology are close to two
different fields — different guideline bodies, different trial networks,
different drug approval status by age. This isn't a minor eligibility filter
like weight-based dosing; it changes which *literature and trial database* is
even relevant.
**What breaks without it:** Athena could surface an adult-only trial for a
pediatric case (or vice versa) as if it were a live option, which is a
category error, not a fine-tuning miss.
**Loop stages depending on it:** trial/literature retrieval scope, guideline
applicability.

---

## 3. Full classification

| Parameter | Tier | Why |
|---|---|---|
| Cancer type / primary site / histology | **P0** | Query anchor |
| Stage / extent / metastatic sites | **P0** | Eligibility & context gate |
| Molecular profile (alterations found) | **P0** | Literal join key into Tier 1/2 |
| Treatment history (drug, line, outcome) | **P0** | Defines the R&D trigger condition |
| Current clinical question | **P0** | Output target |
| Age / pediatric-adult bucket | **P0** | Determines applicable universe |
| Performance status (ECOG) | **P1** | Refines trial eligibility |
| Organ function / relevant labs (renal, hepatic) | **P1** | Refines trial eligibility |
| Comorbidities / contraindications | **P1** | Refines safety filtering |
| Extended biomarkers (TMB, MSI, PD-L1, VAF, co-mutations) | **P1** | Sharper hypothesis generation |
| Imaging summary / progression pattern | **P1** | Dynamic-state accuracy |
| Diagnosis date / time since diagnosis | **P1** | Context, trial recency matching |
| Molecular data recency (when tested) | **P1** | Tells Athena if data may be stale |
| Prior specialist opinions / hypotheses considered | **P1** | Avoids redundant research |
| Decisions already made | **P1** | Avoids redundant research |
| Family history | **P2** | Only relevant for germline-predisposition subset |
| Geographic/location | **P2** | Only matters for trial-site/access-pathway layer |
| Full medication list (non-cancer-relevant) | **P2** | Only interaction-relevant meds matter |
| Full raw imaging (DICOM) | **P2** | No imaging-analysis pipeline exists |
| Detailed dosing/date granularity per regimen | **P2** | Refines but doesn't change retrieval |
| Sex | **P2** | Relevant mainly for reproductive-tract cancers |
| Continuous/wearable biomarker monitoring | **P3** | Not an MVP capability |
| Expression/single-cell data integration | **P3** | Explicitly out of scope today (`founder-mode-use-case.md` §1) |
| Multi-omics longitudinal tracking | **P3** | Future |
| Automated EHR ingestion | **P3** | Future |

---

## 4. Minimum viable schema

```
Patient
├── Identity                          [mostly static]
│   ├── age (or pediatric/adult bucket)     — P0
│   └── sex                                  — P2
├── Diagnosis                          [static — identity of the cancer]
│   ├── cancer_type / primary_site          — P0
│   ├── histology                            — P0
│   └── diagnosis_date                       — P1
├── Disease State                      [dynamic — re-evaluated each loop entry]
│   ├── stage / extent                      — P0
│   ├── metastatic_sites                    — P0 (if metastatic)
│   ├── progression_status                  — P1
│   └── imaging_summary                     — P1
├── Molecular Profile                  [append-only, semi-dynamic]
│   ├── known_alterations: [{gene, variant, source, date_tested}]  — P0
│   └── extended_biomarkers: {TMB, MSI, PD-L1, ...}                — P1
├── Treatment History                  [append-only log, dynamic]
│   └── entries: [{regimen, line, outcome, reason_stopped}]        — P0
├── Patient Condition                  [dynamic]
│   ├── performance_status                  — P1
│   ├── organ_function_flags                — P1
│   └── contraindications                   — P1
└── Research Context                   [dynamic — the actual loop driver]
    ├── current_clinical_question           — P0
    ├── prior_hypotheses_considered          — P1
    └── decisions_already_made               — P1
```

The user's proposed structure was close; the one substantive change is
splitting **Disease State** out as its own dynamic section rather than
folding it into Diagnosis — stage/progression change over the case's life,
histology essentially never does, and the loop needs to treat them
differently (see §5).

---

## 5. Static vs. dynamic, and loop-trigger events

**Static** (identity of the cancer — rarely revised):
cancer_type, primary_site, histology, age at diagnosis, initial diagnosis
date, germline findings (if tested once, don't re-collect).

**Dynamic** (should be re-evaluated, and can trigger the loop):
new imaging (progression, new lesion, response), new biopsy/genomic result,
a biomarker value crossing a threshold, a treatment line starting/stopping,
a new adverse event, a new clinical question from the doctor.

**Events that should trigger Athena to re-enter the R&D loop:**
- A new molecular/genomic result is added
- Imaging shows progression or a new lesion
- A treatment line changes (started, stopped, or switched for intolerance)
- A biomarker crosses a clinically meaningful threshold
- The doctor poses a new clinical question explicitly
- (future, P3) new expression/pathway data becomes available — this is the
  actual mechanism that found FAP in the Sijbrandij case, and it's the one
  the repo's own founder-mode doc flags as the single biggest capability gap
  relative to that use case. Worth naming here so it's a known future trigger,
  not a surprise when someone asks "does Athena do what Sid's team did."

---

## 6. Minimum viable case — concrete example

> 14-year-old patient (pediatric)
> Infantile fibrosarcoma, primary site: soft tissue, thigh
> Locally advanced, no distant metastases
> Molecular profile: ETV6::NTRK3 fusion (confirmed via RNA-seq, tested 2 months ago)
> Treatment history: Line 1 — VAC chemotherapy regimen — stopped due to progression
> Current clinical question: "Is there a targeted option given the NTRK3 fusion, and any trial given progression on standard chemo?"

**With this information Athena can begin the R&D loop because:** cancer type
+ stage give disease context; the NTRK3 fusion is a real Tier 1 query
(`gene=NTRK3`, fusion variant, `disease=infantile fibrosarcoma`) that can
return a `strong_hit`/`weak_hit` against the CIViC graph; the treatment
history establishes this is genuinely an R&D case (first-line chemo already
failed, not a first-consult question); and the clinical question gives
Athena a concrete output target — "targeted therapy + trial options" — rather
than an open-ended evidence dump. Every one of the six P0 fields is doing
distinct work in that query; remove any one and either the query can't run
(molecular profile, cancer type) or the output becomes unsafe/unusable
(treatment history, clinical question, stage, age).

---

## 7. What should explicitly NOT be mandatory

- **Every lab result** — only the labs that gate a specific trial or drug's
  eligibility matter, and only once that trial/drug is actually in
  consideration. Front-loading all labs adds friction for near-zero
  retrieval-relevant signal.
- **Every clinical note** — free text notes are low signal-density for a
  structured graph query. The "current clinical question" field already
  captures the doctor's actual intent; a full note dump doesn't change what
  Athena queries.
- **Full medication list** — only cancer-relevant or interaction-relevant
  meds matter (anticoagulants before biopsy, QT-prolonging drugs for
  interaction checks). An unrelated med list doesn't feed any query today.
- **Full raw imaging (DICOM)** — Athena has no image-analysis pipeline. A
  structured "progressed: yes/no, new lesion: where" summary carries all the
  retrieval-relevant signal; raw imaging is a real future integration, not an
  MVP requirement.
- **Family history** — relevant only for the germline-predisposition subset
  of cases. Requiring it universally adds friction for the majority of cases
  where it changes nothing about the query.
- **Full treatment dosing/date granularity** — line + drug + outcome is
  enough to know what's exhausted. Exact doses and start/end dates refine
  trial-eligibility math later but don't change which evidence Athena
  retrieves at query time.
- **Geography/demographics beyond age** — doesn't change literature/CIViC
  retrieval at all. Geography only matters once you build the access-pathway/
  trial-site layer the founder-mode doc describes (§3b, `RegulatoryPathway`
  nodes) — real, but explicitly P2/future, not MVP.

The goal stated plainly: every field added to intake is a tax on doctor time
and a reason the tool doesn't get used. Each P0 field earns its place because
removing it either breaks the query or makes the output actively unsafe —
not because it would be nice to have.

---

## 8. Recommended intake UI hierarchy

This maps almost exactly onto `docs/ui-flow.md`'s existing Screen 1/2 split —
worth noting that instinct was already right — with one addition: Disease
State should be its own explicit level, since it isn't currently a field in
`ui-flow.md` at all.

| Level | Question it answers | Fields |
|---|---|---|
| 1 — Case Identity | "What are we treating?" | cancer_type, primary_site, histology, age |
| 2 — Disease State Now | "What's happening right now?" | stage, metastatic_sites, progression_status *(not currently in `ui-flow.md` — add it)* |
| 3 — Molecular Fingerprint | "What's unique about this tumor?" | known alterations (gene + variant), extended biomarkers if available |
| 4 — Treatment So Far | "What's been tried?" | regimen / line / outcome log *(matches existing Screen 2 field)* |
| 5 — The Ask | "What do we need Athena to figure out?" | current clinical question, manual override toggle *(matches existing Screen 2)* |

---

## 9. Parameter → Athena capability mapping

| Patient parameter | What Athena uses it for |
|---|---|
| Cancer type / histology | Literature, trial, and CIViC evidence-item filtering |
| Stage / metastatic sites | Trial eligibility gating, clinical context |
| Age (pediatric/adult) | Which guideline body / trial network applies |
| Molecular profile | Direct Tier 1/Tier 2 query key — evidence retrieval + structural plausibility |
| Extended biomarkers (TMB/MSI/PD-L1) | Hypothesis generation, immunotherapy-relevant filtering |
| Treatment history | Resistance/response analysis, "what's already exhausted" framing |
| Performance status / organ function | Trial and therapy eligibility filtering |
| Imaging / progression status | Dynamic disease-state tracking, loop-trigger detection |
| Current clinical question | Output framing and synthesis target |
| Prior hypotheses / decisions made | Avoids redundant research on re-entry |

---

## 10. For the hackathon: implement vs. leave out

**Implement (P0 only, as required intake fields):** cancer_type, stage
(+ met sites if applicable), molecular profile (gene + variant), treatment
history (even a simple repeatable drug+outcome list), current clinical
question, age. This is a six-field form — genuinely fast to fill, and it's
enough to make the Tier 1 → Tier 2 handoff and the "standard-of-care
exhausted" framing both real rather than asserted.

**Surface as optional, not required:** performance status, organ function
flags, extended biomarkers, imaging summary — expandable "add more context"
section, not gating submission.

**Explicitly leave out for the hackathon:** everything in P2/P3 —
family history, full imaging, full med lists, expression-data integration,
access-pathway/geography reasoning. Naming these as deliberately deferred
(not forgotten) is itself a good demo answer if a judge asks "what about
X" — the repo's existing honesty-first posture (`ISSUES.md`, the "one rule"
in `README.md`) is a real strength; this schema should carry the same
discipline rather than quietly implying broader coverage than exists.

**One gap worth closing before demo day:** today, `treatment_history` and
`current_clinical_question` aren't consumed by any code path — Tier 1/Tier 2
only see `gene`, `mutation`, `cancer_type`. Even a minimal wiring — using the
clinical question to set `restrict_to_drugs`, and treatment history to
suppress already-tried drugs from the results list — would make the P0
schema actually load-bearing rather than collected-but-unused, which is the
detail most likely to come up under questioning.
