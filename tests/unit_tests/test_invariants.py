"""scheduler/invariants.py tests."""

import datetime

from pear_schedule.scheduler.gapFill import PoolActivity
from pear_schedule.scheduler.invariants import (
    ALREADY_PASSED, FIXED_SLOT_ELSEWHERE, NO_ELIGIBLE_ACTIVITIES, NO_FIT_FOR_GAP_LENGTH, POOL_EXHAUSTED_TODAY,
    PatientRules, RuleInputs, analyse_free_and_easy, base_title, check_rules,
)

WEEK_START = datetime.datetime(2024, 3, 18)
FE = "Free and Easy"


def _inputs(pool=None, rules=None, slots=(4,), compulsory=None, exempt=None):
    pool = pool if pool is not None else [PoolActivity(1, "Walk", 30), PoolActivity(2, "Sewing", 60)]
    return RuleInputs(
        slots_per_day=list(slots), min_activity_duration=30, week_start=WEEK_START, pool=pool,
        patients={1: rules or PatientRules()}, compulsory=compulsory or [],
        activity_ids_by_title={"Lunch": 9, **{a.title: a.activity_id for a in pool}},
        exempt=exempt or set(),
    )


def _rules_of(violations):
    return sorted(v.rule for v in violations)


class TestCheckRules:
    def test_clean_schedule_has_no_violations(self):
        schedules = {1: [["Lunch", "Walk", "Sewing", "Sewing"]]}
        assert check_rules(schedules, _inputs()) == []

    def test_medication_suffix_is_ignored(self):
        assert base_title("Walk | Give Medication@0900: Aspirin(1)") == "Walk"
        schedules = {1: [["Lunch", "Walk | Give Medication@0900: Aspirin(1)", "Sewing", "Sewing"]]}
        assert check_rules(schedules, _inputs()) == []

    def test_excluded_activity_is_r1(self):
        rules = PatientRules(exclusions={1: None})
        schedules = {1: [["Lunch", "Walk", "Sewing", "Sewing"]]}
        assert _rules_of(check_rules(schedules, _inputs(rules=rules))) == ["R1"]

    def test_exclusion_window_respected(self):
        rules = PatientRules(exclusions={1: datetime.datetime(2024, 3, 18, 23, 59)})  # Monday only
        schedules = {1: [["Lunch", "Sewing", "Sewing", FE], ["Walk", "Sewing", "Sewing", FE]]}
        violations = check_rules(schedules, _inputs(rules=rules, slots=(4, 4)))
        assert "R1" not in _rules_of(violations)

    def test_not_recommended_is_r2_and_dislike_is_r3(self):
        rules = PatientRules(not_recommended={1}, dislikes={2})
        schedules = {1: [["Lunch", "Walk", "Sewing", "Sewing"]]}
        # Sewing takes two slots, one violation per slot
        assert _rules_of(check_rules(schedules, _inputs(rules=rules))) == ["R2", "R3", "R3"]

    def test_recommendation_overrides_dislike(self):
        rules = PatientRules(recommended={2}, dislikes={2})
        schedules = {1: [["Lunch", "Walk", "Sewing", "Sewing"]]}
        assert check_rules(schedules, _inputs(rules=rules)) == []

    def test_missing_compulsory_is_r4(self):
        lunch = PoolActivity(9, "Lunch", 30, frozenset({(0, 0)}))
        schedules = {1: [["Walk", FE, "Sewing", "Sewing"]]}
        violations = check_rules(schedules, _inputs(compulsory=[lunch]))
        assert "R4" in _rules_of(violations)

    def test_adhoc_exempt_slot_is_not_r4(self):
        lunch = PoolActivity(9, "Lunch", 30, frozenset({(0, 0)}))
        schedules = {1: [["Outing", "Walk", "Sewing", "Sewing"]]}
        assert check_rules(schedules, _inputs(compulsory=[lunch], exempt={(1, 0, 0)})) == []

    def test_passed_slots_are_not_flagged(self):
        """Lunch missing and Walk disliked, but both already passed."""
        lunch = PoolActivity(9, "Lunch", 30, frozenset({(0, 0)}))
        inputs = _inputs(rules=PatientRules(dislikes={1}), compulsory=[lunch])
        inputs.locked = {(1, 0, 0), (1, 0, 1)}
        assert check_rules({1: [["Sewing", "Walk", FE, FE]]}, inputs) == []

    def test_passed_day_has_no_r7(self):
        inputs = _inputs(pool=[PoolActivity(1, "Walk", 30)])
        inputs.locked = {(1, 0, s) for s in range(4)}
        assert check_rules({1: [["Walk", "Lunch", "Walk", FE]]}, inputs) == []

    def test_repeat_in_a_day_is_r7(self):
        schedules = {1: [["Walk", "Lunch", "Walk", FE]]}
        pool = [PoolActivity(1, "Walk", 30)]
        assert "R7" in _rules_of(check_rules(schedules, _inputs(pool=pool)))

    def test_blank_slot_and_wrong_shape_are_r9(self):
        schedules = {1: [["Walk", "", "Lunch"]]}
        assert _rules_of(check_rules(schedules, _inputs(pool=[PoolActivity(1, "Walk", 30)]))).count("R9") == 2

    def test_avoidable_free_and_easy_is_r8(self):
        schedules = {1: [["Lunch", FE, FE, FE]]}
        violations = check_rules(schedules, _inputs())
        assert _rules_of(violations) == ["R8"]
        assert "3 Free and Easy" in violations[0].message


