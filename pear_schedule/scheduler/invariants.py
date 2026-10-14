"""
Business rule checks for generated schedules.

  R1 exclusions apply on the days they cover, beat everything but compulsory
  R2 doctor -1 is never scheduled
  R3 dislikes are never scheduled unless recommended
  R4 compulsory activities at their fixed slots
  R7 no individual activity repeated in a day
  R8 Free and Easy only when nothing eligible fits
  R9 right slot count per day, no blank slots

analyse_free_and_easy() re-solves each day's Free and Easy slots. Fillable ones
are LOGIC, the rest are DATA with a reason.
"""

import datetime
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

from pear_schedule.scheduler.gapFill import PoolActivity, build_candidates, is_excluded, slots_for, solve_day

FREE_AND_EASY = "Free and Easy"

# R8 reasons
LOGIC = "LOGIC"
NO_ELIGIBLE_ACTIVITIES = "no_eligible_activities"
POOL_EXHAUSTED_TODAY = "pool_exhausted_today"
NO_FIT_FOR_GAP_LENGTH = "no_fit_for_gap_length"
FIXED_SLOT_ELSEWHERE = "fixed_slot_elsewhere"


def base_title(slot_value: str) -> str:
    """'Walk | Give Medication@0900: ...' -> 'Walk'"""
    return (slot_value or "").split(" | ")[0].strip()


@dataclass
class PatientRules:
    likes: Set[int] = field(default_factory=set)
    dislikes: Set[int] = field(default_factory=set)
    recommended: Set[int] = field(default_factory=set)
    not_recommended: Set[int] = field(default_factory=set)
    exclusions: Dict[int, Optional[datetime.datetime]] = field(default_factory=dict)


@dataclass
class RuleInputs:
    slots_per_day: List[int]
    min_activity_duration: int
    week_start: datetime.datetime
    pool: List[PoolActivity]                       # individual activities gap filling may use
    patients: Dict[Any, PatientRules]
    compulsory: List[PoolActivity] = field(default_factory=list)
    activity_ids_by_title: Dict[str, int] = field(default_factory=dict)  # every known activity
    exempt: Set[Tuple[Any, int, int]] = field(default_factory=set)       # (pid, day, slot) set by adhoc

    def activity_id(self, title: str) -> Optional[int]:
        if title in self.activity_ids_by_title:
            return self.activity_ids_by_title[title]
        for a in self.pool:
            if a.title == title:
                return a.activity_id
        return None


@dataclass
class Violation:
    rule: str
    patient_id: Any
    message: str
    day: Optional[int] = None
    slot: Optional[int] = None
    activity: Optional[str] = None


@dataclass
class FreeAndEasyReport:
    total: int = 0
    avoidable: int = 0
    unavoidable: Counter = field(default_factory=Counter)
    # (pid, day) -> slots, avoidable, could_use, reasons, slot_reasons
    by_patient_day: Dict[Tuple[Any, int], Dict[str, Any]] = field(default_factory=dict)

    @property
    def unavoidable_total(self) -> int:
        return sum(self.unavoidable.values())

    def as_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "avoidable_logic": self.avoidable,
            "unavoidable_data": self.unavoidable_total,
            "unavoidable_by_reason": dict(self.unavoidable),
        }


