# Diff-first evaluation study — protocol

**Issue:** #136 · **Status:** DRAFT v0.1 — not frozen. Nothing below is
pre-registered until §12's freeze checklist is complete and the frozen commit is
tagged. Items marked **TBD** are owed by a named person and are listed in §11.

This is a first-class tested hypothesis, not a claim inherited from the
literature. The literature review found essentially no prior work on a
clinician-facing interface where reviewing a computed diff is the primary
interaction loop (review §5, §11), so Athena cannot cite precedent for "diff-first
review improves error detection or trust calibration." This study is how that
claim gets earned, or fails to.

## 1. Question and hypotheses

**Question.** When a clinician reviews an updated oncology case, does organizing
the review around *what changed and what that invalidated* (diff-first) change how
well they detect flawed or stale findings, compared with reviewing the same
content through a chat interface or a state-only dashboard?

Hypotheses are fixed before any data exists. "Seeded issue" and the three issue
types are defined in §4.

| ID | Hypothesis | Role |
|---|---|---|
| **H1** | For `change_visible` issues, detection rate is higher in diff-first (A) than in dashboard-only (B) **and** than in chat-only (C). | Primary |
| **H3** | For `change_missed` issues (the system's own diff misses an invalidation), detection in A is **not lower** than in B. | Primary — a *risk* hypothesis |
| H2 | For `change_independent` issues, detection does not differ across arms. | Secondary; no benefit is claimed |
| H4 | Over-reliance (accepting a flawed finding) is not higher in A than B or C. | Secondary |
| H5–H7 | Verification behaviour, decision concordance, and time/burden differ across arms. | Exploratory, direction not pre-committed |

H3 exists because the literature warns the opposite of H1 can happen: He et al.
(2025) found LLM-agent-style interfaces *amplified* over-reliance, and Qazi et al.
(2025) found erroneous chat-style advice cut diagnostic accuracy by 14 points even
in AI-trained physicians. A diff banner that reviewers trust too much is a
plausible failure of this design, and the study must be able to detect it.

## 2. Design

**Within-subject crossover, three arms.** Every reviewer reviews cases in all
three arms, so between-reviewer skill differences do not confound the arm effect.

- **Case pool:** *P* synthetic cases (§5), each shown to a reviewer at most once.
- **Per reviewer:** 3 cases per arm (9 total, ~10–15 min each; see §7 on session
  length). Proposed; finalized once reviewer count is known.
- **Counterbalancing:** arm order rotated across reviewers with a 3×3 Latin square;
  case-to-arm assignment rotated so, across reviewers, every case appears in every
  arm about equally often. The assignment is generated from a published RNG seed
  and committed *before* the first session.
- **One training case per arm** (not analysed) so reviewers learn each interface
  before being measured.

**Why not between-subject:** a realistic panel is small (**TBD**, see §11); a
between-subject design would spend most of its power on reviewer variability.

## 3. The three arms — matched content, different organization

The single most important validity rule: **all three arms show the same
underlying system output** (§4). Only the *organizing principle* differs. If arms
differed in evidence content, any difference could be content, not interface.

| Arm | What the reviewer sees | What is deliberately absent |
|---|---|---|
| **A — diff-first** | The change-review screen as shipped: change banner, struck (superseded) findings with the broken assumption named, the question worklist, and findings with inline citations. | Nothing withheld. |
| **B — dashboard-only** | Current case state, the dated event timeline, and the same findings list with the same inline citations. | The change banner, supersession marking, and worklist. **No consensus score** (a strawman dashboard would make the result meaningless). |
| **C — chat-only** | The chat interface (citation-gated, issue #124), opened with the same findings as a first "briefing" message, the case events available as context. The reviewer may ask follow-ups. | No dashboard, no diff banner. The engine's changeset is **not** injected into the chat — asking "what changed?" is answered from the events, as a chat user would. |

Fixed and logged for arm C: model ID, prompt template, temperature, and every
turn. Follow-up answers are live model output and therefore not deterministic;
this is a stated limitation (§10), not something to hide.

**"Diff-first" is a bundle** (banner + supersession + worklist). This study tests
the bundle. Which component carries any effect is a follow-up ablation, not
claimed here.

## 4. Shared system output and seeded issues

Each case carries a fixed **system output**: the findings, the changeset the
system reports (what it says changed and what it superseded), and the open
questions. It is authored, not generated, so the flaws in it are known.

A **seeded issue** is a finding the reviewer *should* flag as no longer valid or
unsupported. Ground truth is fixed per finding. Three types, reported separately:

| Type | Definition | What it tests |
|---|---|---|
| `change_visible` | New data invalidates a finding **and the system's changeset says so.** Arm A shows it struck; B and C show it as an ordinary finding. | The claimed benefit of diff-first. |
| `change_missed` | New data invalidates a finding but **the system's changeset fails to flag it.** | Over-reliance on the diff. The banner is silent; only careful review catches it. |
| `change_independent` | A flaw unrelated to change over time: e.g. a citation that does not support its claim, a wrong evidence level, a mis-bucketed trial. | Whether any arm affects general error detection. |

Plus **no-issue control cases** (no seeded issue) to measure false alarms.

Reporting the types separately is required. Diff-first structurally hands
reviewers information about change; pooling all issue types would let a
`change_visible` advantage masquerade as a general one.

`change_missed` is **simulated** — the shipped diff engine is deterministic and is
not expected to miss; the case author removes the supersession. This is disclosed
in §10.

## 5. Case pool

- **Scope:** HR+/HER2− early breast cancer (issue #121's MVP type); aligned with,
  not a second copy of, #121's gold set.
- **Synthetic only.** No real patient data at any stage (`POLICY.md` §5). Every
  case is labeled synthetic in its own file.
- **Each case:** a baseline state, an update event, the system output (§4), the
  seeded issues with ground truth, and a **reference decision** with concordant
  and acceptable options, written by a clinician from the guideline KB.
- **Target mix (proposed):** roughly one third no-issue controls; the remainder
  split across the three issue types, including cases with more than one issue.
- **Freeze:** the case set is content-hashed and the hash recorded in §12 before
  any session. A case set with `review_status: unreviewed`, or citations not
  verified as real and supporting their claims, is **rejected by the loader for
  study runs** (`secondlook.study`), so an unreviewed set cannot be run by accident.
- **Clinician review is required** for medical correctness of every case and
  reference decision. **TBD (§11).**

## 6. Outcomes and instruments

All six outcomes named in the issue. Definitions are per reviewer-case unless
stated.

| Outcome | Measure |
|---|---|
| **Error detection** | Sensitivity = seeded issues flagged / seeded issues; false-alarm rate = valid findings flagged / valid findings. By issue type (§4). |
| **Trust calibration** | Per-finding confidence (0–100 that "this finding is valid") scored against ground truth: Brier score and calibration slope. Over-reliance = P(accept \| flawed); under-reliance = P(reject \| valid). Plus the published TrAAIT instrument (Stevens & Stetson, 2023) once per arm — **items taken verbatim from the published instrument, not paraphrased; licensing TBD.** |
| **Evidence verification** | Logged: citation/source opens per finding, share of findings whose source was opened before the final decision, time on evidence. |
| **Decision quality** | Final management decision scored against the pre-committed reference: concordant / acceptable / discordant. Free-text rationale scored by clinicians **blind to arm**. |
| **Cognitive / memory burden** | Raw NASA-TLX (six subscales, 0–100) after each case; plus a **recall probe** — after leaving the case screen, a structured "what changed since the last visit?" checklist, scored for accuracy. |
| **Time to complete** | Case open → decision submitted, with idle periods (> 60 s no input) recorded and reported both included and excluded. |

The review notes small case counts, benchmark-only evaluation, and LLM-judge
scoring as the field's common weakness (§1, §9). This study uses real clinician
reviewers and, where judgement is needed, blinded clinician scorers. **LLM-judge
scoring is not used for any reported outcome.** A documented substitute for real
clinicians is allowed only if justified and labeled as such in the results.

## 7. Procedure

1. Consent and briefing (**ethics-approved text, TBD**). Reviewers are told some
   cases contain flawed items and some do not; the rate is not disclosed. *(Decision
   to confirm before freeze: whether to disclose the rate.)*
2. One untimed training case per arm.
3. Three blocks, one per arm, in the reviewer's Latin-square order. Each block:
   3 cases → per case: review → flag findings + confidence → decision → TLX →
   recall probe.
4. Debrief, and an optional free-text interview.

Session length is a real constraint: the product's own usability bar is a
ten-minute session (research-direction notes, Part III). Nine cases plus training
is likely **two sessions**; this is confirmed in the dry run (Phase 4), not assumed.

## 8. Analysis plan (pre-registered)

- **Primary models:** mixed-effects logistic regression, per seeded issue:
  `detected ~ arm × issue_type + arm_order + (1 | reviewer) + (1 | case)`.
- **Primary contrasts:** H1 — A vs B and A vs C on `change_visible`; H3 — A vs B on
  `change_missed`. Multiplicity: Holm across the primary contrasts.
- **Reporting:** effect sizes with 95% confidence intervals for every contrast,
  reported whether or not they are "significant." No results are dropped.
- **Secondary/exploratory** outcomes are labeled exploratory and not used for the
  verdict.
- **Analysis code** is committed and frozen *before* data collection; any deviation
  is logged with reason in the write-up.
- A **power / precision analysis** (by simulation from the frozen design) is filed
  before freeze. With a small panel the study may only be able to bound effects,
  not detect small ones; that is stated up front rather than discovered after.

## 9. Verdict rule (pre-committed)

The house rule applies: **a partial pass is a fail, and is reported as one.**

- **Supported** only if H1 holds against **both** B and C (95% CI excludes zero in
  the favourable direction) **and** H3 shows A is not lower than B.
- **Not supported** if H1 fails against either comparison, **or** H3 shows A is
  lower than B (i.e. the diff increases over-reliance).
- **Inconclusive** if the intervals are too wide to exclude a meaningful effect in
  either direction. Inconclusive is reported as "no support," and does not license
  the claim.

Whichever verdict results is written up as a first-class result, including
"not supported."

## 10. Threats to validity and limitations

- **Synthetic cases** trade realism for ground truth. Findings may not transfer.
- **Small panel:** wide intervals likely; may be reported as a pilot.
- **Bundle, not mechanism** (§3): the study cannot say which part of diff-first
  helps.
- **Simulated engine misses** (§4): `change_missed` cases are authored, not
  observed; real miss patterns may differ.
- **Arm C is stochastic:** live model output varies by run; mitigated by pinning
  and logging, not eliminated. The arm-C "best case" is deliberately steel-manned
  (citation gate on, case events supplied) so a diff-first win is not against a
  strawman.
- **Learning/carry-over:** mitigated by counterbalancing and distinct cases per
  arm, not eliminated.
- **Builder conflict of interest:** the tool's builders designed the arms and
  cases. Mitigations: scorers and, ideally, the analyst are independent of the
  build team; the analysis is pre-registered; H3 is a hypothesis designed to be
  able to embarrass the design.
- **Blinding:** reviewers cannot be blind to arm. Only scorers can.

## 11. Open items — owed before freeze

| # | Item | Owner |
|---|---|---|
| 1 | Reviewer panel: who, how many, and how recruited | **TBD** |
| 2 | Ethics / IRB determination and consent text | **TBD** |
| 3 | Clinician(s) to review case medicine and write/verify reference decisions | **TBD** |
| 4 | Clinicians to score free-text rationales blind to arm | **TBD** |
| 5 | Pinned model for arm C (BioMistral per #122, or a hosted model) | **TBD** |
| 6 | TrAAIT: item text and licensing | **TBD** |
| 7 | Power / precision simulation | build team |
| 8 | Whether to disclose flawed-item prevalence to reviewers | study lead |
| 9 | Independent analyst | **TBD** |

The literature review this protocol cites lists six outcomes in a §13 that is not
in the copy circulated so far (the copy ends at §11). §6 follows the six named in
issue #136; reconcile against the review if a later version exists.

## 12. Freeze checklist

- [ ] Items 1–6 and 9 in §11 resolved
- [ ] Case set `review_status: clinician_reviewed`, citations verified, hash recorded
- [ ] Arm/case assignment generated from a committed seed
- [ ] Power / precision analysis filed
- [ ] Analysis code committed
- [ ] Protocol tagged `study-protocol-v1` at the frozen commit

## 13. Related work

- Issue #121 (MVP cancer type, gold set); #122 (backend for arm C); #124
  (citation enforcement in arm C).
- The research-direction notes also plan a *different* blinded A/B — deterministic
  pipeline vs specialist-framed output. That is a separate question from this one;
  the two may share cases and tooling but are not merged.

## References

- Qazi et al. (2025). Automation bias in LLM-assisted diagnostic reasoning among
  AI-trained physicians. medRxiv.
- He, Aishwarya & Gadiraju (2025). Is conversational XAI all you need? *IUI '25*.
- Rajashekar et al. (2024). Human-algorithmic interaction using an LLM-augmented AI
  clinical decision support system. *CHI '24*.
- Stevens & Stetson (2023). Theory of trust and acceptance of AI technology
  (TrAAIT). *J Biomed Inform* 148.
- Küper et al. (2024). Psychological factors influencing appropriate reliance on
  AI-enabled CDSS. *JMIR* 27.
- Romeo & Conti (2025). Exploring automation bias in human-AI collaboration.
  *AI & Society* 41.
- Hart & Staveland (1988). Development of NASA-TLX. *Advances in Psychology* 52.
