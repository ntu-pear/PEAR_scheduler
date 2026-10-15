"""scheduler/what_if.py tests."""

import datetime

from pear_schedule.scheduler.gapFill import PoolActivity
from pear_schedule.scheduler.invariants import (
    FIXED_SLOT_ELSEWHERE, NO_ELIGIBLE_ACTIVITIES, NO_FIT_FOR_GAP_LENGTH, PatientRules, RuleInputs,
)
from pear_schedule.scheduler.what_if import (
    ADD_SHORT, ALL_FLEXIBLE, MAKE_FLEXIBLE, MAKE_SHORT, NEW_ACTIVITY, format_what_if, what_if,
)

WEEK_START = datetime.datetime(2024, 3, 18)
FE = "Free and Easy"


def _inputs(pool, rules=None, slots=(4,), patients=(1,), locked=None):
    return RuleInputs(
        slots_per_day=list(slots), min_activity_duration=30, week_start=WEEK_START, pool=pool,
        patients={p: rules or PatientRules() for p in patients},
        activity_ids_by_title={"Lunch": 9, **{a.title: a.activity_id for a in pool}},
        locked=locked or set(),
    )


def _option(report, change, activity=None):
    return next(o for o in report["options"] if o["change"] == change and o["activity"] == activity)


class TestWhatIf:
    def test_flexible_fills_fixed_slot_elsewhere(self):
        # Walk is fixed to slot 3, the gap is slot 1
        pool = [PoolActivity(1, "Walk", 30, frozenset({(0, 3)}))]
        schedules = {1: [["Lunch", FE, "Lunch", "Lunch"]]}
        report = what_if(schedules, _inputs(pool))
        o = _option(report, MAKE_FLEXIBLE, "Walk")
        assert o["fills"] == 1
        assert o["patients"] == 1
        assert o["from_reasons"] == {FIXED_SLOT_ELSEWHERE: 1}

    def test_short_fills_no_fit_for_gap_length(self):
        pool = [PoolActivity(2, "Sewing", 60)]
        schedules = {1: [["Lunch", FE, "Lunch", "Lunch"]]}
        report = what_if(schedules, _inputs(pool))
        o = _option(report, MAKE_SHORT, "Sewing")
        assert o["fills"] == 1
        assert o["from_reasons"] == {NO_FIT_FOR_GAP_LENGTH: 1}

    def test_new_short_activity_fills_one_slot_per_day(self):
        pool = [PoolActivity(1, "Walk", 30)]
        rules = PatientRules(dislikes={1})
        schedules = {1: [["Lunch", FE, FE, "Lunch"], [FE, "Lunch", "Lunch", "Lunch"]]}
        report = what_if(schedules, _inputs(pool, rules=rules, slots=(4, 4)))
        o = _option(report, ADD_SHORT, NEW_ACTIVITY)
        # once a day, so 1 of the 2 Monday slots and the Tuesday one
        assert o["fills"] == 2
        assert o["from_reasons"] == {NO_ELIGIBLE_ACTIVITIES: 2}

    def test_all_flexible_counts_every_fixed_activity(self):
        pool = [PoolActivity(1, "Walk", 30, frozenset({(0, 0)})), PoolActivity(3, "Bingo", 30, frozenset({(0, 0)}))]
        schedules = {1: [["Lunch", FE, FE, "Lunch"]]}
        report = what_if(schedules, _inputs(pool))
        assert _option(report, ALL_FLEXIBLE)["fills"] == 2
        assert _option(report, MAKE_FLEXIBLE, "Walk")["fills"] == 1

    def test_already_on_the_day_stays_once_a_day(self):
        pool = [PoolActivity(1, "Walk", 30, frozenset({(0, 3)}))]
        schedules = {1: [["Lunch", FE, "Lunch", "Walk"]]}
        report = what_if(schedules, _inputs(pool))
        assert all(o["activity"] != "Walk" for o in report["options"])

    def test_excluded_activity_stays_excluded(self):
        pool = [PoolActivity(1, "Walk", 30, frozenset({(0, 3)}))]
        rules = PatientRules(exclusions={1: None})
        schedules = {1: [["Lunch", FE, "Lunch", "Lunch"]]}
        report = what_if(schedules, _inputs(pool, rules=rules))
        assert all(o["activity"] != "Walk" for o in report["options"])

    def test_passed_slots_are_not_counted(self):
        pool = [PoolActivity(1, "Walk", 30, frozenset({(0, 3)}))]
        schedules = {1: [["Lunch", FE, "Lunch", "Lunch"]]}
        report = what_if(schedules, _inputs(pool, locked={(1, 0, 1)}))
        assert all(o["activity"] != "Walk" for o in report["options"])

    def test_biggest_first_and_does_not_change_inputs(self):
        pool = [PoolActivity(1, "Walk", 30, frozenset({(0, 3)})), PoolActivity(2, "Sewing", 60)]
        inputs = _inputs(pool, patients=(1, 2))
        schedules = {1: [["Lunch", FE, FE, "Lunch"]], 2: [["Lunch", FE, "Lunch", "Lunch"]]}
        report = what_if(schedules, inputs)
        fills = [o["fills"] for o in report["options"]]
        assert fills == sorted(fills, reverse=True)
        assert inputs.pool == pool
        assert pool[0].fixed_slots == frozenset({(0, 3)})
        assert report["free_and_easy"] == 3

    def test_nothing_to_fill(self):
        pool = [PoolActivity(1, "Walk", 30)]
        report = what_if({1: [["Lunch", "Walk", "Lunch", "Lunch"]]}, _inputs(pool))
        assert report["options"] == []
        assert "no single data change" in format_what_if(report)

    def test_format(self):
        pool = [PoolActivity(2, "Sewing", 60)]
        report = what_if({1: [["Lunch", FE, "Lunch", "Lunch"]]}, _inputs(pool))
        text = format_what_if(report)
        assert "make_30_min 'Sewing'" in text
        assert "fills    1" in text
