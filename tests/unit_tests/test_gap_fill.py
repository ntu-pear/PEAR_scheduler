"""scheduler/gapFill.py tests."""

import datetime

from pear_schedule.scheduler.gapFill import (
    Candidate, PoolActivity, build_candidates, is_valid, score, solve_day,
)

WEEK_START = datetime.datetime(2024, 3, 18)


def c(aid, length=1, starts=None, liked=False, bonus=0.0, title=None):
    return Candidate(aid, title or f"A{aid}", length, frozenset(starts) if starts is not None else None, liked, bonus)


class TestSolveDay:
    def test_fills_every_slot_when_possible(self):
        result = solve_day([True] * 4, [c(1, 2), c(2, 1), c(3, 1), c(4, 2)])
        assert result.score[0] == 4
        assert is_valid(result.assignment, [True] * 4)

    def test_beats_first_fit_greedy(self):
        """First fit strands slot 2, best is 30 min at 0 then 60 min at 1-2."""
        short_fixed_at_0 = c(1, 1, starts={0})
        long_any = c(2, 2)
        greedy = {0: long_any}
        result = solve_day([True] * 3, [long_any, short_fixed_at_0], seed=greedy)
        assert result.seed_score[0] == 2
        assert result.score[0] == 3
        assert result.assignment == {0: short_fixed_at_0, 1: long_any}

    def test_no_activity_used_twice(self):
        result = solve_day([True] * 3, [c(1, 1)])
        assert result.score[0] == 1

    def test_respects_occupied_slots_and_fixed_starts(self):
        free = [True, False, True, True]
        result = solve_day(free, [c(1, 2, starts={2}), c(2, 2)])
        assert result.assignment == {2: c(1, 2, starts={2})} or set(result.assignment) == {2}
        assert result.score[0] == 2
        assert is_valid(result.assignment, free)

    def test_prefers_liked_when_fill_is_tied(self):
        result = solve_day([True], [c(1), c(2, liked=True)])
        assert [x.activity_id for x in result.assignment.values()] == [2]

    def test_prefers_variety_when_fill_and_likes_are_tied(self):
        result = solve_day([True], [c(1, bonus=0.25), c(2, bonus=1.0)])
        assert [x.activity_id for x in result.assignment.values()] == [2]

    def test_fill_outranks_likes(self):
        # filling all 3 slots beats using the liked one
        free = [True] * 3
        result = solve_day(free, [c(1, 2, liked=True), c(2, 1), c(3, 1), c(4, 1)])
        assert result.score[0] == 3

    def test_invalid_seed_is_ignored(self):
        result = solve_day([True, False], [c(1, 1)], seed={1: c(1, 1)})
        assert result.seed_score is None
        assert result.score[0] == 1

    def test_budget_exhaustion_never_returns_worse_than_seed(self):
        cands = [c(i, 1 + (i % 2)) for i in range(1, 30)]
        seed = {0: cands[0]}
        result = solve_day([True] * 16, cands, seed=seed, node_budget=5)
        assert result.exhausted_budget
        assert result.score >= score(seed)

    def test_deterministic(self):
        cands = [c(i, 1 + (i % 2), bonus=1 / i) for i in range(1, 12)]
        a = solve_day([True] * 10, cands).assignment
        b = solve_day([True] * 10, list(reversed(cands))).assignment
        assert a == b


class TestBuildCandidates:
    POOL = [
        PoolActivity(1, "Walk", 30),
        PoolActivity(2, "Sewing", 60),
        PoolActivity(3, "Yoga", 30, frozenset({(0, 2), (1, 3)})),
        PoolActivity(4, "Chess", 30),
    ]

    def _build(self, day=0, **kw):
        args = dict(min_activity_duration=30, week_start=WEEK_START, exclusions={}, liked=set(),
                    blocked=set(), used_titles_today=set())
        args.update(kw)
        return {x.title: x for x in build_candidates(self.POOL, day, **args)}

    def test_lengths_and_fixed_starts(self):
        out = self._build()
        assert out["Sewing"].length == 2
        assert out["Yoga"].starts == frozenset({2})
        assert out["Walk"].starts is None

    def test_fixed_activity_without_a_slot_today_is_not_a_candidate(self):
        assert "Yoga" not in self._build(day=2)

    def test_blocked_used_and_excluded_are_removed(self):
        out = self._build(blocked={4}, used_titles_today={"Walk"},
                          exclusions={2: datetime.datetime(2024, 3, 18, 23, 59)})
        assert set(out) == {"Yoga"}

    def test_exclusion_with_no_end_date_applies(self):
        import pandas as pd
        assert "Sewing" not in self._build(day=3, exclusions={2: pd.NaT})

    def test_exclusion_ending_yesterday_does_not_apply(self):
        out = self._build(day=1, exclusions={2: datetime.datetime(2024, 3, 18, 23, 59)})
        assert "Sewing" in out

    def test_liked_and_variety_bonus(self):
        out = self._build(liked={1}, week_counts={"Chess": 3})
        assert out["Walk"].liked and not out["Chess"].liked
        assert out["Chess"].bonus < out["Walk"].bonus
