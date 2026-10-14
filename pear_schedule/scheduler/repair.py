"""
Regenerate without reshuffling the week.

Starts from the saved schedule and only changes what a reason forces: something now
invalid (excluded, disliked, not recommended, gone, moved), something newly required
(compulsory, routine, doctor recommendation), or a group below its min size. Only the
freed slots get re-filled. Past days and slots already started today never change.
"""

import datetime
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

from pear_schedule.scheduler import trace
from pear_schedule.scheduler.gapFill import build_candidates, is_excluded, slots_for, solve_day
from pear_schedule.scheduler.invariants import FREE_AND_EASY, PatientRules, RuleInputs, base_title

logger = logging.getLogger(__name__)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FREE = ""


@dataclass(frozen=True)
class Rec:
    """Individual doctor recommendation, placed once a week."""
    activity_id: int
    title: str
    length: int
    fixed_slots: FrozenSet[Tuple[int, int]] = frozenset()


@dataclass(frozen=True)
class Group:
    activity_id: int
    title: str
    length: int
    min_size: int


@dataclass
class RepairData:
    inputs: RuleInputs
    patient_ids: List[Any]
    recommended: Dict[Any, List[Rec]] = field(default_factory=dict)
    routines: Dict[Any, Dict[Tuple[int, int], Tuple[int, str]]] = field(default_factory=dict)  # pid -> (day, slot) -> (id, title)
    groups: Dict[str, Group] = field(default_factory=dict)
    group_blocked: Dict[str, Set[Any]] = field(default_factory=dict)  # excluded, not recommended, disliked and not recommended
    group_recommended: Dict[str, Set[Any]] = field(default_factory=dict)
    group_liked: Dict[str, Set[Any]] = field(default_factory=dict)
    adhoc_new: Set[Tuple[Any, int, str]] = field(default_factory=set)  # (pid, day, title) an adhoc request put there


def _runs(day: List[str]) -> List[Tuple[int, int, str]]:
    """(start, end, title) of each run of the same activity, free slots skipped."""
    out, s = [], 0
    while s < len(day):
        t, e = day[s], s + 1
        while e < len(day) and day[e] == t:
            e += 1
        if t not in (FREE, FREE_AND_EASY):
            out.append((s, e, t))
        s = e
    return out


