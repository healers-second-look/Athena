"""Patient Timeline routes. Thin: parse, call the timeline module, map to HTTP.

Two entry points onto the same reference bundle:

- `/api/cases/{case_id}/timeline` is nested under an existing case (see
  `get_existing_case`) so the timeline is scoped to a real case rather than
  an arbitrary string -- even though `get_patient_timeline` ignores the id
  today, see its docstring.
- `/api/timeline` is unscoped, for callers with no case in hand at all --
  the chat interface (`ChatInterface.jsx`'s Patient Timeline button), whose
  sessions are keyed by `context_id` (a KG context, e.g. "graph:tier1"), not
  by case. Faking a case id there would misrepresent a link that doesn't
  exist; this route is honest about serving the same reference data with no
  case scoping at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from secondlook.api.deps import get_existing_case
from secondlook.api.schemas import TimelineBundleView
from secondlook.timeline.reference_data import get_patient_timeline

router = APIRouter(tags=["timeline"])


@router.get("/api/cases/{case_id}/timeline", response_model=TimelineBundleView)
def read_timeline(case=Depends(get_existing_case)) -> TimelineBundleView:
    bundle = get_patient_timeline(str(case.id))
    return TimelineBundleView(**bundle.as_dict())


@router.get("/api/timeline", response_model=TimelineBundleView)
def read_reference_timeline() -> TimelineBundleView:
    bundle = get_patient_timeline("unscoped")
    return TimelineBundleView(**bundle.as_dict())


__all__ = ["router"]
