"""
Repair mode against the real pipeline on random centres: a week built by the stages
comes back unchanged when nothing changed, and one change only touches that patient.
"""

import copy
import datetime
import random

from hypothesis import given, strategies as st

from pear_schedule.scheduler.invariants import FREE_AND_EASY, PatientRules, base_title, check_rules
from pear_schedule.scheduler.repair import load_repair_data, repair_week
from tests.property_tests.test_schedule_rules import SETTINGS, _scenario, centres
from tests.utils.schedule_scenarios import WEEK_START, patched, run


def _titles(schedules):
    return {p: [[base_title(v) or FREE_AND_EASY for v in day] for day in days] for p, days in schedules.items()}


def _saved_and_data(p):
    scenario = _scenario(p)
    schedules, _, _ = run(scenario, "optimal")
    with patched(scenario, "optimal") as config:
        data = load_repair_data(config, WEEK_START)
    return _titles(schedules), data


@SETTINGS
@given(centres)
def test_nothing_changed_means_nothing_changes(p):
    saved, data = _saved_and_data(p)
    assert repair_week(copy.deepcopy(saved), data, set()) == saved


@SETTINGS
@given(centres, st.integers(0, 10**6))
def test_one_exclusion_only_touches_that_patient(p, pick):
    saved, data = _saved_and_data(p)
    rng = random.Random(pick)
    placed = sorted({(pid, t) for pid, days in saved.items() for day in days for t in day
                     if data.inputs.activity_id(t) and t in {a.title for a in data.inputs.pool}})
    if not placed:
        return
    pid, title = rng.choice(placed)
    aid = data.inputs.activity_id(title)
    data.inputs.patients.setdefault(pid, PatientRules())
    data.inputs.patients[pid].exclusions[aid] = None  # until further notice

    out = repair_week(copy.deepcopy(saved), data, set())
    assert all(out[q] == saved[q] for q in saved if q != pid)
    assert all(title not in day for day in out[pid])
    assert [v for v in check_rules({pid: out[pid]}, data.inputs) if v.rule != "R4"] == []


@SETTINGS
@given(centres, st.integers(0, 10**6))
def test_past_days_never_change(p, pick):
    saved, data = _saved_and_data(p)
    days = len(next(iter(saved.values()))) if saved else 0
    if not days:
        return
    cut = random.Random(pick).randrange(days)
    locked = {(d, s) for d in range(cut) for s in range(len(saved[next(iter(saved))][d]))}
    for rules in data.inputs.patients.values():
        rules.dislikes.update(a.activity_id for a in data.inputs.pool)  # plenty to change
    out = repair_week(copy.deepcopy(saved), data, locked)
    assert all(out[q][d] == saved[q][d] for q in saved for d in range(cut))