class TestAnalyseFreeAndEasy:
    def test_logic_vs_data_split(self):
        # Walk + Sewing fill 3 of 4, the 4th is unavoidable
        schedules = {1: [["Lunch", FE, FE, FE, FE]]}
        report = analyse_free_and_easy(schedules, _inputs(slots=(5,)))
        assert report.total == 4
        assert report.avoidable == 3
        assert report.unavoidable == {POOL_EXHAUSTED_TODAY: 1}
        slot_reasons = report.by_patient_day[(1, 0)]["slot_reasons"]
        assert sorted(slot_reasons.values()).count("LOGIC") == 3
        assert set(slot_reasons) == {1, 2, 3, 4}

    def test_no_eligible_activities(self):
        rules = PatientRules(dislikes={1}, exclusions={2: None})
        report = analyse_free_and_easy({1: [["Lunch", FE, FE, FE]]}, _inputs(rules=rules))
        assert report.avoidable == 0
        assert report.unavoidable == {NO_ELIGIBLE_ACTIVITIES: 3}

    def test_pool_exhausted_today(self):
        report = analyse_free_and_easy({1: [["Walk", "Sewing", "Sewing", FE]]}, _inputs())
        assert report.unavoidable == {POOL_EXHAUSTED_TODAY: 1}

    def test_no_fit_for_gap_length(self):
        pool = [PoolActivity(2, "Sewing", 60)]
        report = analyse_free_and_easy({1: [["Lunch", FE, "Lunch2", FE]]}, _inputs(pool=pool))
        assert report.avoidable == 0
        assert report.unavoidable == {NO_FIT_FOR_GAP_LENGTH: 2}

    def test_fixed_slot_elsewhere(self):
        pool = [PoolActivity(3, "Yoga", 30, frozenset({(0, 0)}))]
        report = analyse_free_and_easy({1: [["Lunch", FE, "Lunch2", "Lunch3"]]}, _inputs(pool=pool))
        assert report.unavoidable == {FIXED_SLOT_ELSEWHERE: 1}

    def test_avoidable_only_by_moving_gap_fill_picks(self):
        """Chess blocks the only 2-slot gap, nothing fits in place, but moving it fills 2 more."""
        pool = [PoolActivity(1, "Chess", 30), PoolActivity(2, "Gardening", 60)]
        schedules = {1: [["Chess", FE, "Lunch", FE]]}
        inputs = _inputs(pool=pool)
        inputs.gap_filled = {(1, 0, 0)}
        report = analyse_free_and_easy(schedules, inputs)
        assert report.avoidable == 0
        assert report.avoidable_rearranged == 2

    def test_passed_free_and_easy_is_not_avoidable(self):
        """Morning already passed, only the afternoon slot can still be filled."""
        inputs = _inputs(pool=[PoolActivity(1, "Walk", 30)])
        inputs.locked = {(1, 0, 0), (1, 0, 1)}
        report = analyse_free_and_easy({1: [[FE, "Lunch", FE, "Lunch2"]]}, inputs)
        assert report.total == 2
        assert report.avoidable == 1
        assert report.by_patient_day[(1, 0)]["slot_reasons"] == {0: ALREADY_PASSED, 2: "LOGIC"}
        assert report.unavoidable == {ALREADY_PASSED: 1}

    def test_passed_and_unfillable_keeps_its_data_reason(self):
        inputs = _inputs(rules=PatientRules(dislikes={1, 2}))
        inputs.locked = {(1, 0, 0), (1, 0, 1)}
        report = analyse_free_and_easy({1: [[FE, "Lunch", FE, "Lunch2"]]}, inputs)
        assert report.unavoidable == {NO_ELIGIBLE_ACTIVITIES: 2}

    def test_exempt_slots_are_not_counted(self):
        report = analyse_free_and_easy({1: [["Lunch", FE, FE, FE]]}, _inputs(exempt={(1, 0, 1), (1, 0, 2), (1, 0, 3)}))
        assert report.total == 0