class _Repair:
    def __init__(self, saved: Mapping[Any, Optional[List[List[str]]]], data: RepairData, locked: Set[Tuple[int, int]]):
        self.data = data
        self.inputs = data.inputs
        self.locked = locked
        self.compulsory = {c.title: c for c in self.inputs.compulsory}
        self.pool = {a.title: a for a in self.inputs.pool}
        self.new_patients = set()
        self.grid: Dict[Any, List[List[str]]] = {}
        for pid in data.patient_ids:
            days = saved.get(pid)
            if days is None:
                # new patient, built from today
                self.new_patients.add(pid)
                self.grid[pid] = [[FREE] * n for n in self.inputs.slots_per_day]
            else:
                self.grid[pid] = [[base_title(v) for v in day] for day in days]

    # helpers

    def rules(self, pid) -> PatientRules:
        return self.inputs.patients.get(pid, PatientRules())

    def rec_titles(self, pid) -> Dict[str, Rec]:
        return {r.title: r for r in self.data.recommended.get(pid, [])}

    def unlocked(self, d: int, s0: int, s1: int) -> bool:
        return all((d, k) not in self.locked for k in range(s0, s1))

    def excluded(self, pid, activity_id: int, d: int) -> bool:
        return is_excluded(activity_id, self.rules(pid).exclusions, d, self.inputs.week_start)

    def kind(self, pid, d: int, s: int) -> str:
        t = self.grid[pid][d][s]
        if t in (FREE, FREE_AND_EASY):
            return "free"
        if (pid, d, t) in self.data.adhoc_new:
            return "adhoc"
        if t in self.compulsory:
            return "compulsory"
        if self.data.routines.get(pid, {}).get((d, s), (None, None))[1] == t:
            return "routine"
        if t in self.rec_titles(pid):
            return "recommended"
        if t in self.data.groups:
            return "group"
        return "gap"

    def run_bounds(self, pid, d: int, s: int) -> Tuple[int, int]:
        day = self.grid[pid][d]
        a, b = s, s + 1
        while a > 0 and day[a - 1] == day[s]:
            a -= 1
        while b < len(day) and day[b] == day[s]:
            b += 1
        return a, b

    def run_unlocked(self, pid, d: int, s0: int, s1: int) -> bool:
        """Every activity touching [s0, s1) can be moved, none of it started already."""
        for k in range(s0, s1):
            if self.grid[pid][d][k] not in (FREE, FREE_AND_EASY) and not self.unlocked(d, *self.run_bounds(pid, d, k)):
                return False
        return self.unlocked(d, s0, s1)

    def clear_run(self, pid, d: int, s: int, reason: str) -> None:
        day = self.grid[pid][d]
        t = day[s]
        if t in (FREE, FREE_AND_EASY):
            day[s] = FREE
            return
        a = s
        while a > 0 and day[a - 1] == t:
            a -= 1
        b = s
        while b < len(day) and day[b] == t:
            day[b] = FREE
            b += 1
        for k in range(a, s):
            day[k] = FREE
        trace.record(trace.STAGE_REPAIR, pid, trace.DROPPED, reason, activity=t, day=d, slot=a)

    def place(self, pid, d: int, s0: int, title: str, length: int, reason: str) -> None:
        for k in range(s0, s0 + length):
            if self.grid[pid][d][k] != FREE:
                self.clear_run(pid, d, k, "displaced")
        for k in range(s0, s0 + length):
            self.grid[pid][d][k] = title
        trace.record(trace.STAGE_REPAIR, pid, trace.PLACED, reason, activity=title, day=d, slot=s0)

    def displaceable(self, pid, d: int, s0: int, length: int) -> Optional[bool]:
        """None if the span can't be used, else whether it means moving a gap-filled activity."""
        day = self.grid[pid][d]
        if s0 < 0 or s0 + length > len(day) or not self.run_unlocked(pid, d, s0, s0 + length):
            return None
        kinds = [self.kind(pid, d, k) for k in range(s0, s0 + length)]
        if any(k not in ("free", "gap") for k in kinds):
            return None
        return "gap" in kinds

    # steps

    def remove_invalid(self, pid) -> None:
        rules = self.rules(pid)
        recs = self.rec_titles(pid)
        routines = self.data.routines.get(pid, {})
        for d, day in enumerate(self.grid[pid]):
            seen = set()
            for s, e, t in _runs(list(day)):
                if t in self.data.groups and t not in self.compulsory:
                    continue  # groups have their own step
                reason = None
                if (pid, d, t) in self.data.adhoc_new:
                    reason = None
                elif t in self.compulsory:
                    c = self.compulsory[t]
                    length = slots_for(c.min_duration, self.inputs.min_activity_duration)
                    allowed = {k for dd, s0 in c.fixed_slots if dd == d for k in range(s0, s0 + length)}
                    if not set(range(s, e)) <= allowed:
                        reason = "not_at_set_time"
                elif all(routines.get((d, k), (None, None))[1] == t for k in range(s, e)):
                    if self.excluded(pid, routines[(d, s)][0], d):
                        reason = "excluded"
                else:
                    a = self.pool.get(t) or recs.get(t)
                    if a is None:
                        reason = "activity_gone"
                    else:
                        length = a.length if isinstance(a, Rec) else slots_for(a.min_duration, self.inputs.min_activity_duration)
                        if self.excluded(pid, a.activity_id, d):
                            reason = "excluded"
                        elif a.activity_id in rules.not_recommended:
                            reason = "not_recommended"
                        elif a.activity_id in rules.dislikes and a.activity_id not in rules.recommended:
                            reason = "disliked"
                        elif e - s != length:
                            reason = "duration_changed"
                        elif a.fixed_slots and (d, s) not in a.fixed_slots:
                            reason = "not_at_set_time"
                        elif t in seen:
                            reason = "repeat_in_day"
                if reason is None or not self.unlocked(d, s, e):
                    seen.add(t)  # started ones stay, even if no longer valid
                else:
                    self.clear_run(pid, d, s, reason)

    def add_compulsory(self, pid) -> None:
        for c in self.inputs.compulsory:
            length = slots_for(c.min_duration, self.inputs.min_activity_duration)
            for d, s0 in sorted(c.fixed_slots):
                if d >= len(self.grid[pid]) or s0 + length > len(self.grid[pid][d]):
                    continue
                if not self.run_unlocked(pid, d, s0, s0 + length):
                    continue
                span = range(s0, s0 + length)
                if all(self.grid[pid][d][k] == c.title for k in span):
                    continue
                held = {self.kind(pid, d, k) for k in span if self.grid[pid][d][k] != c.title}
                if held & {"compulsory", "adhoc"}:
                    trace.record(trace.STAGE_REPAIR, pid, trace.SKIPPED, "set_time_taken", activity=c.title, day=d, slot=s0,
                                 occupied_by=sorted({self.grid[pid][d][k] for k in span}))
                    continue
                self.place(pid, d, s0, c.title, length, "compulsory_now")

    def add_routines(self, pid) -> None:
        for (d, s), (activity_id, title) in sorted(self.data.routines.get(pid, {}).items()):
            if d >= len(self.grid[pid]) or s >= len(self.grid[pid][d]) or (d, s) in self.locked:
                continue
            if self.excluded(pid, activity_id, d) or self.grid[pid][d][s] == title:
                continue
            if self.displaceable(pid, d, s, 1) is None:
                trace.record(trace.STAGE_REPAIR, pid, trace.SKIPPED, "routine_slot_taken", activity=title, day=d, slot=s)
                continue
            self.place(pid, d, s, title, 1, "routine_now")

    def add_recommended(self, pid) -> None:
        week = {t for day in self.grid[pid] for t in day}
        for r in self.data.recommended.get(pid, []):
            if r.title in week:
                continue
            starts = sorted(r.fixed_slots) if r.fixed_slots else [
                (d, s) for d, day in enumerate(self.grid[pid]) for s in range(len(day))]
            options = []
            for d, s0 in starts:
                if d >= len(self.grid[pid]) or self.excluded(pid, r.activity_id, d) or r.title in self.grid[pid][d]:
                    continue
                moves = self.displaceable(pid, d, s0, r.length)
                if moves is not None:
                    options.append((moves, d, s0))
            if not options:
                trace.record(trace.STAGE_REPAIR, pid, trace.SKIPPED, "no_room_this_week", activity=r.title)
                continue
            # free slots first, then earliest
            _, d, s0 = min(options)
            self.place(pid, d, s0, r.title, r.length, "recommended_now")
            week.add(r.title)

    def group_count(self, pid) -> int:
        return sum(1 for day in self.grid[pid] for _, _, t in _runs(day) if t in self.data.groups)

    def has_in_week(self, pid, title: str) -> bool:
        return any(title in day for day in self.grid[pid])

    def fix_groups(self) -> None:
        groups = self.data.groups
        # members no longer allowed
        for pid, days in self.grid.items():
            for d, day in enumerate(days):
                for s, e, t in _runs(list(day)):
                    if t in self.compulsory or not self.unlocked(d, s, e):
                        continue
                    g = groups.get(t)
                    if g is None:
                        continue
                    if pid in self.data.group_blocked.get(t, set()):
                        self.clear_run(pid, d, s, "group_not_allowed")
                    elif e - s != g.length:
                        self.clear_run(pid, d, s, "duration_changed")

        # sessions running this week: (title, day, start)
        sessions = sorted({(t, d, s) for days in self.grid.values() for d, day in enumerate(days)
                           for s, _, t in _runs(day) if t in groups})
        for t, d, s0 in sessions:
            g = groups[t]
            if not self.unlocked(d, s0, s0 + g.length):
                continue
            members = [pid for pid, days in self.grid.items()
                       if s0 + g.length <= len(days[d]) and all(days[d][k] == t for k in range(s0, s0 + g.length))]
            if not members:
                continue
            blocked = self.data.group_blocked.get(t, set())

            def can_join(pid) -> bool:
                return (pid not in members and pid not in blocked and not self.has_in_week(pid, t)
                        and self.displaceable(pid, d, s0, g.length) is not None)

            # recommended ones join, and new patients who like it
            for pid in sorted(self.grid, key=str):
                wants = pid in self.data.group_recommended.get(t, set()) or (
                    pid in self.new_patients and pid in self.data.group_liked.get(t, set()))
                if wants and can_join(pid):
                    self.place(pid, d, s0, t, g.length, "group_joined")
                    members.append(pid)

            if len(members) >= g.min_size:
                continue
            # top up, fewest group activities first
            for pid in sorted(self.grid, key=lambda p: (self.group_count(p), str(p))):
                if len(members) >= g.min_size:
                    break
                if can_join(pid):
                    self.place(pid, d, s0, t, g.length, "group_top_up")
                    members.append(pid)
            if len(members) < g.min_size:
                for pid in members:
                    self.clear_run(pid, d, s0, "group_below_min_size")

    def fill_gaps(self, pid) -> None:
        rules = self.rules(pid)
        week = self.grid[pid]
        for d, day in enumerate(week):
            free = [(d, s) not in self.locked and t in (FREE, FREE_AND_EASY) for s, t in enumerate(day)]
            if any(free):
                used = {t for t, f in zip(day, free) if not f and t not in (FREE, FREE_AND_EASY)}
                week_counts = Counter(t for dd in week for t in dd if t not in (FREE, FREE_AND_EASY))
                candidates = build_candidates(
                    self.inputs.pool, d,
                    min_activity_duration=self.inputs.min_activity_duration,
                    week_start=self.inputs.week_start,
                    exclusions=rules.exclusions,
                    liked=rules.likes,
                    blocked=rules.dislikes | rules.not_recommended,
                    used_titles_today=used,
                    week_counts=week_counts,
                )
                result = solve_day(free, candidates)
                for start, c in sorted(result.assignment.items()):
                    for k in range(start, start + c.length):
                        day[k] = c.title
                    trace.record(trace.STAGE_PREFERRED, pid, trace.PLACED, "preferred" if c.liked else "neutral",
                                 activity=c.title, day=d, slot=start, strategy="repair")
            for s, t in enumerate(day):
                if t == FREE:
                    day[s] = FREE_AND_EASY


