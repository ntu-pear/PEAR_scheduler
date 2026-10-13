"""
Random centres through the whole pipeline, checked against the business rules.
Scenarios come from tests/utils/schedule_scenarios.py, hypothesis picks the seed and sizes.
"""

import random

from hypothesis import HealthCheck, given, settings, strategies as st

from pear_schedule.scheduler import trace
from pear_schedule.scheduler.invariants import analyse_free_and_easy, check_rules
from tests.utils.schedule_scenarios import make_scenario, run

SETTINGS = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])

centres = st.fixed_dictionaries({
    "seed": st.integers(0, 10**6),
    "patients": st.integers(1, 4),
    "days": st.integers(1, 6),
    "slots": st.integers(6, 16),
    "pool_size": st.integers(0, 12),
    "flexible_share": st.floats(0, 1),
    "short_share": st.floats(0, 1),
    "compulsory": st.integers(0, 3),
})


def _scenario(p):
    p = dict(p)
    return make_scenario(random.Random(p.pop("seed")), **p)


def _rules(violations):
    return sorted({v.rule for v in violations})


@SETTINGS
@given(centres)
def test_optimal_follows_every_rule(p):
    schedules, _, inputs = run(_scenario(p), "optimal")
    assert check_rules(schedules, inputs) == []


@SETTINGS
@given(centres)
def test_greedy_follows_every_rule_but_free_and_easy(p):
    schedules, _, inputs = run(_scenario(p), "greedy")
    assert set(_rules(check_rules(schedules, inputs))) <= {"R8"}


@SETTINGS
@given(centres)
def test_optimal_never_leaves_more_free_and_easy_than_greedy(p):
    scenario = _scenario(p)
    greedy = analyse_free_and_easy(*_schedules_and_inputs(scenario, "greedy"))
    optimal = analyse_free_and_easy(*_schedules_and_inputs(scenario, "optimal"))
    for key, info in optimal.by_patient_day.items():
        assert len(info["slots"]) <= len(greedy.by_patient_day.get(key, {"slots": []})["slots"])


@SETTINGS
@given(centres)
def test_no_stage_crashes(p):
    for strategy in ("greedy", "optimal"):
        _, t, _ = run(_scenario(p), strategy)
        assert [e for e in t.events if e.outcome == trace.ERROR] == []


@SETTINGS
@given(centres)
def test_optimal_is_deterministic(p):
    scenario = _scenario(p)
    assert run(scenario, "optimal")[0] == run(scenario, "optimal")[0]


def _schedules_and_inputs(scenario, strategy):
    schedules, _, inputs = run(scenario, strategy)
    return schedules, inputs
