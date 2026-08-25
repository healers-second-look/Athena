"""Enforce issue #103's evidence bar on pull requests touching a live surface.

The rule already existed in prose. Issue #103 states it plainly:

    A PR without this evidence should not be merged, regardless of how
    confident the description sounds.

PR #106 merged anyway -- zero reviews, a description asserting six completed
phases, and pasted JSON in place of a driven flow. One payload it quoted
(`"citation-guard active with retrieved context present"`) was a string the
merged code could not produce. Three follow-up PRs (#108, #110, #111) fixed
what a single driven run would have surfaced first.

So the rule moves out of one issue's prose and into the repo, where it
applies without anyone remembering it.

## What triggers it

Only PRs that change a surface a human can drive: the frontend, or an API
route. A change to a signal generator or a loader is not exempt from review,
it is exempt from *this* check, because there is no UI flow to record.

## What satisfies it

An `## Evidence` heading whose body contains a real artefact:

* an image or video link (a screenshot or recording of the driven flow), or
* a fenced block holding an actual request/response payload.

Deliberately NOT satisfied by prose alone. "Tested locally, works" is the
exact claim the bar exists to stop being sufficient. This checks for the
*shape* of evidence, which is all a linter can do -- a reviewer still has to
look at it. That is the point: it forces the artefact to exist so there is
something to look at.
"""

from __future__ import annotations

import re

#: Paths where a change is drivable by a human and must therefore be shown.
SURFACE_PREFIXES = ("web/src/", "web/index.html", "src/secondlook/api/")

#: Paths that look like a surface but cannot be driven.
SURFACE_EXEMPT_SUFFIXES = (".test.jsx", ".test.js", ".spec.jsx", ".spec.js")

_EVIDENCE_HEADING = re.compile(r"^#{1,4}\s*evidence\b.*$", re.IGNORECASE | re.MULTILINE)
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_HEADING_LINE = re.compile(r"^#{1,4}\s")
_IMAGE_OR_VIDEO = re.compile(
    r"!\[[^\]]*\]\([^)]+\)"  # markdown image
    r"|<img\s"  # inline html image
    r"|<video\s"
    r"|https?://\S+\.(?:png|jpe?g|gif|webp|mp4|mov|webm)"
    r"|https?://github\.com/user-attachments/\S+"
    r"|https?://\S*githubusercontent\.com/\S+",
    re.IGNORECASE,
)
_FENCED_BLOCK = re.compile(r"```[^\n]*\n(.+?)```", re.DOTALL)


def touches_a_drivable_surface(changed_paths: list[str]) -> bool:
    """True when at least one changed path is a surface someone can drive."""
    for path in changed_paths:
        if path.endswith(SURFACE_EXEMPT_SUFFIXES):
            continue
        if path.startswith(SURFACE_PREFIXES):
            return True
    return False


def _next_heading_offset(text: str) -> int | None:
    """Offset of the next heading, ignoring anything inside a code fence.

    Fence-awareness is not a nicety. Evidence for this repo routinely
    contains markdown -- a captured assistant reply opens with `## On: ...`
    and `### Evidence search could not be run`. Scanning for `^#` without
    tracking fences truncates the section at the first line of the very
    payload being checked, so a PR with real evidence reads as having none.
    Caught by running this against PR #111, which is exactly that shape.
    """
    offset = 0
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and _HEADING_LINE.match(line):
            return offset
        offset += len(line)
    return None


def evidence_section(body: str) -> str | None:
    """The text under the `## Evidence` heading, or None if there is none."""
    if not body:
        return None
    match = _EVIDENCE_HEADING.search(body)
    if match is None:
        return None
    rest = body[match.end() :]
    following = _next_heading_offset(rest)
    return rest[:following] if following is not None else rest


def _has_real_payload(section: str) -> bool:
    """A fenced block with something in it -- not an empty or placeholder one."""
    for block in _FENCED_BLOCK.findall(section):
        stripped = block.strip()
        if len(stripped) >= 40 and not stripped.lower().startswith(("todo", "tbd", "n/a")):
            return True
    return False


def check(body: str, changed_paths: list[str]) -> tuple[bool, str]:
    """`(ok, message)`. Only fails PRs that change a drivable surface."""
    if not touches_a_drivable_surface(changed_paths):
        return True, "No drivable surface changed; the evidence bar does not apply."

    section = evidence_section(body)
    if section is None:
        return False, (
            "This PR changes a surface someone can drive (web/src or "
            "src/secondlook/api) but has no '## Evidence' section.\n\n"
            "Add one showing the flow actually running: a screenshot or "
            "recording of the real frontend against the real backend, and for "
            "backend changes the request/response actually exchanged.\n\n"
            "Issue #103: 'A PR without this evidence should not be merged, "
            "regardless of how confident the description sounds.'"
        )

    if _IMAGE_OR_VIDEO.search(section):
        return True, "Evidence section contains a screenshot or recording."
    if _has_real_payload(section):
        return True, "Evidence section contains a request/response payload."

    return False, (
        "The '## Evidence' section has no artefact in it -- only prose.\n\n"
        "Prose is the thing this check exists to stop being sufficient: a "
        "description that sounds confident is not evidence that the flow ran. "
        "Include a screenshot/recording of the driven flow, or a fenced block "
        "holding the actual request/response payload."
    )


__all__ = [
    "SURFACE_PREFIXES",
    "check",
    "evidence_section",
    "touches_a_drivable_surface",
]
