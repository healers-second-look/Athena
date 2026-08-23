"""Scheduler: cadence, isolation between sources, and state advancement."""

from datetime import UTC, datetime, timedelta

import pytest
import yaml

from secondlook.tier1.scheduler import (
    ScheduleConfigError,
    SourceSchedule,
    load_schedule,
    load_state,
    run_due,
    save_state,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def schedule(name="civic", hours=24.0, enabled=True):
    return SourceSchedule(name=name, interval_hours=hours, reason="test", enabled=enabled)


class TestDueLogic:
    def test_never_run_is_due(self):
        """First tick backfills rather than waiting a full interval."""
        assert schedule().is_due(None, NOW)

    def test_not_due_before_the_interval_elapses(self):
        assert not schedule(hours=24).is_due(NOW - timedelta(hours=23), NOW)

    def test_due_once_the_interval_elapses(self):
        assert schedule(hours=24).is_due(NOW - timedelta(hours=24), NOW)


class TestConfig:
    def test_interval_without_a_reason_is_rejected(self, tmp_path):
        """A cadence with no stated reason is a number nobody can review later."""
        path = tmp_path / "s.yaml"
        path.write_text(yaml.safe_dump({"sources": {"civic": {"interval_hours": 24}}}))
        with pytest.raises(ScheduleConfigError, match="reason"):
            load_schedule(path)

    def test_non_positive_interval_is_rejected(self, tmp_path):
        path = tmp_path / "s.yaml"
        path.write_text(
            yaml.safe_dump({"sources": {"civic": {"interval_hours": 0, "reason": "x"}}})
        )
        with pytest.raises(ScheduleConfigError, match="positive"):
            load_schedule(path)

    def test_shipped_config_parses_and_every_source_states_a_reason(self):
        for source in load_schedule():
            assert source.reason.strip()
            assert source.interval_hours > 0


class TestRunDue:
    def test_runs_a_due_source_and_advances_state(self):
        calls = []
        report, state = run_due(
            None,
            schedules=[schedule()],
            state={},
            now=NOW,
            loaders={"civic": lambda g, dry_run: calls.append("civic") or "ok"},
        )
        assert calls == ["civic"]
        assert report.ok
        assert state["civic"] == NOW

    def test_skips_a_source_that_is_not_due(self):
        calls = []
        report, _ = run_due(
            None,
            schedules=[schedule(hours=168)],
            state={"civic": NOW - timedelta(hours=1)},
            now=NOW,
            loaders={"civic": lambda g, dry_run: calls.append("x")},
        )
        assert calls == []
        assert "not due" in report.runs[0].skipped_reason

    def test_force_overrides_the_interval(self):
        calls = []
        run_due(
            None,
            schedules=[schedule(hours=168)],
            state={"civic": NOW},
            now=NOW,
            force=True,
            loaders={"civic": lambda g, dry_run: calls.append("x")},
        )
        assert calls == ["x"]

    def test_disabled_source_is_skipped_with_a_reason(self):
        report, _ = run_due(
            None,
            schedules=[schedule(name="ctri", enabled=False)],
            state={},
            now=NOW,
            loaders={"ctri": lambda g, dry_run: 1 / 0},
        )
        assert report.runs[0].skipped_reason == "disabled in config"

    def test_a_source_with_no_registered_loader_is_reported_not_crashed(self):
        report, _ = run_due(None, schedules=[schedule(name="ctri")], state={}, now=NOW, loaders={})
        assert "no loader registered" in report.runs[0].skipped_reason

    def test_one_source_failing_does_not_stop_the_others(self):
        """The scheduler's whole purpose: an upstream outage must not take the
        rest of the ingestion down with it."""
        ran = []

        def boom(graph, dry_run):
            raise RuntimeError("CIViC is down")

        report, state = run_due(
            None,
            schedules=[schedule(name="civic"), schedule(name="pubmed")],
            state={},
            now=NOW,
            loaders={"civic": boom, "pubmed": lambda g, dry_run: ran.append("pubmed")},
        )
        assert ran == ["pubmed"]
        assert not report.ok
        assert [r.name for r in report.failed] == ["civic"]
        # The failed source must NOT advance, so it retries next tick...
        assert "civic" not in state
        # ...while the one that worked does.
        assert state["pubmed"] == NOW

    def test_the_error_is_recorded_not_swallowed(self):
        report, _ = run_due(
            None,
            schedules=[schedule()],
            state={},
            now=NOW,
            loaders={"civic": lambda g, dry_run: (_ for _ in ()).throw(ValueError("bad json"))},
        )
        assert "ValueError" in report.failed[0].error
        assert "bad json" in report.failed[0].error

    def test_dry_run_does_not_advance_the_clock(self):
        """Otherwise a dry run would suppress the next real run."""
        _, state = run_due(
            None,
            schedules=[schedule()],
            state={},
            now=NOW,
            dry_run=True,
            loaders={"civic": lambda g, dry_run: None},
        )
        assert state == {}

    def test_only_limits_to_one_source(self):
        ran = []
        run_due(
            None,
            schedules=[schedule("civic"), schedule("pubmed")],
            state={},
            now=NOW,
            only="pubmed",
            loaders={
                "civic": lambda g, dry_run: ran.append("civic"),
                "pubmed": lambda g, dry_run: ran.append("pubmed"),
            },
        )
        assert ran == ["pubmed"]


class TestState:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "state.json"
        save_state({"civic": NOW}, path)
        assert load_state(path)["civic"] == NOW

    def test_corrupt_state_is_treated_as_empty_not_fatal(self, tmp_path):
        """Re-running is merely expensive; refusing to run means the graph
        silently stops updating."""
        path = tmp_path / "state.json"
        path.write_text("{not json")
        assert load_state(path) == {}

    def test_unparseable_timestamp_is_dropped_not_fatal(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(
            '{"last_success": {"civic": "never",' ' "pubmed": "2026-08-23T12:00:00+00:00"}}'
        )
        state = load_state(path)
        assert "civic" not in state
        assert state["pubmed"] == NOW
