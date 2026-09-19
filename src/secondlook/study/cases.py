"""Study case sets for the diff-first evaluation (issue #136).

A study case is a *synthetic* patient case plus the fixed "system output" a
reviewer is shown (findings, the changeset the system reports, open
questions), plus ground truth about which findings are flawed and why. The
output is authored, not generated, so every flaw in it is known -- the study
measures whether reviewers catch them (docs/research/diff-first-study-protocol.md
sections 4-5).

Three seeded-issue types, reported separately by the protocol:

- ``change_visible``: new data invalidates a finding and the system's
  changeset says so.
- ``change_missed``: new data invalidates a finding and the system's
  changeset does NOT say so. Simulated -- the shipped diff engine is
  deterministic; the case author removes the supersession.
- ``change_independent``: a flaw unrelated to change over time.

Everything here is pure: no I/O beyond reading a YAML file, no database.

Fail-closed, on purpose. Unknown keys are errors (a typo'd field must not
silently become "no flaw"), and ``assert_eligible_for_study`` refuses any set
that is not clinician-reviewed with verified citations, so an unreviewed set
cannot be run against real reviewers by accident. The pilot set shipped in
``case_sets/`` exists only to exercise the harness and is refused by that
check by design.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from secondlook.case.models import EVENT_TYPES

DEFAULT_CASE_SET_DIR = Path(__file__).parent / "case_sets"

ISSUE_TYPES: tuple[str, ...] = ("change_visible", "change_missed", "change_independent")
REVIEW_STATUSES: frozenset[str] = frozenset({"unreviewed", "clinician_reviewed"})
STUDY_ELIGIBLE_STATUS = "clinician_reviewed"
STUDY_EVIDENCE_CLASSES: frozenset[str] = frozenset({"documented", "computed"})


class CaseSetError(ValueError):
    """A case-set file is structurally malformed (unknown/missing keys, bad types)."""


class IneligibleCaseSetError(RuntimeError):
    """A case set cannot be used for a study run; `.reasons` lists every cause."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("case set is not eligible for a study run: " + "; ".join(reasons))


@dataclass(frozen=True)
class Citation:
    id: str
    url: str
    name: str


@dataclass(frozen=True)
class StudyEvent:
    id: str
    occurred_on: str
    event_type: str
    summary: str
    source_document: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StudyFinding:
    """`valid`/`invalidated_by`/`flaw` are ground truth the reviewer never sees."""

    id: str
    claim: str
    evidence_class: str
    valid: bool
    evidence_level: str | None = None
    citation: Citation | None = None
    method: str | None = None
    invalidated_by: str | None = None
    flaw: str | None = None


@dataclass(frozen=True)
class ReportedChange:
    kind: str
    summary: str
    triggering_event: str


@dataclass(frozen=True)
class ReportedSupersession:
    finding_id: str
    broken_assumption: str
    triggering_event: str
    note: str


@dataclass(frozen=True)
class StudyQuestion:
    id: str
    text: str


@dataclass(frozen=True)
class SystemOutput:
    findings: tuple[StudyFinding, ...]
    reported_changes: tuple[ReportedChange, ...] = ()
    reported_supersessions: tuple[ReportedSupersession, ...] = ()
    questions: tuple[StudyQuestion, ...] = ()


@dataclass(frozen=True)
class SeededIssue:
    id: str
    type: str
    finding_id: str
    description: str


@dataclass(frozen=True)
class DecisionOption:
    id: str
    text: str


@dataclass(frozen=True)
class ReferenceDecision:
    prompt: str
    options: tuple[DecisionOption, ...]
    concordant: tuple[str, ...]
    acceptable: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudyCase:
    case_id: str
    label: str
    cancer_type: str
    synthetic: bool
    citations_verified: bool
    baseline_events: tuple[StudyEvent, ...]
    update_events: tuple[StudyEvent, ...]
    system_output: SystemOutput
    seeded_issues: tuple[SeededIssue, ...]
    reference_decision: ReferenceDecision
    age_years: int | None = None
    stage: str | None = None
    # Plausible changes that did NOT happen in this case, mixed with the real
    # update events for the post-review "what changed?" recall probe
    # (protocol section 6, memory burden). Authored per case, like everything
    # else a reviewer sees.
    recall_distractors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseSet:
    set_id: str
    version: int
    review_status: str
    cases: tuple[StudyCase, ...]
    reviewed_by: str | None = None
    notes: str | None = None


