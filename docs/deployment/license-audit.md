# License Audit

Every direct dependency Athena ships with — Python and JavaScript — has a
verified license, checked in at
[`license-audit.yaml`](license-audit.yaml) and enforced by
[`tests/deployment/test_license_audit.py`](../../tests/deployment/test_license_audit.py):
a new dependency added without recording its license here fails CI, the
same way `NO_PHI_COLUMN_PATTERN` fails CI on a disallowed schema column.

## Summary

All direct dependencies are permissive (MIT, BSD-3-Clause, Apache-2.0) or
weak/dependency-safe copyleft (LGPL, MPL) — none conflict with shipping
Athena under AGPL-3.0 + a commercial-licensing option. See
`license-audit.yaml` for the full table with sources and check dates; the
two entries worth knowing about specifically:

- **`psycopg`** (LGPL-3.0-only) and **`meeko`** (LGPL-2.1-or-later) — LGPL
  explicitly permits use by a work under any license, including a
  proprietary one, as long as the LGPL'd library itself isn't modified
  without sharing those specific changes. No conflict with Athena's own
  license or with commercial licensees.
- **`falkordb/falkordb` (the database server, not the Python client)** —
  SSPL-1.0, a source-available license that is **not** OSI-approved open
  source. Its restrictive clause targets someone offering FalkorDB itself
  as a competing hosted database service — not an application (like
  Athena) that runs it as an internal backend component. Flagged for
  transparency, not because it currently blocks anything.

## Self-hostable model checkpoints

A `models:` section in `license-audit.yaml` audits open-weight model
checkpoints a deployer can choose to run behind
`synthesis/llm_client.py`'s `OpenAICompatibleClient` (issue #122) — not a
pip/npm dependency, so not covered by the automated
pyproject.toml/package.json cross-check below, but audited by hand the
same way the `infrastructure:` section's Docker images are, for the same
transparency reason. **`biomistral-7b`** (Apache-2.0, fully permissive) is
the first entry — see
[`docs/deployment/biomistral-deployment.md`](biomistral-deployment.md)
for the deployment recipe and, critically, the model publisher's own
advisory against clinical production use without further testing, which
a permissive *license* does not override.

## Method

Direct dependencies only (what's declared in `pyproject.toml` and
`web/package.json`), checked against PyPI's `license_expression` /
classifier metadata and the npm registry's `license` field on
2026-08-24. This does **not** cover the full transitive dependency tree —
doing that thoroughly would need a proper SBOM tool (e.g.
`pip-licenses`, `license-checker`, or a Syft/Grype scan), which is a
reasonable next step but wasn't run for this first pass. Direct
dependencies are the ones a maintainer actually chooses to add; the audit
enforcement (a new *direct* dependency needs a recorded license) is the
part that's actually automated and actually prevents drift.

## Data source licensing

This document covers *code*. Data source licensing (CIViC, PubMed,
ClinicalTrials.gov, and what's explicitly excluded — NCCN, DrugBank,
OncoKB) is a separate, already-documented concern — see
[`docs/data-sources.md`](../data-sources.md).

## Updating this audit

Adding a new dependency:

1. Add it to `pyproject.toml` or `web/package.json` as normal.
2. Check its license — `license_expression` in `curl -s
   https://pypi.org/pypi/<name>/json | jq '.info.license_expression'`
   for Python, or `npm view <name> license` for JavaScript.
3. Add an entry to `license-audit.yaml` in the same PR. `tests/deployment/test_license_audit.py`
   will fail the build otherwise.
4. If the license doesn't look permissive or LGPL/MPL-style
   dependency-safe, flag it for a maintainer decision before merging —
   don't just add the entry and move on.