def _runs(free: Sequence[bool]) -> List[Tuple[int, int]]:
    """[start, end) of each maximal run of True."""
    out, i, n = [], 0, len(free)
    while i < n:
        if free[i]:
            j = i
            while j < n and free[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _unavoidable_reason(run: Tuple[int, int], day: int, rules: PatientRules, inputs: RuleInputs,
                        used_titles_today: Set[str]) -> str:
    start, end = run
    run_len = end - start
    blocked = rules.dislikes | rules.not_recommended
    eligible = [
        a for a in inputs.pool
        if a.activity_id not in blocked and not is_excluded(a.activity_id, rules.exclusions, day, inputs.week_start)
    ]
    if not eligible:
        return NO_ELIGIBLE_ACTIVITIES
    unused = [a for a in eligible if a.title not in used_titles_today]
    if not unused:
        return POOL_EXHAUSTED_TODAY
    if all(slots_for(a.min_duration, inputs.min_activity_duration) > run_len for a in unused):
        return NO_FIT_FOR_GAP_LENGTH
    if all(a.fixed_slots for a in unused if slots_for(a.min_duration, inputs.min_activity_duration) <= run_len):
        return FIXED_SLOT_ELSEWHERE
    # fits, but the best fill already uses it in another gap
    return POOL_EXHAUSTED_TODAY


def analyse_free_and_easy(schedules: Mapping[Any, List[List[str]]], inputs: RuleInputs) -> FreeAndEasyReport:
    report = FreeAndEasyReport()
    for pid, days in schedules.items():
        rules = inputs.patients.get(pid, PatientRules())
        for d, day in enumerate(days):
            titles = [base_title(v) for v in day]
            free = [t == FREE_AND_EASY and (pid, d, s) not in inputs.exempt for s, t in enumerate(titles)]
            n_fe = sum(free)
            if not n_fe:
                continue
            used_today = {t for t, f in zip(titles, free) if t and not f and t != FREE_AND_EASY}
            candidates = build_candidates(
                inputs.pool, d,
                min_activity_duration=inputs.min_activity_duration,
                week_start=inputs.week_start,
                exclusions=rules.exclusions,
                liked=rules.likes,
                blocked=rules.dislikes | rules.not_recommended,
                used_titles_today=used_today,
            )
            best = solve_day(free, candidates)
            avoidable = best.score[0]

            taken = set()
            for start, c in best.assignment.items():
                taken.update(range(start, start + c.length))
            left = [f and s not in taken for s, f in enumerate(free)]
            used_after = used_today | {c.title for c in best.assignment.values()}
            reasons = Counter()
            slot_reasons = {s: LOGIC for s in taken}
            for run in _runs(left):
                reason = _unavoidable_reason(run, d, rules, inputs, used_after)
                reasons[reason] += run[1] - run[0]
                slot_reasons.update({s: reason for s in range(*run)})

            report.total += n_fe
            report.avoidable += avoidable
            report.unavoidable.update(reasons)
            report.by_patient_day[(pid, d)] = {
                "slots": [s for s, f in enumerate(free) if f],
                "avoidable": avoidable,
                "could_use": sorted(c.title for c in best.assignment.values()),
                "reasons": reasons,
                "slot_reasons": slot_reasons,
            }
    return report


def _run_titles(day_titles: List[str]) -> List[str]:
    out, prev = [], None
    for t in day_titles:
        if t != prev:
            out.append(t)
        prev = t
    return out


def check_rules(schedules: Mapping[Any, List[List[str]]], inputs: RuleInputs) -> List[Violation]:
    violations: List[Violation] = []
    pool_titles = {a.title for a in inputs.pool}
    compulsory_titles = {a.title for a in inputs.compulsory}

    for pid, days in schedules.items():
        rules = inputs.patients.get(pid, PatientRules())

        # R9: shape and no blank slots
        if len(days) != len(inputs.slots_per_day):
            violations.append(Violation("R9", pid, f"{len(days)} days, expected {len(inputs.slots_per_day)}"))
        for d, day in enumerate(days):
            if d < len(inputs.slots_per_day) and len(day) != inputs.slots_per_day[d]:
                violations.append(Violation("R9", pid, f"{len(day)} slots, expected {inputs.slots_per_day[d]}", day=d))
            for s, v in enumerate(day):
                if not base_title(v):
                    violations.append(Violation("R9", pid, "blank slot", day=d, slot=s))

        for d, day in enumerate(days):
            titles = [base_title(v) for v in day]

            for s, t in enumerate(titles):
                if not t or t == FREE_AND_EASY or t in compulsory_titles or (pid, d, s) in inputs.exempt:
                    continue
                aid = inputs.activity_id(t)
                if aid is None:
                    continue
                # R1: exclusions win over everything except compulsory
                if is_excluded(aid, rules.exclusions, d, inputs.week_start):
                    violations.append(Violation("R1", pid, "excluded activity scheduled", d, s, t))
                # R2: doctor says not recommended
                if aid in rules.not_recommended:
                    violations.append(Violation("R2", pid, "not-recommended activity scheduled", d, s, t))
                # R3: dislikes, unless a doctor recommended it
                if aid in rules.dislikes and aid not in rules.recommended:
                    violations.append(Violation("R3", pid, "disliked activity scheduled", d, s, t))

            # R7: once a day, a multi-slot run counts once
            runs = Counter(t for t in _run_titles(titles) if t in pool_titles)
            for t, n in runs.items():
                if n > 1:
                    violations.append(Violation("R7", pid, f"scheduled {n} times in one day", day=d, activity=t))

        # R4: compulsory at fixed slots, if the slot exists that day
        for c in inputs.compulsory:
            length = slots_for(c.min_duration, inputs.min_activity_duration)
            for d, s in sorted(c.fixed_slots):
                if d >= len(days) or s + length > len(days[d]):
                    continue
                for k in range(s, s + length):
                    if (pid, d, k) in inputs.exempt:
                        continue
                    if base_title(days[d][k]) != c.title:
                        violations.append(Violation("R4", pid, "compulsory activity missing from its fixed slot",
                                                    d, k, c.title))

    # R8: Free and Easy only when unavoidable
    report = analyse_free_and_easy(schedules, inputs)
    for (pid, d), info in report.by_patient_day.items():
        if info["avoidable"]:
            violations.append(Violation(
                "R8", pid, f"{info['avoidable']} Free and Easy slot(s) could be filled with {info['could_use']}", day=d,
            ))
    return violations