# --- parsing -----------------------------------------------------------------


def _take(raw: Any, where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict:
    if not isinstance(raw, dict):
        raise CaseSetError(f"{where}: expected a mapping, got {type(raw).__name__}")
    unknown = sorted(set(raw) - set(required) - set(optional))
    if unknown:
        raise CaseSetError(f"{where}: unknown key(s) {unknown}")
    missing = [k for k in required if k not in raw]
    if missing:
        raise CaseSetError(f"{where}: missing required key(s) {missing}")
    return raw


def _seq(raw: Any, where: str) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CaseSetError(f"{where}: expected a list, got {type(raw).__name__}")
    return raw


def _parse_event(raw: Any, where: str) -> StudyEvent:
    d = _take(
        raw,
        where,
        ("id", "occurred_on", "event_type", "summary"),
        ("source_document", "payload"),
    )
    return StudyEvent(
        id=str(d["id"]),
        occurred_on=str(d["occurred_on"]),
        event_type=str(d["event_type"]),
        summary=str(d["summary"]),
        source_document=d.get("source_document"),
        payload=dict(d.get("payload") or {}),
    )


def _parse_finding(raw: Any, where: str) -> StudyFinding:
    d = _take(
        raw,
        where,
        ("id", "claim", "evidence_class", "valid"),
        ("evidence_level", "citation", "method", "invalidated_by", "flaw"),
    )
    citation = None
    if d.get("citation") is not None:
        c = _take(d["citation"], f"{where}.citation", ("id", "url", "name"))
        citation = Citation(id=str(c["id"]), url=str(c["url"]), name=str(c["name"]))
    if not isinstance(d["valid"], bool):
        raise CaseSetError(f"{where}.valid: must be a boolean")
    return StudyFinding(
        id=str(d["id"]),
        claim=str(d["claim"]),
        evidence_class=str(d["evidence_class"]),
        valid=d["valid"],
        evidence_level=d.get("evidence_level"),
        citation=citation,
        method=d.get("method"),
        invalidated_by=d.get("invalidated_by"),
        flaw=d.get("flaw"),
    )


def _parse_system_output(raw: Any, where: str) -> SystemOutput:
    d = _take(
        raw, where, ("findings",), ("reported_changes", "reported_supersessions", "questions")
    )
    findings = tuple(
        _parse_finding(f, f"{where}.findings[{i}]")
        for i, f in enumerate(_seq(d["findings"], f"{where}.findings"))
    )
    changes = []
    for i, c in enumerate(_seq(d.get("reported_changes"), f"{where}.reported_changes")):
        cd = _take(c, f"{where}.reported_changes[{i}]", ("kind", "summary", "triggering_event"))
        changes.append(
            ReportedChange(str(cd["kind"]), str(cd["summary"]), str(cd["triggering_event"]))
        )
    supers = []
    for i, s in enumerate(_seq(d.get("reported_supersessions"), f"{where}.reported_supersessions")):
        sd = _take(
            s,
            f"{where}.reported_supersessions[{i}]",
            ("finding_id", "broken_assumption", "triggering_event", "note"),
        )
        supers.append(
            ReportedSupersession(
                str(sd["finding_id"]),
                str(sd["broken_assumption"]),
                str(sd["triggering_event"]),
                str(sd["note"]),
            )
        )
    questions = []
    for i, q in enumerate(_seq(d.get("questions"), f"{where}.questions")):
        qd = _take(q, f"{where}.questions[{i}]", ("id", "text"))
        questions.append(StudyQuestion(str(qd["id"]), str(qd["text"])))
    return SystemOutput(findings, tuple(changes), tuple(supers), tuple(questions))


def _parse_case(raw: Any, where: str) -> StudyCase:
    d = _take(
        raw,
        where,
        (
            "case_id",
            "label",
            "cancer_type",
            "synthetic",
            "citations_verified",
            "baseline_events",
            "update_events",
            "system_output",
            "seeded_issues",
            "reference_decision",
        ),
        ("age_years", "stage", "recall_distractors"),
    )
    for flag in ("synthetic", "citations_verified"):
        if not isinstance(d[flag], bool):
            raise CaseSetError(f"{where}.{flag}: must be a boolean")
    issues = []
    for i, s in enumerate(_seq(d["seeded_issues"], f"{where}.seeded_issues")):
        sd = _take(s, f"{where}.seeded_issues[{i}]", ("id", "type", "finding_id", "description"))
        issues.append(
            SeededIssue(
                str(sd["id"]), str(sd["type"]), str(sd["finding_id"]), str(sd["description"])
            )
        )
    rd = _take(
        d["reference_decision"],
        f"{where}.reference_decision",
        ("prompt", "options", "concordant"),
        ("acceptable",),
    )
    options = []
    for i, o in enumerate(_seq(rd["options"], f"{where}.reference_decision.options")):
        od = _take(o, f"{where}.reference_decision.options[{i}]", ("id", "text"))
        options.append(DecisionOption(str(od["id"]), str(od["text"])))
    return StudyCase(
        case_id=str(d["case_id"]),
        label=str(d["label"]),
        cancer_type=str(d["cancer_type"]),
        synthetic=d["synthetic"],
        citations_verified=d["citations_verified"],
        baseline_events=tuple(
            _parse_event(e, f"{where}.baseline_events[{i}]")
            for i, e in enumerate(_seq(d["baseline_events"], f"{where}.baseline_events"))
        ),
        update_events=tuple(
            _parse_event(e, f"{where}.update_events[{i}]")
            for i, e in enumerate(_seq(d["update_events"], f"{where}.update_events"))
        ),
        system_output=_parse_system_output(d["system_output"], f"{where}.system_output"),
        seeded_issues=tuple(issues),
        reference_decision=ReferenceDecision(
            prompt=str(rd["prompt"]),
            options=tuple(options),
            concordant=tuple(str(x) for x in _seq(rd["concordant"], f"{where}.concordant")),
            acceptable=tuple(str(x) for x in _seq(rd.get("acceptable"), f"{where}.acceptable")),
        ),
        age_years=d.get("age_years"),
        stage=d.get("stage"),
        recall_distractors=tuple(
            str(x) for x in _seq(d.get("recall_distractors"), f"{where}.recall_distractors")
        ),
    )


def parse_case_set(raw: Any) -> CaseSet:
    d = _take(
        raw, "case set", ("set_id", "version", "review_status", "cases"), ("reviewed_by", "notes")
    )
    if not isinstance(d["version"], int) or isinstance(d["version"], bool):
        raise CaseSetError("case set.version: must be an integer")
    return CaseSet(
        set_id=str(d["set_id"]),
        version=d["version"],
        review_status=str(d["review_status"]),
        cases=tuple(_parse_case(c, f"cases[{i}]") for i, c in enumerate(_seq(d["cases"], "cases"))),
        reviewed_by=d.get("reviewed_by"),
        notes=d.get("notes"),
    )


def load_case_set(path: str | Path) -> CaseSet:
    with open(path, encoding="utf-8") as fh:
        return parse_case_set(yaml.safe_load(fh))


# --- validation --------------------------------------------------------------


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_case(case: StudyCase) -> list[str]:
    """Every semantic problem with one case; an empty list means consistent."""
    p = f"case {case.case_id}"
    errs: list[str] = []

    if not case.synthetic:
        errs.append(f"{p}: synthetic must be true (POLICY.md section 5: no real patient data)")

    baseline_ids = [e.id for e in case.baseline_events]
    update_ids = [e.id for e in case.update_events]
    if not case.update_events:
        errs.append(f"{p}: needs at least one update event -- there is nothing to review")
    all_events = case.baseline_events + case.update_events
    if len({e.id for e in all_events}) != len(all_events):
        errs.append(f"{p}: event ids are not unique")
    baseline_dates, update_dates = [], []
    for e in all_events:
        if e.event_type not in EVENT_TYPES:
            errs.append(f"{p}: event {e.id} has unknown event_type {e.event_type!r}")
        when = _parse_date(e.occurred_on)
        if when is None:
            errs.append(f"{p}: event {e.id} occurred_on {e.occurred_on!r} is not an ISO date")
        elif e.id in baseline_ids:
            baseline_dates.append(when)
        else:
            update_dates.append(when)
    if baseline_dates and update_dates and max(baseline_dates) >= min(update_dates):
        errs.append(f"{p}: every update event must be dated after every baseline event")

    findings = case.system_output.findings
    by_id = {f.id: f for f in findings}
    if len(by_id) != len(findings):
        errs.append(f"{p}: finding ids are not unique")
    if not findings:
        errs.append(f"{p}: needs at least one finding")

    for f in findings:
        fp = f"{p} finding {f.id}"
        if f.evidence_class not in STUDY_EVIDENCE_CLASSES:
            errs.append(f"{fp}: evidence_class must be one of {sorted(STUDY_EVIDENCE_CLASSES)}")
        elif f.evidence_class == "documented":
            if f.citation is None:
                errs.append(f"{fp}: a documented finding needs a citation (no citation, no item)")
            if f.method is not None:
                errs.append(f"{fp}: a documented finding must not carry a method")
        else:
            if not f.method:
                errs.append(f"{fp}: a computed finding needs a method")
            if f.citation is not None:
                errs.append(f"{fp}: a computed finding must not carry a citation")
        if f.valid:
            if f.invalidated_by is not None or f.flaw is not None:
                errs.append(f"{fp}: a valid finding cannot carry invalidated_by or flaw")
        else:
            if (f.invalidated_by is None) == (f.flaw is None):
                errs.append(f"{fp}: a flawed finding needs exactly one of invalidated_by or flaw")
        if f.invalidated_by is not None and f.invalidated_by not in update_ids:
            errs.append(f"{fp}: invalidated_by {f.invalidated_by!r} is not an update event")

    out = case.system_output
    superseded: dict[str, ReportedSupersession] = {}
    for s in out.reported_supersessions:
        sp = f"{p} supersession of {s.finding_id}"
        if s.finding_id in superseded:
            errs.append(f"{sp}: reported more than once")
        superseded[s.finding_id] = s
        if s.finding_id not in by_id:
            errs.append(f"{sp}: no such finding")
        elif by_id[s.finding_id].valid:
            errs.append(
                f"{sp}: supersedes a valid finding -- a false supersession is not a defined "
                "issue type in the protocol"
            )
        if s.triggering_event not in update_ids:
            errs.append(f"{sp}: triggering_event {s.triggering_event!r} is not an update event")
    for c in out.reported_changes:
        if c.triggering_event not in update_ids:
            errs.append(
                f"{p}: reported change triggered by non-update event {c.triggering_event!r}"
            )
    if len({q.id for q in out.questions}) != len(out.questions):
        errs.append(f"{p}: question ids are not unique")

    issue_targets: dict[str, SeededIssue] = {}
    if len({i.id for i in case.seeded_issues}) != len(case.seeded_issues):
        errs.append(f"{p}: seeded issue ids are not unique")
    for issue in case.seeded_issues:
        ip = f"{p} issue {issue.id}"
        if issue.type not in ISSUE_TYPES:
            errs.append(f"{ip}: type must be one of {list(ISSUE_TYPES)}")
        if issue.finding_id in issue_targets:
            errs.append(f"{ip}: finding {issue.finding_id} already has a seeded issue")
        issue_targets[issue.finding_id] = issue
        finding = by_id.get(issue.finding_id)
        if finding is None:
            errs.append(f"{ip}: no such finding {issue.finding_id!r}")
            continue
        if finding.valid:
            errs.append(f"{ip}: targets a finding whose ground truth is valid")
            continue
        is_superseded = issue.finding_id in superseded
        if issue.type == "change_visible":
            if finding.invalidated_by is None or not is_superseded:
                errs.append(
                    f"{ip}: change_visible needs invalidated_by set AND a reported supersession"
                )
            elif superseded[issue.finding_id].triggering_event != finding.invalidated_by:
                errs.append(
                    f"{ip}: reported supersession cites a different event than invalidated_by"
                )
        elif issue.type == "change_missed":
            if finding.invalidated_by is None or is_superseded:
                errs.append(
                    f"{ip}: change_missed needs invalidated_by set and NO reported supersession"
                )
        elif issue.type == "change_independent" and (finding.flaw is None or is_superseded):
            errs.append(f"{ip}: change_independent needs a flaw and NO reported supersession")

    flawed = {f.id for f in findings if not f.valid}
    for orphan in sorted(flawed - set(issue_targets)):
        errs.append(f"{p}: finding {orphan} is flawed in ground truth but has no seeded issue")

    real_changes = {e.summary.strip().lower() for e in all_events}
    seen_distractors: set[str] = set()
    for text in case.recall_distractors:
        key = text.strip().lower()
        if not key:
            errs.append(f"{p}: a recall distractor is empty")
        elif key in real_changes:
            errs.append(f"{p}: recall distractor {text!r} is actually an event in this case")
        elif key in seen_distractors:
            errs.append(f"{p}: recall distractor {text!r} is listed twice")
        seen_distractors.add(key)

    rd = case.reference_decision
    option_ids = [o.id for o in rd.options]
    if not option_ids or len(set(option_ids)) != len(option_ids):
        errs.append(f"{p}: reference decision needs unique, non-empty options")
    if not rd.concordant:
        errs.append(f"{p}: reference decision needs at least one concordant option")
    for oid in rd.concordant + rd.acceptable:
        if oid not in option_ids:
            errs.append(f"{p}: reference decision names unknown option {oid!r}")
    if set(rd.concordant) & set(rd.acceptable):
        errs.append(f"{p}: an option cannot be both concordant and acceptable")
    return errs


def validate_case_set(case_set: CaseSet) -> list[str]:
    errs: list[str] = []
    if case_set.review_status not in REVIEW_STATUSES:
        errs.append(f"review_status must be one of {sorted(REVIEW_STATUSES)}")
    if case_set.review_status == STUDY_ELIGIBLE_STATUS and not case_set.reviewed_by:
        errs.append("a clinician_reviewed set must name who reviewed it (reviewed_by)")
    if not case_set.cases:
        errs.append("case set has no cases")
    ids = [c.case_id for c in case_set.cases]
    if len(set(ids)) != len(ids):
        errs.append("case ids are not unique within the set")
    for case in case_set.cases:
        errs.extend(validate_case(case))
    return errs


# --- study eligibility, hashing, reporting ------------------------------------


def assert_eligible_for_study(case_set: CaseSet) -> None:
    """Raise unless this set may be run against real reviewers.

    Requires: no validation errors, `review_status: clinician_reviewed`, and
    every case's citations verified as real and supporting their claims.
    """
    reasons = validate_case_set(case_set)
    if case_set.review_status != STUDY_ELIGIBLE_STATUS:
        reasons.append(
            f"review_status is {case_set.review_status!r}, not {STUDY_ELIGIBLE_STATUS!r}"
        )
    for case in case_set.cases:
        if not case.citations_verified:
            reasons.append(f"case {case.case_id}: citations_verified is false")
    if reasons:
        raise IneligibleCaseSetError(reasons)


def content_hash(case_set: CaseSet) -> str:
    """Stable sha256 of the whole set's content, for the protocol's freeze step."""
    canonical = json.dumps(asdict(case_set), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prevalence(case_set: CaseSet) -> dict[str, int]:
    """Case and issue counts, so the mix can be checked against the protocol's target."""
    counts = {"cases": len(case_set.cases), "no_issue_controls": 0}
    counts.update({t: 0 for t in ISSUE_TYPES})
    for case in case_set.cases:
        if not case.seeded_issues:
            counts["no_issue_controls"] += 1
        for issue in case.seeded_issues:
            if issue.type in counts:
                counts[issue.type] += 1
    return counts