def repair_week(saved: Mapping[Any, Optional[List[List[str]]]], data: RepairData,
                locked: Set[Tuple[int, int]]) -> Dict[Any, List[List[str]]]:
    """saved is the stored week per patient (None if new). Returns activity titles, no medication."""
    r = _Repair(saved, data, locked)
    for pid in r.grid:
        r.remove_invalid(pid)
    for pid in r.grid:
        r.add_compulsory(pid)
        r.add_routines(pid)
        r.add_recommended(pid)
    r.fix_groups()
    for pid in r.grid:
        r.fill_gaps(pid)
    return r.grid


def locked_slots(config: Mapping[str, Any], week_start: datetime.datetime, now: datetime.datetime) -> Set[Tuple[int, int]]:
    """Past days, and today's slots that already started."""
    from pear_schedule.db_utils.utils import day_timeslot_labels

    out = set()
    for d, day in enumerate(config["OPEN_DAYS"]):
        date = week_start.date() + datetime.timedelta(days=WEEKDAYS.index(day))
        n = config["SLOTS_PER_DAY"].get(day)
        if date < now.date():
            out.update((d, s) for s in range(n))
        elif date == now.date():
            labels = day_timeslot_labels(day, n, config["WORKING_HOURS"], config["MIN_ACTIVITY_DURATION"])
            for s, label in enumerate(labels):
                if datetime.datetime.strptime(label.split("-")[0], "%H:%M").time() <= now.time():
                    out.add((d, s))
    return out


