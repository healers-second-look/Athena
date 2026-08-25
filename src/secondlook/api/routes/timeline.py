"""Patient Timeline route. Thin: parse, call the timeline module, map to HTTP.

Nested under /api/cases/{case_id} so the timeline is scoped to a real,
existing case (see `get_existing_case`) rather than an arbitrary string --
even though `get_patient_timeline` ignores the id today, see its docstring.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from secondlook.api.deps import get_existing_case
from secondlook.api.schemas import TimelineBundleView
from secondlook.timeline.reference_data import get_patient_timeline

router = APIRouter(prefix="/api/cases", tags=["timeline"])


@router.get("/{case_id}/timeline", response_model=TimelineBundleView)
def read_timeline(case=Depends(get_existing_case)) -> TimelineBundleView:
    bundle = get_patient_timeline(str(case.id))
    return TimelineBundleView(**bundle.as_dict())


__all__ = ["router"]
