# Hardware Sizing Guide

## What's actually measured here, and what isn't

The figures below are **real measurements** — `docker stats` against
the actual containers built from this repo's `Dockerfile` /
`web/Dockerfile`, running the real API and a real Postgres instance
with all migrations applied. First measured 2026-08-24, **re-measured
the same day** after issue #99's fix changed the API image
substantially (see below) — the numbers here reflect the second,
current pass, not the first.

What this does **not** include: sizing under real clinical-case load
(concurrent users querying the API, a full FalkorDB knowledge graph
loaded via `civic_loader.py`/`pubmed_loader.py`, Tier 2 structural
prediction running). That's a follow-up load-testing pass against the
seeded demo cases the issue asks for — flagged honestly as not done
yet, rather than presented as though it were.

## A real finding that changed this whole document

The first pass of this guide measured the API idle, before any
`/research` call. That undercounted its real footprint: `api/deps.py`
never actually ran `signals/literature.py`'s semantic (embedding-based)
evidence retrieval, because `get_graph()`/`get_llm_client()` were
disconnected stubs (issue #98) and, separately, the API image never
included the `sentence-transformers` dependency `literature.py` needs
(issue #99 — a hard crash on every single `/research` call, not a
degraded path). Both are now fixed. Fixing them changed the real
resource picture:

- The API image grew from 635 MB to **8.91 GB**, driven almost
  entirely by `torch` (sentence-transformers' dependency).
- The API container's RAM grew from ~60 MiB idle to **~680 MiB** the
  moment it actually serves a `/research` call that touches semantic
  retrieval, because the embedding model (`all-MiniLM-L6-v2`, ~90 MB
  of weights) loads into memory on first use and stays resident
  (`tier1/semantic_retrieval.py`'s `_get_model()` is a lazy, one-time
  singleton per process).
- The **first ever** `/research` call on a freshly-created container
  took **~47 seconds**, because the embedding model isn't baked into
  the image — it downloads from Hugging Face on first use. A plain
  container **restart** (same writable layer, cache survives) reloads
  it from local disk in **~16 seconds**. A full container
  **recreation** (redeploy, image update — writable layer is wiped)
  goes back to the ~47-second network download. See
  `offline-capability-matrix.md` for what this means for air-gapped
  deployments.

This is a direct, honest consequence of a real bug being fixed
correctly rather than worked around — see issues
[#98](https://github.com/healers-second-look/Athena/issues/98) and
[#99](https://github.com/healers-second-look/Athena/issues/99). The
lean-footprint story in the first version of this document was
accurate for what the API *actually did* at the time (nothing —
`/research` silently never reached real evidence), not for what it
does now that it works.

## Measured footprint

| Service | RAM (idle, before first `/research` call) | RAM (after a real `/research` call) | CPU (idle) | Notes |
|---|---|---|---|---|
| `api` | 62–72 MiB | **~678 MiB** | ~0.1% | The jump happens once, on first use per container lifetime — see above |
| `web` (nginx) | 11 MiB | — | ~0% | Static file serving only, unaffected |
| `postgres` | 14 MiB | — | ~0% | Steady-state idle; the first pass's 35 MiB/~10% CPU reading was a momentary post-migration spike, not steady state |
| `falkordb` | 95 MiB | — | ~0.3% | Measured against an existing instance with prior data loaded — a truly empty instance would likely be lower |

**Realistic total once the API has served at least one research
request: roughly 800 MiB–1 GiB of RAM** across all four application
containers, before OS/Docker daemon overhead — not the "well under 300
MiB" the first pass of this document claimed. That earlier number was
real, but it was measuring a code path that didn't actually work yet.

## Image sizes (re-measured 2026-08-24, after issue #99's fix)

| Image | Size | Change from first pass |
|---|---|---|
| `athena-api` / `athena-migrate` (same image, both rebuilt in sync) | **8.91 GB** | was 635 MB |
| `athena-web` (nginx + built bundle) | 73.9 MB | unchanged |
| `postgres:16` (upstream, unmodified) | 642 MB | unchanged |
| `falkordb/falkordb:latest` (upstream, unmodified) | 744 MB | unchanged |

`torch` (sentence-transformers' dependency) is the overwhelming
majority of that growth. The `hgvs`/`pysam` finding from the first pass
of this document (a smaller, secondary contributor) still stands
unaddressed — see below.

**A real finding, not swept under the rug:** the API image is heavier
than it strictly needs to be, for two independent reasons now:

1. `hgvs` is a *core* dependency (not gated behind an extra), and
   transitively pulls in `pysam` (wraps `htslib`, a compiled genomics
   library) — a Tier 2/mutation-notation concern, not something the
   REST API needs at runtime for case-memory/diff-engine/synthesis
   operations.
2. `sentence-transformers`/`torch` (see above) is now a genuine runtime
   requirement of `/research`, not an avoidable one — this is no longer
   a "slim it down" opportunity the way `hgvs` is, since every
   `ChangeKind` unconditionally dispatches through
   `signals/literature.py`'s semantic retrieval.

Slimming `hgvs` out of the API image is still a reasonable follow-up
(either making `hgvs` itself extras-gated, or building a separate
`api`-only image that doesn't import anything from
`mutation_validation.py`'s dependency chain) but wasn't done as part of
this pass — flagged, not silently fixed, since it would change what
`pip install -e ".[api]"` installs.

## Sizing recommendation

Built on the measured baseline above plus known scaling factors — not a
second independent measurement.

| Scale | vCPU | RAM | Disk | Notes |
|---|---|---|---|---|
| **Small** (one hospital, single clinician workflow) | 2 | **6 GB** (was 4 GB) | **25 GB** (was 20 GB) | Raised from the first pass's figures to give real headroom above the ~1 GiB realistic idle/light-use total measured above, plus image storage for the now-8.91 GB API image. Does not include the `structural` extra (Tier 2 docking). |
| **Medium** (regional network, several hospitals sharing one instance) | 4–8 | 10–18 GB | 60–110 GB | FalkorDB's memory footprint grows with the evidence graph's size; Postgres grows with case-history volume. Neither was load-tested here — treat this row as directional, not measured. |

**If running Tier 2 structural prediction** (`structural` extra: RDKit,
AutoDock Vina, Playwright) **on the same server**, add substantially
more RAM on top of the above — `README.md`'s existing prerequisites
table already documents ≥3 GB free disk for `sentence-transformers`
alone (now bundled into the API image itself, not just local tooling —
see the correction below), from prior real experience ("a full disk
wedged Docker during development"). `structural` is not part of the
`docker-compose.yml` stack this guide sizes; it runs as local Python
tooling, not a containerized service, as of this pass.

**Correction to the first pass of this document:** it stated Mode 3
semantic retrieval (`semantic` extra) "runs as local Python tooling,
not a containerized service." That was wrong — confirmed wrong by an
actual crash, not a second guess. `signals/literature.py` calls
semantic retrieval unconditionally for every dispatched question, so
it is a hard runtime dependency of the containerized `api` service,
not optional local tooling. See issue #99.

## What would make this a stronger measurement

- Load-test against the actual seeded demo cases mentioned in the
  project's own docs, with concurrent API requests
- Measure FalkorDB's real memory footprint after a full `civic_loader.py`
  + `pubmed_loader.py` run, not an instance with unknown pre-existing
  data
- Measure Postgres growth over a realistic case-history volume (e.g. 100
  cases × 50 events each) rather than an empty schema
- Address the `hgvs`/`pysam` image-size finding above, then re-measure
- Consider baking the embedding model into the image at build time
  (trading a larger image for zero network dependency + no ~47s
  first-call cost) — see `offline-capability-matrix.md`