def saved_grid(row: Mapping[str, Any], config: Mapping[str, Any]) -> List[List[str]]:
    """Schedule row (day -> {"09:00-09:30": activity}) -> slot grid like build_schedules makes."""
    from pear_schedule.db_utils.utils import day_timeslot_labels

    grid = []
    for day in config["OPEN_DAYS"]:
        labels = day_timeslot_labels(day, config["SLOTS_PER_DAY"].get(day), config["WORKING_HOURS"],
                                     config["MIN_ACTIVITY_DURATION"])
        try:
            slots = json.loads(row.get(day) or "{}")
        except (TypeError, ValueError):
            slots = {}
        grid.append([slots.get(label, FREE) for label in labels])
    return grid


def load_repair_data(config: Mapping[str, Any], week_start: datetime.datetime) -> RepairData:
    """Everything repair reads, from the same views the stages use."""
    import pandas as pd

    from pear_schedule.db_utils.views import (
        AdhocActivityView, GroupActivitiesExclusionView, GroupActivitiesOnlyView, GroupActivitiesPreferenceView,
        GroupActivitiesRecommendationView, PatientsOnlyView, RecommendedActivitiesView, ValidRoutineActivitiesView,
    )
    from pear_schedule.scheduler.explain import collect_rule_inputs, parse_slots

    inputs = collect_rule_inputs(config, week_start)
    data = RepairData(inputs=inputs, patient_ids=list(PatientsOnlyView.get_data()["PatientID"]))
    min_d = config["MIN_ACTIVITY_DURATION"]

    # same week end as the recommended stage
    week_end = (week_start + datetime.timedelta(days=6)).replace(hour=23, minute=59, second=59)
    for _, r in RecommendedActivitiesView.get_data().iterrows():
        end = r.get("ActivityEndDate")
        # same filter as the recommended stage, null end means no end
        if end is not None and not pd.isna(end) and pd.Timestamp(end) <= pd.Timestamp(week_end):
            continue
        data.recommended.setdefault(r["PatientID"], []).append(
            Rec(int(r["ActivityID"]), r["ActivityTitle"], slots_for(r["MinDuration"], min_d), parse_slots(r["FixedTimeSlots"])))

    for _, r in ValidRoutineActivitiesView.get_data().iterrows():
        for d, s in parse_slots(r["FixedTimeSlots"]):
            data.routines.setdefault(r["PatientID"], {})[(d, s)] = (int(r["ActivityID"]), r["ActivityTitle"])

    title_by_centre_id = {}
    for _, r in GroupActivitiesOnlyView.get_data().iterrows():
        data.groups[r["ActivityTitle"]] = Group(int(r["ActivityID"]), r["ActivityTitle"],
                                                slots_for(r["MinDuration"], min_d), int(r["MinPeopleReq"]))
        title_by_centre_id[int(r["CentreActivityID"])] = r["ActivityTitle"]

    excluded, not_rec, disliked = {}, {}, {}
    for _, r in GroupActivitiesExclusionView.get_data().iterrows():
        t = title_by_centre_id.get(int(r["CentreActivityID"]))
        if t:
            excluded.setdefault(t, set()).add(r["PatientID"])
    for _, r in GroupActivitiesRecommendationView.get_data().iterrows():
        t = title_by_centre_id.get(int(r["CentreActivityID"]))
        if t and int(r["DoctorRecommendation"]) == 1:
            data.group_recommended.setdefault(t, set()).add(r["PatientID"])
        elif t and int(r["DoctorRecommendation"]) == -1:
            not_rec.setdefault(t, set()).add(r["PatientID"])
    for _, r in GroupActivitiesPreferenceView.get_data().iterrows():
        t = title_by_centre_id.get(int(r["CentreActivityID"]))
        if t and int(r["IsLike"]) == 1:
            data.group_liked.setdefault(t, set()).add(r["PatientID"])
        elif t and int(r["IsLike"]) == -1:
            disliked.setdefault(t, set()).add(r["PatientID"])
    for t in data.groups:
        rec = data.group_recommended.get(t, set())
        data.group_blocked[t] = excluded.get(t, set()) | not_rec.get(t, set()) | (disliked.get(t, set()) - rec)

    # adhoc requests this week, same date handling as the adhoc stage
    for _, r in AdhocActivityView.get_data().iterrows():
        new, start, end = r.get("NewActivityTitle"), r.get("StartDate"), r.get("EndDate")
        if not new or start is None or end is None or pd.isna(start) or pd.isna(end):
            continue
        for d in range(len(config["OPEN_DAYS"])):
            date = (week_start + datetime.timedelta(days=d)).date()
            if pd.Timestamp(start).date() <= date <= pd.Timestamp(end).date():
                data.adhoc_new.add((r["PatientID"], d, new))
    return data


