"""Reference timeline dataset -- real, published patient data used as seed
content while there is no real patient timeline data in this system yet.

Source: osteosarc.com/timeline (Sid Sijbrandij's public osteosarcoma
treatment data, published under an open license for exactly this kind of
reuse). Downloaded 2026-08-25 from:
  - https://osteosarc.com/data/events.tsv
  - https://osteosarc.com/data/mrd.tsv
  - https://osteosarc.com/data/cytometry.tsv
  - https://osteosarc.com/data/lab_results.tsv

`events.tsv` covers six categories (Imaging, Omics, Pathology, Procedures,
Symptoms, Treatments); this module scopes to the three the Patient Timeline
feature asks for -- Treatments, Procedures, Imaging -- at conversion time,
not here, so the checked-in JSON already matches what the API serves.

get_patient_timeline() is the one function the API route calls, and it is
the seam where this stops being reference data. Today it ignores
`patient_id` entirely and returns this same fixed bundle for every case --
that is the honest current behavior, not hidden behind a name that implies
per-patient data already works. Swapping in real data means replacing this
function's body with real queries (Case Memory Store events for
treatments/procedures, an imaging system integration, a lab/MRD/flow
cytometry data source) that return the same `TimelineBundle` shape, so nothing
above this module (the route, the frontend) needs to change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "reference"


@dataclass(frozen=True)
class TimelineBundle:
    events: list[dict] = field(default_factory=list)
    mrd: list[dict] = field(default_factory=list)
    cytometry: list[dict] = field(default_factory=list)
    lab_results: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "events": self.events,
            "mrd": self.mrd,
            "cytometry": self.cytometry,
            "lab_results": self.lab_results,
        }


def _load(name: str) -> list[dict]:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _reference_bundle() -> TimelineBundle:
    """Load once, not once per request -- lab_results.json alone is ~1.4MB
    and this data never changes at runtime (it's a static reference
    dataset), so re-parsing it on every call would be pure waste.
    """
    return TimelineBundle(
        events=_load("events"),
        mrd=_load("mrd"),
        cytometry=_load("cytometry"),
        lab_results=_load("lab_results"),
    )


def get_patient_timeline(patient_id: str) -> TimelineBundle:
    """The one seam a real backend swaps in. `patient_id` is accepted and
    validated by the caller (see routes/timeline.py's get_existing_case
    dependency) but not yet used -- every case sees the same reference
    dataset today. That is a deliberate, temporary state: real patient data
    was explicitly out of scope for this pass (issue TBD), and pretending
    otherwise by silently keying on patient_id while still returning the
    same rows for everyone would be worse than being upfront about it.
    """
    del patient_id  # not yet used -- see docstring
    return _reference_bundle()


__all__ = ["TimelineBundle", "get_patient_timeline"]
