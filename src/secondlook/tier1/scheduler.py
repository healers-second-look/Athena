"""Cron-style re-ingestion for the Evidence Graph Spine.

Subsystem A's first half. Deliberately a scheduled batch job rather than
streaming: the sources publish on a timescale of hours to months, so
event-driven infrastructure would cost real money to react no faster.

What it does per run:

1. Ask which sources are **due**, from `config/ingestion_schedule.yaml` and the
   recorded time of each source's last successful run.
2. Run each due loader.
3. Persist the new state -- but only for sources that actually succeeded, so a
   failed run is retried at the next tick instead of being silently skipped for
   a whole interval.

Cadence lives in config with a written reason per source, not in code. Polling
faster than upstream publishes buys nothing and costs requests.

Run:
    python -m secondlook.tier1.scheduler --once
    python -m secondlook.tier1.scheduler --once --source civic
    python -m secondlook.tier1.scheduler --once --force --dry-run
    python -m secondlook.tier1.scheduler --status

Install as a real cron entry (hourly tick; the interval logic decides what
actually runs):
    0 * * * * cd /path/to/Athena && python -m secondlook.tier1.scheduler --once
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "ingestion_schedule.yaml"
#: Beside the config rather than in /tmp: losing it silently re-runs every
#: loader, which is expensive and floods the change log with false events.
STATE_PATH = Path(__file__).parent / "config" / "ingestion_state.json"


class ScheduleConfigError(RuntimeError):
    """The schedule config is missing, unreadable, or malformed."""


@dataclass(frozen=True)
class SourceSchedule:
    name: str
    interval_hours: float
    reason: str
    enabled: bool = True

    def is_due(self, last_run: datetime | None, now: datetime) -> bool:
        """Never run before counts as due -- the first tick backfills."""
        if last_run is None:
            return True
        return now - last_run >= timedelta(hours=self.interval_hours)


@dataclass
class SourceRun:
    """One source's outcome in one scheduler tick."""

    name: str
    ran: bool
    #: False only when the loader raised. A run that legitimately found nothing
    #: new is a success.
    ok: bool = True
    skipped_reason: str | None = None
    error: str | None = None
    detail: Any = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class SchedulerReport:
    runs: list[SourceRun] = field(default_factory=list)

    @property
    def ran(self) -> list[SourceRun]:
        return [r for r in self.runs if r.ran]

    @property
    def failed(self) -> list[SourceRun]:
        return [r for r in self.runs if r.ran and not r.ok]

    @property
    def ok(self) -> bool:
        return not self.failed

    def render(self) -> str:
        lines = []
        for run in self.runs:
            if not run.ran:
                lines.append(f"  {run.name:<16} skipped   ({run.skipped_reason})")
            elif run.ok:
                lines.append(f"  {run.name:<16} ok        {run.detail or ''}")
            else:
                lines.append(f"  {run.name:<16} FAILED    {run.error}")
        if not lines:
            lines.append("  (no sources configured)")
        return "\n".join(lines)