def repair_schedules(config: Mapping[str, Any], patientSchedules: Dict, now: Optional[datetime.datetime] = None):
    """
    Regenerate in repair mode. Puts only the patients whose schedule changed into
    patientSchedules (same shape as build_schedules) and returns the medication data.
    """
    from pear_schedule.db import DB
    from pear_schedule.scheduler.adhocScheduling import AdhocScheduler
    from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler
    from pear_schedule.scheduler.medicationScheduling import medicationScheduler

    now = now or datetime.datetime.now()
    # same week start as the stages
    week_start = now - datetime.timedelta(days=now.weekday())
    data = load_repair_data(config, week_start)

    saved: Dict[Any, Optional[List[List[str]]]] = {pid: None for pid in data.patient_ids}
    with DB.get_engine().begin() as conn:
        rows = PreferredActivityScheduler.getMostUpdatedSchedules(data.patient_ids, conn, now.date())
    for _, row in rows.iterrows():
        if row["PatientID"] in saved:
            saved[row["PatientID"]] = saved_grid(row, config)

    locked = locked_slots(config, week_start, now)
    grids = repair_week(saved, data, locked)
    AdhocScheduler.fillSchedule(grids)
    medication_ref = medicationScheduler.fillSchedule(grids)

    changed = 0
    for pid, grid in grids.items():
        old = saved[pid]
        if old is not None:
            # started slots keep exactly what was saved, medication note included
            for d, s in locked:
                if d < len(grid) and s < len(grid[d]) and d < len(old) and s < len(old[d]):
                    grid[d][s] = old[d][s]
        if old is None or grid != [[v or FREE_AND_EASY for v in day] for day in old]:
            patientSchedules[pid] = grid
            changed += 1
    logger.info(f"Regenerate (repair): {changed} of {len(grids)} patients changed")
    return medication_ref
