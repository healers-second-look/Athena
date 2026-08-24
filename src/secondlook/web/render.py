"""Server-rendered HTML for Finding Detail and Brief. Pure, and no JavaScript.

Issue #14 asks for a server-rendered fallback for these two views
specifically, "read-mostly and benefit least from a heavy client bundle".
That is taken literally here: these pages ship **zero** bytes of JavaScript
and make **zero** subresource requests. The stylesheet is inlined, there are
no webfonts and no images, so a Finding Detail is one request and one round
trip on the 3G budget in `docs/performance-budget.md`.

## The invariant this file exists to hold

`IMPLEMENTATION_PLAN.md` SS9.2: "The `computed` card must have **no place**
for a citation -- not an empty one." So there is no shared `_card()` helper
taking an optional citation and rendering it conditionally. There are four
renderers with four different signatures, and `_computed_card()` **does not
take a citation argument at all**. You cannot pass it one. That is the UI
half of what `signals/types.py.__post_init__` enforces in the data model,
and `tests/web/test_render.py` asserts the signature so a future refactor
into a "nice" shared component fails the suite instead of quietly
reintroducing the ambiguity.

Rendering documented and computed side by side is a first-class case, not an
edge one: as of issue #46 a matched trial produces two signals -- a
DOCUMENTED one citing the registry ("this trial is recruiting") and a
COMPUTED one carrying our matcher's bucket ("this patient probably does not
qualify"). Reconciling them is subsystem M's job, and per
`signals/types.py`'s docstring the generators deliberately do not do it for
us. Two cards, two treatments, both shown.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
STYLESHEET = _REPO_ROOT / "web" / "src" / "styles" / "app.css"

#: Spelled-out names for the four classes. The badge text, and the only
#: thing distinguishing the classes if CSS fails to apply at all.
CLASS_LABEL: dict[str, str] = {
    "documented": "Documented",
    "computed": "Computed",
    "regulatory": "Regulatory",
    "contextual": "Contextual",
}

#: Glyph plus a spelled-out name for each change kind. The glyph is
#: decorative -- SS9.1's mock uses "+" and an up-arrow -- and the words are
#: what a screen reader announces.
CHANGE_MARK: dict[str, tuple[str, str]] = {
    "new_alteration": ("+", "newly observed"),
    "biomarker_shift": ("↑", "threshold crossed"),
    "treatment_line_change": ("→", "treatment line changed"),
    "disease_progression": ("!", "disease assessment changed"),
}


def _e(value: object) -> str:
    """Escape anything into HTML text. `None` renders as empty, never "None"."""
    return "" if value is None else escape(str(value), quote=True)


def load_stylesheet(path: Path | None = None) -> str:
    source = path or STYLESHEET
    if not source.is_file():
        raise FileNotFoundError(
            f"Subsystem M stylesheet not found at {source}. The server-rendered "
            "views inline it; they do not fall back to an unstyled page, because "
            "the four evidence classes are only distinguishable with it."
        )
    return source.read_text(encoding="utf-8")


def page(title: str, body: str, *, stylesheet: str | None = None) -> str:
    """The whole document. One request: CSS inlined, no script tag anywhere."""
    css = stylesheet if stylesheet is not None else load_stylesheet()
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n"
        f"<style>{css}</style>\n"
        "</head>\n<body>\n"
        f'<div class="wrap">\n{body}\n</div>\n'
        "</body>\n</html>\n"
    )


def _caveats(caveats: list[str] | tuple[str, ...] | None) -> str:
    """Caveats are rendered whenever present, for every class.

    ARCHITECTURE.md SS8's first invariant is "no evidence, no claim -- and no
    silent gaps either". A caveat that exists in the data and not on the
    screen is exactly that gap, so there is no "collapse if long" branch.
    """
    if not caveats:
        return ""
    items = "".join(f"<li>{_e(c)}</li>" for c in caveats)
    return f'<ul class="caveats">{items}</ul>'


def _citation_link(url: str | None, label: str | None) -> str:
    """A documented/regulatory citation. Always clickable, never bare text."""
    if not url:
        return ""
    text = label or url
    return f'<a href="{_e(url)}" rel="noreferrer noopener">{_e(text)}</a>'


# ---------------------------------------------------------------------------
# The four cards. Four signatures on purpose -- see the module docstring.
# ---------------------------------------------------------------------------


def _documented_card(
    claim: str,
    *,
    source_name: str | None,
    citation_url: str,
    citation_id: str | None,
    evidence_level: str | None,
    caveats=None,
) -> str:
    """`citation_url` is REQUIRED and positional-free -- there is no path here
    that renders a documented card without one, mirroring
    `signals.types.DocumentedSource.__post_init__`."""
    level = (
        f' <span class="small muted">Level {_e(evidence_level)}</span>' if evidence_level else ""
    )
    cite = _citation_link(citation_url, citation_id or source_name)
    return (
        '<article class="card card-documented">'
        '<div class="badge badge-documented">Documented</div>'
        f'<p class="claim">{_e(claim)}</p>'
        f'<p class="small">{_e(source_name)}{level} &middot; {cite}</p>'
        f"{_caveats(caveats)}"
        "</article>"
    )


def _computed_card(claim: str, *, method: str, version: str, caveats=None) -> str:
    """No citation parameter. Not an optional one -- none.

    IMPLEMENTATION_PLAN.md SS9.2: the computed card must have no place for a
    citation, "not an empty one". Adding one here to "support the case where
    we do have a URL" is the refactor this signature exists to stop; a
    computed signal that has acquired a citation is a documented signal, and
    the generator, not the renderer, is where that gets fixed.
    """
    return (
        '<article class="card card-computed">'
        '<div class="badge badge-computed">Computed</div>'
        f'<p class="claim">{_e(claim)}</p>'
        f'<p class="method">{_e(method)} &middot; {_e(version)}</p>'
        f"{_caveats(caveats)}"
        "</article>"
    )


def _regulatory_card(
    claim: str,
    *,
    instrument: str,
    citation_url: str | None = None,
    caveats=None,
) -> str:
    """The instrument is cited; precedent is stated separately (ARCHITECTURE.md
    SS5). This renderer never asserts precedent -- if a caller has one, it
    belongs in `caveats` where it reads as a separate claim."""
    cite = _citation_link(citation_url, "instrument")
    tail = f" &middot; {cite}" if cite else ""
    return (
        '<article class="card card-regulatory">'
        '<div class="badge badge-regulatory">Regulatory</div>'
        f'<p class="claim">{_e(claim)}</p>'
        f'<p class="small">{_e(instrument)}{tail}</p>'
        f"{_caveats(caveats)}"
        "</article>"
    )


def _contextual_card(
    claim: str,
    *,
    source_name: str | None = None,
    citation_url: str | None = None,
    caveats=None,
) -> str:
    """Visually subordinate, and it can never drive an option."""
    cite = _citation_link(citation_url, source_name or "source")
    tail = f' <span class="small">{cite}</span>' if cite else ""
    return (
        '<article class="card card-contextual">'
        '<div class="badge badge-contextual">Contextual</div>'
        f'<p class="claim">{_e(claim)}</p>'
        f'<p class="small">Background, not a finding about this patient.{tail}</p>'
        f"{_caveats(caveats)}"
        "</article>"
    )


def render_card(finding: dict) -> str:
    """Dispatch on `evidence_class`, unpacking only the fields that class carries.

    An unknown class raises rather than falling back to a generic card. A
    fifth evidence class arriving unnoticed and rendering as a neutral box is
    precisely the flattening ARCHITECTURE.md SS5 forbids.
    """
    klass = finding.get("evidence_class")
    source = finding.get("source") or {}
    claim = finding.get("claim", "")
    caveats = finding.get("caveats")

    if klass == "documented":
        return _documented_card(
            claim,
            source_name=source.get("name"),
            citation_url=source["citation_url"],
            citation_id=source.get("citation_id"),
            evidence_level=finding.get("evidence_level"),
            caveats=caveats,
        )
    if klass == "computed":
        # Only method and version are read off the source. Even if a caller
        # smuggled a citation_url onto a computed source dict, it has no way
        # of reaching the page.
        return _computed_card(
            claim,
            method=source["method"],
            version=source["version"],
            caveats=caveats,
        )
    if klass == "regulatory":
        return _regulatory_card(
            claim,
            instrument=source["instrument"],
            citation_url=source.get("citation_url"),
            caveats=caveats,
        )
    if klass == "contextual":
        return _contextual_card(
            claim,
            source_name=source.get("name"),
            citation_url=source.get("citation_url"),
            caveats=caveats,
        )
    raise ValueError(
        f"unknown evidence class {klass!r}; the four classes in ARCHITECTURE.md "
        "SS5 each have their own renderer, and there is no generic fallback on purpose"
    )


# ---------------------------------------------------------------------------
# SS9.1 change banner -- shared by the Brief and (in JSX) the Case Dashboard
# ---------------------------------------------------------------------------


def render_change_banner(changes: dict) -> str:
    """The banner from SS9.1. Renders every change, not a truncated sample."""
    items = changes.get("changes") or []
    supersessions = changes.get("supersessions") or []
    if not items and not supersessions:
        reason = changes.get("unchanged_reason") or "No tracked field changed."
        return f'<div class="panel"><p class="muted">{_e(reason)}</p></div>'

    since = changes.get("since")
    head = f"{len(items)} change{'s' if len(items) != 1 else ''}"
    if since:
        head += f" since {_e(since)}"

    rows = []
    for change in items:
        mark, spoken = CHANGE_MARK.get(str(change.get("kind")), ("•", "changed"))
        when = change.get("observed_on")
        rows.append(
            '<div class="change-line">'
            f'<span class="change-mark" aria-hidden="true">{_e(mark)}</span>'
            f'<span class="change-kind">{_e(spoken)}:</span>'
            f"<span>{_e(change.get('summary'))}</span>"
            + (f'<span class="change-when">{_e(when)}</span>' if when else "")
            + "</div>"
        )

    sup_html = ""
    if supersessions:
        count = len(supersessions)
        sup_rows = []
        for s in supersessions:
            label = s.get("finding_label") or s.get("finding_id")
            trigger = s.get("triggering_event_label") or s.get("triggering_event_id")
            sup_rows.append(
                '<div class="supersession">'
                f'<div class="superseded-claim">{_e(label)}: {_e(s.get("finding_claim"))}</div>'
                f'<div class="supersession-why">{_e(s.get("note"))}</div>'
                f'<div class="supersession-trigger">&rarr; {_e(trigger)}</div>'
                "</div>"
            )
        sup_html = (
            f'<div class="supersession-head">&#8856; {count} prior finding'
            f"{'s' if count != 1 else ''} superseded</div>" + "".join(sup_rows)
        )

    return (
        '<section class="banner" role="alert">'
        f'<div class="banner-head">&#9888; {head}</div>' + "".join(rows) + sup_html + "</section>"
    )


# ---------------------------------------------------------------------------
# Degraded lanes and explained empty states -- the server half of #88
# ---------------------------------------------------------------------------
#
# These two mirror web/src/components/DegradeNotice.jsx and EmptyState.jsx,
# and they exist for the same reason the fixture set is shared: the no-JS
# fallback and the client must not disagree about whether a lane was
# reached. A brief that omits a failed lookup tells a tumour board we
# searched and found nothing, which is a different sentence than the truth.


def render_degrade_notice(failure: dict) -> str:
    """A lane whose live lookup failed, labelled as such.

    Per `docs/api-contracts.md` a failure object is ALWAYS rendered and never
    filtered out before reaching the view, so there is no severity threshold
    below which this returns "". Only a missing object renders nothing --
    and that means no failure was reported, not that one was ignored.
    """
    if not failure:
        return ""
    lane = failure.get("lane")
    head = f"{lane} lookup unavailable" if lane else "Lookup unavailable"
    last_known = failure.get("last_known_at")
    if last_known:
        # Stale data is useful, and must never be passed off as current.
        freshness = (
            f"Showing last known state from <strong>{_e(str(last_known)[:10])}</strong>. "
            "This is not a live result."
        )
    else:
        freshness = "No cached result is available for this lane."
    retry = (
        "This may succeed on retry. Everything else on this page is local and unaffected."
        if failure.get("retryable")
        else "This will not succeed on retry without a change upstream."
    )
    return (
        '<div class="degraded" role="status">'
        f'<div class="degraded-head">{_e(head)}</div>'
        f'<p class="small">{_e(failure.get("reason"))}</p>'
        f'<p class="small">{freshness}</p>'
        f'<p class="small muted">{retry}</p>'
        "</div>"
    )


def render_empty_state(reason: str) -> str:
    """An empty panel that says why it is empty.

    The reason is REQUIRED and this raises without one, the same move as
    `_computed_card` having no citation parameter to pass: a rule that is
    merely documented gets skipped by someone in a hurry, and this skip is
    invisible because a blank panel looks like a working panel with nothing
    in it. Making the unexplained version impossible to render is the only
    form of "absence must be visible" that survives a deadline.
    """
    if not reason or not str(reason).strip():
        raise ValueError(
            "render_empty_state requires a reason -- an unexplained empty panel "
            "is a defect, not a neutral state"
        )
    return f'<p class="empty-state">{_e(reason)}</p>'


# ---------------------------------------------------------------------------
# The two server-rendered views
# ---------------------------------------------------------------------------


def _provenance(entries: list[dict] | None) -> str:
    """The full chain, every step, clickable where a step has a URL.

    SS9 requires the provenance chain be clickable through to PubMed/CIViC.
    Steps without a URL still render -- an unlinkable step is part of the
    chain, and dropping it would make the chain look shorter than it is.
    """
    if not entries:
        return '<p class="muted small">No provenance chain recorded for this finding.</p>'
    rows = []
    for entry in entries:
        url = entry.get("url")
        detail = _e(entry.get("detail"))
        if url:
            detail += f' &middot; {_citation_link(url, "open source")}'
        rows.append(
            "<li>"
            f'<div class="step">{_e(entry.get("step"))}</div>'
            f'<div class="detail">{detail}</div>'
            "</li>"
        )
    return f'<ol class="provenance">{"".join(rows)}</ol>'


def _decisions(entries: list[dict] | None) -> str:
    if not entries:
        return '<p class="muted small">No clinician review recorded yet.</p>'
    rows = [
        "<li>"
        f'<strong>{_e(d.get("action"))}</strong> &mdash; {_e(d.get("reason"))}'
        f'<div class="small muted">{_e(d.get("decided_by"))}, {_e(d.get("decided_at"))}</div>'
        "</li>"
        for d in entries
    ]
    return f'<ul class="caveats">{"".join(rows)}</ul>'


def render_finding_detail(finding: dict, *, stylesheet: str | None = None) -> str:
    """`/findings/:id` with no JavaScript.

    Review buttons post a normal form. The no-JS view is not a read-only
    consolation prize: a clinician on a 3G handset can still record a
    decision, which is the whole point of the fallback existing.
    """
    superseded = finding.get("status") == "superseded"
    label = finding.get("label") or "Finding"
    claim_class = "superseded-claim" if superseded else ""

    banner = ""
    if superseded:
        trigger = finding.get("superseded_event_label") or finding.get("superseded_by")
        banner = (
            '<section class="banner" role="alert">'
            '<div class="banner-head">&#8856; Superseded</div>'
            f'<div class="supersession-why">{_e(finding.get("superseded_note"))}</div>'
            f'<div class="supersession-trigger">&rarr; {_e(trigger)}</div>'
            "</section>"
        )

    body = (
        f'<p class="small muted"><a href="/cases/{_e(finding.get("case_id"))}">'
        "&larr; Case dashboard</a></p>"
        f"<h1>{_e(label)}</h1>"
        f'<p class="small muted">In answer to: {_e(finding.get("question_text"))}</p>'
        f"{banner}"
        f'<p class="{claim_class}">{_e(finding.get("claim"))}</p>'
        f"{render_card(finding)}"
        "<h2>Provenance</h2>"
        f"{_provenance(finding.get('provenance'))}"
        "<h2>Clinician review</h2>"
        f"{_decisions(finding.get('decisions'))}"
        f'<form class="actions" method="post" action="/findings/{_e(finding.get("id"))}/decision">'
        '<button type="submit" name="action" value="investigating">Investigating</button>'
        '<button type="submit" name="action" value="deferred">Defer</button>'
        '<button type="submit" name="action" value="rejected">Reject</button>'
        "</form>"
        '<p class="small muted">A reason is required with every decision, including '
        '"investigating".</p>'
        '<p class="nojs-note">Server-rendered view: no JavaScript, no webfonts, '
        "no image requests. See docs/performance-budget.md.</p>"
    )
    return page(f"{label} — Athena", body, stylesheet=stylesheet)


def render_brief(
    case: dict,
    changes: dict,
    queue: dict,
    findings: dict,
    *,
    stylesheet: str | None = None,
) -> str:
    """`/cases/:id/brief` -- the tumour-board handout. Server-rendered, print-ready.

    Findings are grouped by evidence class in the order documented ->
    computed -> regulatory -> contextual, so the strongest warrant is read
    first and the contextual block lands last and subordinate. Superseded
    findings are printed struck through rather than omitted: the historical
    record is the point (IMPLEMENTATION_PLAN.md SS4.2).
    """
    active = [f for f in findings.values() if f.get("status") != "superseded"]
    superseded = [f for f in findings.values() if f.get("status") == "superseded"]
    order = {"documented": 0, "computed": 1, "regulatory": 2, "contextual": 3}
    active.sort(key=lambda f: (order.get(f.get("evidence_class"), 9), f.get("id", "")))

    state = case.get("current_state") or {}
    alterations = ", ".join(
        f"{a.get('gene')} {a.get('variant')}" for a in state.get("alterations") or ()
    )
    biomarkers = ", ".join(
        f"{b.get('name')} {b.get('value')}{b.get('unit') or ''}"
        for b in (state.get("biomarkers") or {}).values()
    )
    treatments = ", ".join(
        f"{t.get('regimen')} ({t.get('action')}, line {t.get('line')})"
        for t in state.get("treatments") or ()
    )
    assessments = state.get("assessments") or []
    latest = assessments[-1].get("status") if assessments else None

    panel = (
        '<div class="panel"><dl>'
        f"<dt>Cancer type</dt><dd>{_e(case.get('cancer_type'))}</dd>"
        f"<dt>Stage</dt><dd>{_e(case.get('stage') or 'not recorded')}</dd>"
        f"<dt>Age</dt><dd>{_e(case.get('age_years') or 'not recorded')}</dd>"
        f"<dt>Alterations</dt><dd>{_e(alterations or 'none recorded')}</dd>"
        f"<dt>Biomarkers</dt><dd>{_e(biomarkers or 'none recorded')}</dd>"
        f"<dt>Treatments</dt><dd>{_e(treatments or 'none recorded')}</dd>"
        f"<dt>Latest assessment</dt><dd>{_e(latest or 'never assessed')}</dd>"
        "</dl></div>"
    )

    counts = queue.get("counts") or {}
    open_qs = queue.get("open") or []

    # Which lanes could not be reached this run. A question dispatched into
    # one of them was not answered-and-empty, it was never asked, and the
    # brief must not let those two read the same on paper.
    failures = queue.get("failures") or []
    degraded_lanes = {f.get("lane"): f for f in failures if f.get("lane")}
    coverage = (
        "<h2>Coverage</h2>" + "".join(render_degrade_notice(f) for f in failures)
        if failures
        else ""
    )

    def _q_row(q: dict) -> str:
        # A question whose lane failed is still listed -- dropping it would
        # shorten the worklist by hiding work that was never done.
        note = (
            '<div class="small muted">Lane unavailable this run — this question '
            "was not dispatched.</div>"
            if q.get("lane") in degraded_lanes
            else ""
        )
        return (
            '<li class="q">'
            f'<div class="q-priority">Priority {_e(q.get("priority"))}</div>'
            f"<div>{_e(q.get('text'))}</div>"
            f"{note}"
            "</li>"
        )

    q_rows = "".join(
        _q_row(q)
        for q in sorted(open_qs, key=lambda q: (-int(q.get("priority", 0)), q.get("id", "")))
    )
    suppressed_n = int(counts.get("suppressed", 0) or 0)
    suppressed_note = (
        f'<p class="suppressed-count">{suppressed_n} suppressed as already answered</p>'
        if suppressed_n
        else ""
    )

    superseded_html = ""
    if superseded:
        rows = "".join(
            '<div class="supersession">'
            f'<div class="superseded-claim">{_e(f.get("label") or f.get("id"))}: '
            f'{_e(f.get("claim"))}</div>'
            f'<div class="supersession-why">{_e(f.get("superseded_note"))}</div>'
            "</div>"
            for f in superseded
        )
        superseded_html = f"<h2>Superseded findings</h2>{rows}"

    body = (
        f"<h1>{_e(case.get('label'))} — tumour-board brief</h1>"
        f'<p class="small muted">Synthetic case. Generated {_e(changes.get("computed_at"))}. '
        "Research/clinical decision support — see POLICY.md.</p>"
        f"{render_change_banner(changes)}"
        f"{coverage}"
        "<h2>Current state</h2>"
        f"{panel}"
        "<h2>Findings</h2>"
        + (
            "".join(render_card(f) for f in active)
            or render_empty_state(
                "No active findings. Every finding on this case has been superseded "
                "by a later one."
            )
        )
        + superseded_html
        + "<h2>Open questions</h2>"
        + (
            f'<ul style="list-style:none;padding:0">{q_rows}</ul>'
            if q_rows
            else render_empty_state(
                "No open questions. Every question raised by the last change set "
                "has been answered."
            )
        )
        + suppressed_note
        + '<p class="nojs-note">Server-rendered, print-ready: no JavaScript, no '
        "webfonts, no image requests.</p>"
    )
    return page(f"{case.get('label')} — brief", body, stylesheet=stylesheet)
