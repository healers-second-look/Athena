# API contracts v2 (case memory)

These are the Pydantic models in `secondlook.query.contracts` plus the
REST request bodies in `secondlook.api.schemas`. MCP tools return query
results inside the uniform `{items, empty_reason}` envelope. REST routes
unwrap that envelope at the HTTP boundary: a GET of a single resource
returns the resource (or 404), never the envelope itself.

MCP authentication (issue #60) is a static bearer token in
`ATHENA_MCP_API_KEY`, required only when `--allow-remote` is passed.
Loopback-bound SSE/streamable-http and stdio stay unauthenticated — the
same trust boundary as a local process. Clients send
`Authorization: Bearer <token>` (the MCP SDK's `BearerAuthBackend` reads
that header; there is no custom `X-` header). `AuthSettings.issuer_url`
and `resource_server_url` are SDK plumbing so `RequireAuthMiddleware`
turns on; they are not a real OAuth authorization server. REST write-route
auth is a **separate** secret (`ATHENA_API_KEY` / `X-Athena-Api-Key`),
fail-closed unless `ATHENA_API_AUTH_DISABLED=true`.

## Envelope

Every tool/query returns:

```json
{"items": [], "empty_reason": "string or null"}
```

`empty_reason` is required when `items` is empty. Never a silent `[]`.

## Models

See `src/secondlook/query/contracts.py`:

- `CaseSummary` — case demographics, folded alterations, question counts, active finding count, plus `current_state` (alterations/biomarkers/treatments/assessments, mirroring `case/state.py`'s `CaseState`) and `timeline` (raw event list) for the frontend's dashboard (issue #101 — these two were originally missing even though the underlying `CaseState` data was already computed correctly)
- `CaseView` — bare Case row returned by `POST /api/cases` (no folded state; `CaseSummary` is too heavy for creation)
- `EvidenceItem` — one structured retrieval hit (`retrieval_mode` is `exact` or `relaxed`; semantic retrieval is not chained)
- `TrialMatchResult` — bucketed eligibility match for one trial
- `AccessPathway` — country-level expanded-access route after Drug identity resolution
- `ChangeSetForApi` — **display-shaped** diff (human-readable `summary` strings). Not a field-for-field mirror of `case/diff.py`'s `ChangeSet`
- `FindingDetail` / `DecisionView` — one finding plus question text, case id, assumption descriptions, and decision history
- `QueueView` — questions plus status counts; does not fold the event log

## Honest gaps this PR does not hide

- `biomarker_thresholds` for `get_recent_changes` defaults to `{}`. No production thresholds exist in the repo, so biomarker-shift detection is inert until a clinically authorized caller supplies values.
- AccessPathway nodes are country-level, not per-drug. Drug identity is still resolved first (name / `chembl_id` / optional InChIKey via SMILES) so an unrecognized name cannot silently receive another country's generic pathways. `ligand_identity.py` is InChIKey matching, not RxNorm.
- Trial *signal* dispatch already attaches eligibility buckets (issue #46). This query layer's `match_trials` tool is a separate, case-scoped compose of the same matcher; it does not change generator dispatch.
- `POST /api/cases/{id}/research` attaches `DiseaseNotProgressing()` to every synthesized finding. That is a documented placeholder, not a per-`ChangeKind` clinical mapping.
- `POST /research` is not idempotent (`case/memory.py` `suppress_duplicates` is unbuilt).
- The brief HTML view is plain string-templating, not Jinja2.
