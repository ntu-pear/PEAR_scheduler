"""
What-if for Free and Easy left by data: re-solves this week's Free and Easy with one
activity changed (made flexible, made 30 min) or a new 30 min activity added, and
counts how many slots it would fill. Nothing else moves. Read-only.
"""

import copy
import dataclasses
from collections import Counter
from typing import Any, Dict, List, Mapping

from pear_schedule.scheduler.gapFill import PoolActivity
from pear_schedule.scheduler.invariants import LOGIC, RuleInputs, analyse_free_and_easy

MAKE_FLEXIBLE = "make_flexible"
MAKE_SHORT = "make_30_min"
ADD_SHORT = "add_30_min_activity"
ALL_FLEXIBLE = "all_flexible"
NEW_ACTIVITY = "New 30 min activity"


def _with_pool(inputs: RuleInputs, pool: List[PoolActivity]) -> RuleInputs:
    out = copy.copy(inputs)
    out.pool = pool
    return out


def _filled(schedules, inputs: RuleInputs, base) -> Dict[str, Any]:
    """Slots the changed data fills that were Free and Easy, by their old reason."""
    report = analyse_free_and_easy(schedules, inputs)
    by_reason, patients = Counter(), set()
    for key, info in report.by_patient_day.items():
        old = base.by_patient_day.get(key, {}).get("slot_reasons", {})
        for s, reason in info["slot_reasons"].items():
            if reason == LOGIC and old.get(s) != LOGIC:
                by_reason[old.get(s)] += 1
                patients.add(key[0])
    return {
        "fills": sum(by_reason.values()),
        # if gap filling also re-arranged its own picks
        "fills_rearranged": report.avoidable_rearranged - base.avoidable_rearranged,
        "patients": len(patients),
        "from_reasons": dict(by_reason),
    }


def what_if(schedules: Mapping[Any, List[List[str]]], inputs: RuleInputs, slot_minutes: int = 30) -> Dict[str, Any]:
    """Free and Easy each data change would fill, biggest first."""
    base = analyse_free_and_easy(schedules, inputs)
    options = []

    def add(change, activity, pool):
        options.append({"change": change, "activity": activity, **_filled(schedules, _with_pool(inputs, pool), base)})

    for i, a in enumerate(inputs.pool):
        if a.fixed_slots:
            add(MAKE_FLEXIBLE, a.title, inputs.pool[:i] + [dataclasses.replace(a, fixed_slots=frozenset())] + inputs.pool[i + 1:])
        if a.min_duration > slot_minutes:
            add(MAKE_SHORT, a.title, inputs.pool[:i] + [dataclasses.replace(a, min_duration=slot_minutes)] + inputs.pool[i + 1:])

    new_id = max((a.activity_id for a in inputs.pool), default=0) + 1
    add(ADD_SHORT, NEW_ACTIVITY, inputs.pool + [PoolActivity(new_id, NEW_ACTIVITY, slot_minutes)])
    if any(a.fixed_slots for a in inputs.pool):
        add(ALL_FLEXIBLE, None, [dataclasses.replace(a, fixed_slots=frozenset()) for a in inputs.pool])

    options = [o for o in options if o["fills"] or o["fills_rearranged"]]
    options.sort(key=lambda o: (-o["fills"], -o["fills_rearranged"], o["change"], o["activity"] or ""))
    return {
        "free_and_easy": base.total,
        "unavoidable_data": base.unavoidable_total,
        "options": options,
    }


def format_what_if(report: Mapping[str, Any], top: int = 15) -> str:
    lines = [f"What if (Free and Easy {report['free_and_easy']}, {report['unavoidable_data']} from data):"]
    if not report["options"]:
        lines.append("  no single data change fills any of it")
    for o in report["options"][:top]:
        what = o["change"] if o["activity"] is None else f"{o['change']} {o['activity']!r}"
        lines.append(
            f"  {what:<48} fills {o['fills']:>4} ({o['fills_rearranged']} if re-arranged), "
            f"{o['patients']} patients, was {o['from_reasons']}"
        )
    return "\n".join(lines)
