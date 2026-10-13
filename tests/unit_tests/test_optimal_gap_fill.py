"""PreferredActivityScheduler with GAP_FILL_STRATEGY="optimal"."""

import datetime
from unittest.mock import patch

import pandas as pd

from pear_schedule.scheduler import trace
from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler
from tests.utils.scheduler_config import make_scheduler_config

WEEK_START = datetime.datetime(2024, 3, 18)


def _activities(rows):
    # rows: (id, title, minutes, fixed slots)
    return pd.DataFrame({
        "ActivityID": [r[0] for r in rows], "ActivityTitle": [r[1] for r in rows],
        "FixedTimeSlots": [r[3] if len(r) > 3 else "" for r in rows],
        "MinDuration": [r[2] for r in rows], "MaxDuration": [r[2] for r in rows],
    })


def _fill(monkeypatch, schedule, rows, strategy="optimal", likes=(), dislikes=(), exclusions=None, days=1):
    open_days = ["Monday", "Tuesday", "Wednesday"][:days]
    cfg = make_scheduler_config(OPEN_DAYS=open_days, SLOTS_PER_DAY={d: len(schedule[0]) for d in open_days},
                                GAP_FILL_STRATEGY=strategy)
    monkeypatch.setattr(PreferredActivityScheduler, "config", cfg, raising=False)
    monkeypatch.setattr(pd.DataFrame, "sample", lambda self, frac=1: self)  # deterministic greedy
    schedules = {1: [list(d) for d in schedule]}
    patients = {1: {"exclusions": exclusions or {}, "preferences": set(likes), "dispreferences": set(dislikes)}}
    with trace.tracing() as t, patch("pear_schedule.db_utils.views.ActivitiesView.get_data", return_value=_activities(rows)):
        PreferredActivityScheduler.fillPreferences(schedules, patients=patients, week_start=WEEK_START)
    return schedules[1], t


class TestOptimalGapFill:
    def test_fills_what_greedy_leaves_as_free_and_easy(self, monkeypatch):
        """Greedy puts the 30 min one first and strands both gaps."""
        rows = [(1, "Chess", 30), (2, "Gardening", 60)]
        greedy, _ = _fill(monkeypatch, [["", "", "Lunch", ""]], rows, strategy="greedy")
        optimal, _ = _fill(monkeypatch, [["", "", "Lunch", ""]], rows)

        assert greedy[0].count("Free and Easy") == 2
        assert optimal[0] == ["Gardening", "Gardening", "Lunch", "Chess"]

    def test_no_repeats_dislikes_or_exclusions(self, monkeypatch):
        rows = [(1, "Chess", 30), (2, "Puzzles", 30), (3, "Karaoke", 30)]
        sched, _ = _fill(monkeypatch, [["", "", "", ""]], rows, dislikes={2}, exclusions={3: None})
        assert sched[0] == ["Chess", "Free and Easy", "Free and Easy", "Free and Easy"]

    def test_exclusion_only_on_its_days(self, monkeypatch):
        rows = [(1, "Chess", 30)]
        sched, _ = _fill(monkeypatch, [[""], [""]], rows, days=2,
                         exclusions={1: datetime.datetime(2024, 3, 18, 23, 59)})
        assert sched == [["Free and Easy"], ["Chess"]]

    def test_fixed_activity_only_at_its_slot(self, monkeypatch):
        rows = [(1, "Yoga", 30, "0-1")]
        sched, _ = _fill(monkeypatch, [["", ""]], rows)
        assert sched[0] == ["Free and Easy", "Yoga"]

    def test_liked_activity_wins_a_tie(self, monkeypatch):
        rows = [(1, "Chess", 30), (2, "Puzzles", 30)]
        sched, _ = _fill(monkeypatch, [[""]], rows, likes={2})
        assert sched[0] == ["Puzzles"]

    def test_spreads_activities_across_the_week(self, monkeypatch):
        """Greedy gives Chess both days, optimal mixes it up."""
        rows = [(1, "Chess", 30), (2, "Puzzles", 30)]
        greedy, _ = _fill(monkeypatch, [[""], [""]], rows, strategy="greedy", days=2)
        optimal, _ = _fill(monkeypatch, [[""], [""]], rows, days=2)
        assert greedy == [["Chess"], ["Chess"]]
        assert sorted(d[0] for d in optimal) == ["Chess", "Puzzles"]

    def test_free_and_easy_is_traced_with_a_data_reason(self, monkeypatch):
        rows = [(1, "Gardening", 60), (2, "Sewing", 60)]
        _, t = _fill(monkeypatch, [["", "Lunch", "", ""]], rows)
        fe = [e for e in t.events if e.outcome == trace.FREE_AND_EASY]
        assert [(e.slot, e.reason) for e in fe] == [(0, "no_fit_for_gap_length")]
        assert all(e.details["strategy"] == "optimal" for e in fe)

    def test_unknown_strategy_falls_back_to_greedy(self, monkeypatch, caplog):
        rows = [(1, "Chess", 30), (2, "Gardening", 60)]
        sched, _ = _fill(monkeypatch, [["", "", "Lunch", ""]], rows, strategy="bogus")
        assert sched[0].count("Free and Easy") == 2
        assert "Unknown GAP_FILL_STRATEGY" in caplog.text
