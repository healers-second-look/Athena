# Trial criteria extraction — pre-committed validation criteria

**Written before any accuracy number was measured.** Criteria here are fixed and
must not be adjusted after seeing results, following the same rule
`docs/validation-plan.md` applies to the structural pipeline. Falling below a
threshold is a documented outcome with a defined fallback, not something to fix
by moving the bar.

## Why this document exists

The Subsystem F issue states the requirement directly:

> Criteria extraction accuracy is unvalidated until a spot-check harness exists
> — **do not ship the bucketing as authoritative without a documented
> sample-accuracy check.**

The risk is specific. A matcher that buckets a patient `highly_compatible` on a
misread criterion sends someone to a trial that will turn them away. A matcher
that buckets them `probably_incompatible` on a misread criterion hides a trial
they could have joined. Neither failure announces itself: both produce
confident, plausible output.

## What is measured

Extraction is scored **per line**, against a hand-annotated corpus of real
ClinicalTrials.gov eligibility sections in `tests/trials/fixtures/`.

For each line the annotation records the predicate type a careful human reader
says it is. The extractor's output for that line is then one of:

| Outcome | Meaning |
|---|---|
| **correct** | extracted type equals the annotated type |
| **missed** | annotated as a real type, extracted as `UNPARSEABLE` |
| **wrong** | extracted a real type that is not the annotated one |

These are deliberately not collapsed into one accuracy figure, because they
carry very different costs.

## Criteria

### C1 — No wrong extractions (hard requirement)

**`wrong` must be 0.**

A `missed` line becomes an `UNPARSEABLE` predicate, which the matcher resolves
to `needs_verification` — the honest answer, and a human reads the criterion. A
`wrong` line becomes a confidently evaluated predicate that is about the wrong
thing, and it buckets a patient with no signal that anything went awry.

This is the only criterion with a zero tolerance, and it is deliberate: the
system is allowed to not know, and is not allowed to be confidently wrong.

### C2 — Recall on the regular types

**At least 70% of lines annotated `AGE_RANGE` or `ECOG_MAX` are extracted
correctly.**

These two are the genuinely regular patterns in registry prose. If the
rule-based extractor cannot reach 70% on them, rules are the wrong tool and the
LLM-assisted path is required rather than optional.

70% is chosen as the same threshold `validation-plan.md` uses, for consistency
rather than from any property of this task.

### C3 — Nothing is silently dropped

**Every non-empty line in the source text produces exactly one predicate.**

`lines_seen` must equal `len(predicates)`. A dropped criterion reads downstream
as a criterion the patient satisfies.

### C4 — Section attribution

**Every line inside an inclusion or exclusion block is attributed to that
section.**

Inclusion and exclusion invert the meaning of the same sentence: "prior
anthracycline therapy" is a requirement under one and a disqualifier under the
other. A line attributed to `unknown` when the source made it plain is a
correctness failure, not a formatting one.

## Corpus

Target is **~30 real eligibility sections**, per the issue. Fixtures are real
registry text, not written for the test — the failure modes that matter are the
ones real sponsors produce.

## What passing does and does not license

Passing means extraction is accurate enough on this corpus that the
`needs_verification` bucket reflects genuine data gaps rather than parser
failures.

It does **not** license presenting `highly_compatible` as a clinical
recommendation. Bucketing is a triage aid over registry text; it does not read
the protocol, does not know the site's current slots, and cannot see anything a
sponsor did not write down.

## Fallback if a criterion fails

If C1 fails, the rule-based extractor is not fit to run unsupervised: route all
extraction through the LLM-assisted path with human spot-checks, or restrict
predicate types to those with no `wrong` results.

If C2 fails, report `needs_verification` for the affected types rather than
lowering the threshold.
