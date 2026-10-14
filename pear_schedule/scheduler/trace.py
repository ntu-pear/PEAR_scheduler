"""
Decision trace for schedule generation.

Stages call record() with an outcome and a reason, it does nothing unless a
trace is active. build_schedules also snapshots after each stage so every slot
knows which stage wrote it.
"""

import contextvars
import copy
import logging
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# outcomes
PLACED = "PLACED"
SKIPPED = "SKIPPED"
MOVED = "MOVED"
REPLACED = "REPLACED"
DROPPED = "DROPPED"
FILTERED = "FILTERED"
FREE_AND_EASY = "FREE_AND_EASY"
ERROR = "ERROR"

# stages, in pipeline order
STAGE_COMPULSORY = "compulsory"
STAGE_RECOMMENDED = "recommended_routine"
STAGE_GROUP = "group"
STAGE_PREFERRED = "preferred"
STAGE_ADHOC = "adhoc"
STAGE_MEDICATION = "medication"


@dataclass
class TraceEvent:
    stage: str
    patient_id: Any
    outcome: str
    reason: str
    activity: Optional[str] = None
    day: Optional[int] = None
    slot: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SlotWrite:
    stage: str
    activity: str
    previous: str


class ScheduleTrace:
    def __init__(self):
        self.events: List[TraceEvent] = []
        # (patient_id, day, slot) -> writes in stage order
        self.provenance: Dict[Tuple[Any, int, int], List[SlotWrite]] = {}
        self._snapshot = None

    def add(self, event: TraceEvent) -> None:
        self.events.append(event)

    def events_for(self, patient_id) -> List[TraceEvent]:
        return [e for e in self.events if e.patient_id == patient_id]

    def provenance_for(self, patient_id) -> Dict[Tuple[int, int], List[SlotWrite]]:
        return {(d, s): w for (pid, d, s), w in self.provenance.items() if pid == patient_id}

    def start_snapshot(self, schedules) -> None:
        self._snapshot = copy.deepcopy(dict(schedules))

    def end_stage(self, stage: str, schedules) -> None:
        """Records what this stage wrote, by diffing against the last snapshot."""
        before = self._snapshot or {}
        for pid, days in schedules.items():
            old_days = before.get(pid)
            for d, day in enumerate(days):
                for s, activity in enumerate(day):
                    prev = old_days[d][s] if old_days and d < len(old_days) and s < len(old_days[d]) else ""
                    if activity != prev:
                        self.provenance.setdefault((pid, d, s), []).append(SlotWrite(stage, activity, prev))
        self._snapshot = copy.deepcopy(dict(schedules))

    def summary(self) -> Dict[str, Any]:
        by_outcome = Counter((e.stage, e.outcome) for e in self.events)
        by_reason = Counter((e.stage, e.outcome, e.reason) for e in self.events)
        return {
            "events": len(self.events),
            "by_outcome": {f"{s}:{o}": n for (s, o), n in sorted(by_outcome.items())},
            "by_reason": {f"{s}:{o}:{r}": n for (s, o, r), n in sorted(by_reason.items())},
        }

    def notable(self) -> List[TraceEvent]:
        """Dropped or errored events, worth logging at INFO."""
        return [e for e in self.events if e.outcome in (DROPPED, ERROR)]

    def log_summary(self, log: logging.Logger = logger) -> None:
        summary = self.summary()
        log.info(f"Schedule trace summary: {summary['by_outcome']}")
        for e in self.notable():
            log.info(
                f"[{e.stage}] {e.outcome} {e.reason}: patient={e.patient_id} activity={e.activity!r} "
                f"day={e.day} slot={e.slot} {e.details or ''}"
            )
        for e in self.events:
            log.debug(f"[{e.stage}] {e.outcome} {e.reason}: {e.to_dict()}")


_current: contextvars.ContextVar[Optional[ScheduleTrace]] = contextvars.ContextVar("schedule_trace", default=None)


def current() -> Optional[ScheduleTrace]:
    return _current.get()


@contextmanager
def tracing(trace: Optional[ScheduleTrace] = None):
    trace = trace or ScheduleTrace()
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


def record(stage: str, patient_id, outcome: str, reason: str, activity: Optional[str] = None,
           day: Optional[int] = None, slot: Optional[int] = None, **details) -> None:
    trace = _current.get()
    if trace is None:
        return
    trace.add(TraceEvent(stage, patient_id, outcome, reason, activity, day, slot, details))
