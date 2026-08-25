## What does this PR do?

<!-- Describe the change. Link the issue it addresses, e.g. "Closes #12". -->

## Which subsystem(s) does this touch?

<!-- Reference the relevant issue/area label(s), e.g. area: diff-engine -->

## Checklist

- [ ] `pytest` passes locally (offline suite; the count grows with the
      repo, so compare against `main` rather than a number written here).
- [ ] `ruff` / `black` run clean.
- [ ] New code has test coverage in `tests/` (or `tests/tier1/`).
- [ ] I have not softened, removed, or bypassed any existing
      validation/caveat language (e.g., Tier 2's binding-affinity
      disclaimers) as part of this change.
- [ ] If this touches a deterministic component (e.g., the diff/
      assumption engine), it introduces **no LLM calls** — see
      `CONTRIBUTING.md`.
- [ ] If this adds/changes a data source, it's consistent with
      `docs/data-sources.md` (open/free sources only in any shipped
      path).
- [ ] This PR contains **no real patient data, PHI, or PII** — in code,
      tests, fixtures, commit messages, or this description. See
      `POLICY.md` §5.
- [ ] Docs updated if this changes documented behavior (`README.md`,
      `ARCHITECTURE.md`, or the relevant subsystem issue).

## Evidence

<!--
REQUIRED when this PR changes web/src/ or src/secondlook/api/ -- anything a
human can drive. CI checks that this section exists and contains an actual
artefact; it is skipped for PRs that touch neither.

Issue #103: "A PR without this evidence should not be merged, regardless of
how confident the description sounds." That line was written after a PR
merged on a description alone and needed three follow-ups to fix what one
driven run would have shown.

Paste at least one of:

  * a screenshot or short recording of the flow actually running -- the real
    frontend against the real backend, not a design comp;
  * the request/response actually exchanged, in a fenced block.

For a graph/visualisation change, show the rendered result NEXT TO the query
and data it came from, so it is clear it is not a placeholder.

`python -m secondlook.devtools.capture_evidence` drives the chat API end to
end and writes docs/evidence/. It cannot record the UI flow -- that part
still needs a human with a browser.

Prose does not satisfy this. "Tested locally, works" is the exact claim the
bar exists to stop being sufficient.
-->

## Anything reviewers should pay special attention to?
