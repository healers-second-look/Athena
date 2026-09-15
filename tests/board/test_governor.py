"""Tests for Subsystem AE (Cost & Latency Governor)."""

import pytest

from secondlook.board.governor import (
    BoardGovernor,
    GovernorConfig,
    GovernorLimitExceededError,
)


def test_governor_tracks_usage_and_stays_healthy() -> None:
    config = GovernorConfig(
        max_case_tokens=10_000,
        per_role_token_limit=3_000,
        per_role_timeout_ms=5_000.0,
    )
    governor = BoardGovernor(config)

    ok = governor.record_usage(
        role_id="medical_oncologist",
        tokens_used=1_200,
        duration_ms=1_500.0,
    )
    assert ok is True
    assert governor.is_degraded("medical_oncologist") is False
    assert governor.state.total_tokens_consumed == 1_200
    assert governor.state.tokens_by_role["medical_oncologist"] == 1_200
    assert governor.state.latency_ms_by_role["medical_oncologist"] == 1_500.0


def test_governor_degrades_on_latency_breach() -> None:
    config = GovernorConfig(per_role_timeout_ms=2_000.0, allow_graceful_degrade=True)
    governor = BoardGovernor(config)

    ok = governor.record_usage(
        role_id="clinical_pharmacologist",
        tokens_used=500,
        duration_ms=3_500.0,  # Exceeds 2000ms
    )
    assert ok is False
    assert governor.is_degraded("clinical_pharmacologist") is True


def test_governor_degrades_on_token_limit_breach() -> None:
    config = GovernorConfig(per_role_token_limit=1_000, allow_graceful_degrade=True)
    governor = BoardGovernor(config)

    ok = governor.record_usage(
        role_id="molecular_pathologist",
        tokens_used=1_500,
        duration_ms=500.0,
    )
    assert ok is False
    assert governor.is_degraded("molecular_pathologist") is True


def test_governor_degrades_on_case_token_limit_breach() -> None:
    config = GovernorConfig(
        max_case_tokens=2_000,
        per_role_token_limit=5_000,
        allow_graceful_degrade=True,
    )
    governor = BoardGovernor(config)

    governor.record_usage("role_a", tokens_used=1_500, duration_ms=200.0)
    ok_b = governor.record_usage("role_b", tokens_used=800, duration_ms=200.0)
    assert ok_b is False
    assert governor.is_degraded("role_b") is True


def test_governor_raises_when_graceful_degrade_disabled() -> None:
    config = GovernorConfig(
        per_role_timeout_ms=1_000.0,
        allow_graceful_degrade=False,
    )
    governor = BoardGovernor(config)

    with pytest.raises(GovernorLimitExceededError, match="Governor halted session"):
        governor.record_usage(
            role_id="chair",
            tokens_used=100,
            duration_ms=2_000.0,
        )