def load_schedule(path: Path = CONFIG_PATH) -> list[SourceSchedule]:
    if not path.exists():
        raise ScheduleConfigError(f"schedule config not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ScheduleConfigError(f"could not parse {path}: {exc}") from exc

    sources = raw.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ScheduleConfigError(f"{path} declares no sources")

    schedules: list[SourceSchedule] = []
    for name, entry in sources.items():
        if not isinstance(entry, dict):
            raise ScheduleConfigError(f"{path}: source {name!r} is not a mapping")
        interval = entry.get("interval_hours")
        if not isinstance(interval, (int, float)) or interval <= 0:
            raise ScheduleConfigError(
                f"{path}: source {name!r} needs a positive interval_hours, got {interval!r}"
            )
        # A cadence without a stated reason is a number nobody can review later.
        reason = entry.get("reason")
        if not reason:
            raise ScheduleConfigError(
                f"{path}: source {name!r} must state a `reason` for its interval"
            )
        schedules.append(
            SourceSchedule(
                name=str(name),
                interval_hours=float(interval),
                reason=str(reason),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return schedules


def load_state(path: Path = STATE_PATH) -> dict[str, datetime]:
    """Last *successful* run per source. Unreadable state is treated as empty.

    Refusing to run because a state file is corrupt would be worse than
    re-running: re-running is merely expensive, while not running means the
    graph silently stops updating.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("ignoring unreadable scheduler state %s: %s", path, exc)
        return {}
    state: dict[str, datetime] = {}
    for name, stamp in (raw.get("last_success") or {}).items():
        try:
            state[str(name)] = datetime.fromisoformat(str(stamp))
        except ValueError:
            logger.warning("ignoring unparseable timestamp for %s: %r", name, stamp)
    return state


def save_state(state: dict[str, datetime], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "config_version_note": "written by scheduler.py; safe to delete to force a full re-run",
        "last_success": {name: stamp.isoformat() for name, stamp in sorted(state.items())},
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


#: name -> callable(graph, dry_run) -> detail. Imported lazily inside each
#: entry so that a missing optional dependency for one source cannot stop the
#: scheduler from running the others.
LoaderFn = Callable[..., Any]


def _civic_loader(graph, *, dry_run: bool):
    from secondlook.tier1.civic_loader import run_load

    return run_load(graph, dry_run=dry_run)


def _pubmed_loader(graph, *, dry_run: bool):
    from secondlook.tier1.pubmed_loader import run_load

    return run_load(graph, dry_run=dry_run)


def _ctgov_loader(graph, *, dry_run: bool):
    from secondlook.tier1.ctgov_loader import run_load

    return run_load(graph, dry_run=dry_run)


LOADERS: dict[str, LoaderFn] = {
    "civic": _civic_loader,
    "pubmed": _pubmed_loader,
    "clinicaltrials": _ctgov_loader,
    # "ctri" is intentionally absent: its access mode is unverified, and the
    # config disables it. A missing entry is reported as a skip with a reason
    # rather than crashing the tick.
}


def run_due(
    graph,
    *,
    schedules: list[SourceSchedule] | None = None,
    state: dict[str, datetime] | None = None,
    now: datetime | None = None,
    only: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    loaders: dict[str, LoaderFn] | None = None,
) -> tuple[SchedulerReport, dict[str, datetime]]:
    """Run every due source once. Returns the report and the updated state.

    State is returned rather than written so the caller decides whether a
    dry run should be allowed to advance the clock. It must not.
    """
    schedules = schedules if schedules is not None else load_schedule()
    state = dict(state if state is not None else load_state())
    now = now or datetime.now(UTC)
    loaders = loaders if loaders is not None else LOADERS

    report = SchedulerReport()
    for schedule in schedules:
        if only and schedule.name != only:
            continue
        if not schedule.enabled:
            report.runs.append(
                SourceRun(schedule.name, ran=False, skipped_reason="disabled in config")
            )
            continue
        if not force and not schedule.is_due(state.get(schedule.name), now):
            last = state[schedule.name]
            due_at = last + timedelta(hours=schedule.interval_hours)
            report.runs.append(
                SourceRun(
                    schedule.name,
                    ran=False,
                    skipped_reason=f"not due until {due_at.isoformat(timespec='minutes')}",
                )
            )
            continue

        loader = loaders.get(schedule.name)
        if loader is None:
            report.runs.append(
                SourceRun(
                    schedule.name,
                    ran=False,
                    skipped_reason="no loader registered for this source",
                )
            )
            continue

        started = datetime.now(UTC)
        try:
            detail = loader(graph, dry_run=dry_run)
        # Every loader documents its own failure type; catching the module's
        # error base plus the transport errors keeps one source's outage from
        # ending the tick for the others.
        except Exception as exc:  # noqa: BLE001 - see below
            # BLE001 is suppressed here deliberately and nowhere else in this
            # module. The scheduler's whole purpose is that one source failing
            # must not stop the rest, and it cannot enumerate the exception
            # types of loaders it imports lazily. The error is recorded in full
            # and surfaced in the report, never swallowed.
            logger.exception("source %s failed", schedule.name)
            report.runs.append(
                SourceRun(
                    schedule.name,
                    ran=True,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                    started_at=started.isoformat(),
                    finished_at=datetime.now(UTC).isoformat(),
                )
            )
            continue

        report.runs.append(
            SourceRun(
                schedule.name,
                ran=True,
                ok=True,
                detail=detail,
                started_at=started.isoformat(),
                finished_at=datetime.now(UTC).isoformat(),
            )
        )
        # Only successful, non-dry runs advance the clock.
        if not dry_run:
            state[schedule.name] = now

    return report, state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one tick and exit")
    parser.add_argument("--status", action="store_true", help="show cadence and due times")
    parser.add_argument("--source", help="limit to one source name")
    parser.add_argument("--force", action="store_true", help="run even if not due")
    parser.add_argument("--dry-run", action="store_true", help="do not write, do not advance state")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    schedules = load_schedule()
    state = load_state()

    if args.status or not args.once:
        now = datetime.now(UTC)
        print(f"{'source':<16}{'every':<12}{'last success':<28}{'due'}")
        print("-" * 78)
        for schedule in schedules:
            last = state.get(schedule.name)
            last_text = last.isoformat(timespec="minutes") if last else "never"
            if not schedule.enabled:
                due = "disabled"
            elif schedule.is_due(last, now):
                due = "DUE NOW"
            else:
                due = (last + timedelta(hours=schedule.interval_hours)).isoformat(
                    timespec="minutes"
                )
            print(f"{schedule.name:<16}{schedule.interval_hours:>6.0f}h    {last_text:<28}{due}")
            print(f"{'':<16}{schedule.reason}")
        if not args.once:
            return 0

    from secondlook.tier1.graph_connection import connect_graph

    graph = connect_graph()
    report, new_state = run_due(
        graph,
        schedules=schedules,
        state=state,
        only=args.source,
        force=args.force,
        dry_run=args.dry_run,
    )
    print("\n" + report.render())
    if not args.dry_run:
        save_state(new_state)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
