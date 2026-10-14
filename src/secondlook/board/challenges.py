"""Structured Challenge & Disagreement Ledger.

Subsystem X (Issue #79, P1).

Disagreement is the primary clinical product of the multi-agent tumor board;
it must have a durable, queryable home, not be a transient render artifact.

Rules from Part I §4:
1. Every challenge must be one of five typed categories:
   - contradiction: "My evidence says the opposite"
   - jurisdiction:  "This claim is outside the claiming role's charter"
   - precondition:   "True in general, but a constraint in my lane forecloses it"
   - staleness:      "Superseded by a newer instrument/label/guideline in my KG"
   - identity:       "The entities referenced do not resolve to the same anchor"
2. Every challenge MUST carry a citation from the challenger's own KG.
3. Challenges cannot be withdrawn by another role; their default resolution
   status is `unresolved`, and may remain unresolved forever.
4. Ledger provides queryable auditing and per-lane challenge rate tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ChallengeType(StrEnum):
    """The 5 canonical challenge types from Part I §4."""

    CONTRADICTION = "contradiction"
    JURISDICTION = "jurisdiction"
    PRECONDITION = "precondition"
    STALENESS = "staleness"
    IDENTITY = "identity"


class ChallengeStatus(StrEnum):
    """Resolution status of a challenge."""

    UNRESOLVED = "unresolved"
    UPHELD = "upheld"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ChallengeCitationMissingError(ValueError):
    """Raised when a challenge is filed without a mandatory citation from the challenger's KG."""


@dataclass(frozen=True)
class Challenge:
    """An immutable, typed challenge filed against a specific target finding."""

    challenge_id: str
    challenger_role: str
    target_role: str
    target_finding_id: str
    challenge_type: ChallengeType
    rationale: str
    citation: str
    citation_url: str | None = None
    supporting_node_id: str | None = None
    status: ChallengeStatus = ChallengeStatus.UNRESOLVED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.challenge_id:
            raise ValueError("challenge_id cannot be empty")
        if not self.challenger_role:
            raise ValueError("challenger_role cannot be empty")
        if not self.target_role:
            raise ValueError("target_role cannot be empty")
        if not self.target_finding_id:
            raise ValueError("target_finding_id cannot be empty")
        if not self.rationale or not self.rationale.strip():
            raise ValueError("Challenge rationale cannot be blank")

        # Invariant 2: A challenge MUST carry a citation from the challenger's KG
        if not self.citation or not self.citation.strip():
            raise ChallengeCitationMissingError(
                f"Challenge '{self.challenge_id}' filed by '{self.challenger_role}' "
                f"must carry a citation from the challenger's own KG"
            )

        # Invariant: A role cannot challenge its own finding
        if self.challenger_role == self.target_role:
            raise ValueError(
                f"Role '{self.challenger_role}' cannot file a challenge against its own finding"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "challenger_role": self.challenger_role,
            "target_role": self.target_role,
            "target_finding_id": self.target_finding_id,
            "challenge_type": self.challenge_type.value,
            "rationale": self.rationale,
            "citation": self.citation,
            "citation_url": self.citation_url,
            "supporting_node_id": self.supporting_node_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Challenge:
        return cls(
            challenge_id=data["challenge_id"],
            challenger_role=data["challenger_role"],
            target_role=data["target_role"],
            target_finding_id=data["target_finding_id"],
            challenge_type=ChallengeType(data["challenge_type"]),
            rationale=data["rationale"],
            citation=data["citation"],
            citation_url=data.get("citation_url"),
            supporting_node_id=data.get("supporting_node_id"),
            status=ChallengeStatus(data.get("status", ChallengeStatus.UNRESOLVED.value)),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


class DisagreementLedger:
    """Durable, queryable home for structured board challenges."""

    def __init__(self, challenges: list[Challenge] | None = None) -> None:
        self._challenges: list[Challenge] = list(challenges or [])

    def add_challenge(self, challenge: Challenge) -> None:
        self._challenges.append(challenge)

    def all_challenges(self) -> tuple[Challenge, ...]:
        return tuple(self._challenges)

    def get_challenges_for_finding(self, finding_id: str) -> tuple[Challenge, ...]:
        return tuple(c for c in self._challenges if c.target_finding_id == finding_id)

    def get_challenges_by_challenger(self, role_id: str) -> tuple[Challenge, ...]:
        return tuple(c for c in self._challenges if c.challenger_role == role_id)

    def get_challenges_by_target_role(self, role_id: str) -> tuple[Challenge, ...]:
        return tuple(c for c in self._challenges if c.target_role == role_id)

    def get_unresolved(self) -> tuple[Challenge, ...]:
        return tuple(c for c in self._challenges if c.status == ChallengeStatus.UNRESOLVED)

    def filter(
        self,
        challenge_type: ChallengeType | None = None,
        status: ChallengeStatus | None = None,
    ) -> tuple[Challenge, ...]:
        results = self._challenges
        if challenge_type is not None:
            results = [c for c in results if c.challenge_type == challenge_type]
        if status is not None:
            results = [c for c in results if c.status == status]
        return tuple(results)

    def challenge_rate_per_lane(
        self, active_roles: tuple[str, ...] | list[str]
    ) -> dict[str, float]:
        """Calculates challenge metrics per role.

        Eval hook from §4: tracks challenge filing rate per lane.
        """
        role_set = set(active_roles)
        total_challenges = len(self._challenges)
        rates: dict[str, float] = {}

        for role in role_set:
            count = sum(1 for c in self._challenges if c.challenger_role == role)
            rates[role] = count / total_challenges if total_challenges > 0 else 0.0

        return rates

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenges": [c.to_dict() for c in self._challenges],
            "total_count": len(self._challenges),
            "unresolved_count": len(self.get_unresolved()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DisagreementLedger:
        challenges = [Challenge.from_dict(c) for c in data.get("challenges", [])]
        return cls(challenges)
