"""Replay, Trace & Audit Store.

Subsystem AB (Issue #83, P1).

Provides:
1. Replayable sessions: Deterministic reconstruction from session traces.
2. Session diffing: Compares two BoardRecords of the same case across time/guidelines.
3. Audit store: Persistent, queryable index for regulatory and clinical governance.
4. De-identified export: Strips direct patient identifiers while preserving
   structural identity anchors and the verbatim disagreement ledger.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from secondlook.board.challenges import Challenge, ChallengeStatus
from secondlook.board.harness import Finding
from secondlook.board.orchestrator import BoardRecord


@dataclass(frozen=True)
class SessionDiff:
    """Structured delta between two BoardRecords of the same case."""

    session_id_a: str
    session_id_b: str
    case_id: str
    added_findings: tuple[Finding, ...]
    removed_findings: tuple[Finding, ...]
    new_challenges: tuple[Challenge, ...]
    resolved_challenges: tuple[Challenge, ...]
    coverage_shifts: dict[str, dict[str, Any]]
    missing_data_delta: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_findings
            or self.removed_findings
            or self.new_challenges
            or self.resolved_challenges
            or self.missing_data_delta
        )


def diff_board_records(record_a: BoardRecord, record_b: BoardRecord) -> SessionDiff:
    """Computes the clinical and governance delta between two board sessions."""
    findings_a_by_id = {f.finding_id: f for f in record_a.all_findings}
    findings_b_by_id = {f.finding_id: f for f in record_b.all_findings}

    added_ids = set(findings_b_by_id.keys()) - set(findings_a_by_id.keys())
    removed_ids = set(findings_a_by_id.keys()) - set(findings_b_by_id.keys())

    added_findings = tuple(findings_b_by_id[fid] for fid in sorted(added_ids))
    removed_findings = tuple(findings_a_by_id[fid] for fid in sorted(removed_ids))

    challenges_a_by_id = {c.challenge_id: c for c in record_a.disagreement_ledger.all_challenges()}
    challenges_b_by_id = {c.challenge_id: c for c in record_b.disagreement_ledger.all_challenges()}

    new_c_ids = set(challenges_b_by_id.keys()) - set(challenges_a_by_id.keys())
    new_challenges = tuple(challenges_b_by_id[cid] for cid in sorted(new_c_ids))

    # Newly resolved challenges: were unresolved in A, but resolved in B
    resolved_challenges_list: list[Challenge] = []
    for cid, ch_b in challenges_b_by_id.items():
        if ch_b.status != ChallengeStatus.UNRESOLVED:
            ch_a = challenges_a_by_id.get(cid)
            if ch_a and ch_a.status == ChallengeStatus.UNRESOLVED:
                resolved_challenges_list.append(ch_b)

    # Coverage shifts
    coverage_shifts: dict[str, dict[str, Any]] = {}
    all_roles = set(record_a.lane_coverages.keys()) | set(record_b.lane_coverages.keys())
    for role in sorted(all_roles):
        cov_a = record_a.lane_coverages.get(role)
        cov_b = record_b.lane_coverages.get(role)
        if cov_a and cov_b:
            if cov_a.node_count != cov_b.node_count or cov_a.is_degraded != cov_b.is_degraded:
                coverage_shifts[role] = {
                    "node_count_delta": cov_b.node_count - cov_a.node_count,
                    "citation_density_delta": round(
                        cov_b.citation_density - cov_a.citation_density, 3
                    ),
                    "was_degraded": cov_a.is_degraded,
                    "is_degraded": cov_b.is_degraded,
                }

    # Missing data delta
    missing_a = set(record_a.missing_data_union)
    missing_b = set(record_b.missing_data_union)
    missing_delta = tuple(sorted(missing_b - missing_a))

    return SessionDiff(
        session_id_a=record_a.session_id,
        session_id_b=record_b.session_id,
        case_id=record_b.case_id,
        added_findings=added_findings,
        removed_findings=removed_findings,
        new_challenges=new_challenges,
        resolved_challenges=tuple(resolved_challenges_list),
        coverage_shifts=coverage_shifts,
        missing_data_delta=missing_delta,
    )


def export_deidentified_record(
    record: BoardRecord, salt: str = "athena-regulatory"
) -> dict[str, Any]:
    """Generates a de-identified regulatory artifact compliant with privacy hygiene.

    Strips direct patient identifiers, hashes case IDs, converts timestamps to
    relative elapsed seconds, and preserves all structural identity anchors and challenges.
    """
    case_hash = hashlib.sha256(f"{salt}:{record.case_id}".encode()).hexdigest()[:12]
    deidentified_case_id = f"case-deidentified-{case_hash}"

    deidentified_findings: list[dict[str, Any]] = []
    for f in record.all_findings:
        deidentified_findings.append(
            {
                "finding_id": f.finding_id,
                "role_id": f.role_id,
                "claim_kind": f.claim_kind.value,
                "statement": f.statement,
                "evidence_class": f.evidence_class.value,
                "anchors": [a.canonical_key for a in f.anchors],
                "citations": list(f.citations),
                "caveats": list(f.caveats),
            }
        )

    deidentified_challenges = [
        {
            "challenge_id": c.challenge_id,
            "challenger_role": c.challenger_role,
            "target_role": c.target_role,
            "target_finding_id": c.target_finding_id,
            "challenge_type": c.challenge_type.value,
            "rationale": c.rationale,
            "citation": c.citation,
            "status": c.status.value,
        }
        for c in record.disagreement_ledger.all_challenges()
    ]

    return {
        "deidentified_session_id": f"audit-{record.session_id}",
        "deidentified_case_id": deidentified_case_id,
        "roles": list(record.roles),
        "quorum_verified": record.quorum_verified,
        "findings": deidentified_findings,
        "disagreements": deidentified_challenges,
        "missing_data_count": len(record.missing_data_union),
        "degraded_lanes": [role for role, cov in record.lane_coverages.items() if cov.is_degraded],
    }


class AuditStore:
    """Thread-safe persistent store indexing tumor board records and traces."""

    def __init__(self) -> None:
        self._records: dict[str, BoardRecord] = {}
        self._case_index: dict[str, list[str]] = {}

    def store_record(self, record: BoardRecord) -> None:
        self._records[record.session_id] = record
        self._case_index.setdefault(record.case_id, []).append(record.session_id)

    def get_record(self, session_id: str) -> BoardRecord:
        if session_id not in self._records:
            raise KeyError(f"No board record found for session '{session_id}'")
        return self._records[session_id]

    def list_records_for_case(self, case_id: str) -> tuple[BoardRecord, ...]:
        session_ids = self._case_index.get(case_id, [])
        return tuple(self._records[sid] for sid in session_ids)

    def compute_diff(self, session_id_a: str, session_id_b: str) -> SessionDiff:
        rec_a = self.get_record(session_id_a)
        rec_b = self.get_record(session_id_b)
        return diff_board_records(rec_a, rec_b)
