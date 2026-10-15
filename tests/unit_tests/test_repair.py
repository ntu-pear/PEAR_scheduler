"""
Regenerate in repair mode: only what a reason forces changes. Pure, no DB.
"""

import copy
import datetime

import pytest

from pear_schedule.scheduler import trace
from pear_schedule.scheduler.gapFill import PoolActivity
from pear_schedule.scheduler.invariants import FREE_AND_EASY, PatientRules, RuleInputs
from pear_schedule.scheduler.repair import Group, Rec, RepairData, locked_slots, repair_week, saved_grid
from tests.utils.scheduler_config import make_scheduler_config

WEEK = datetime.datetime(2024, 3, 18)  # Monday
FE = FREE_AND_EASY
FAR = datetime.datetime(2099, 1, 1)


def _data(patients=(1, 2, 3), **kw) -> RepairData:
    inputs = RuleInputs(
        slots_per_day=[6, 6],
        min_activity_duration=30,
        week_start=WEEK,
        pool=[
            PoolActivity(1, "Puzzles", 30), PoolActivity(2, "Reading", 30), PoolActivity(3, "Gardening", 60),
            PoolActivity(4, "Music", 30), PoolActivity(5, "Board games", 30), PoolActivity(6, "Walk", 30),
        ],
        patients={p: PatientRules() for p in patients},
        compulsory=[PoolActivity(-1, "Exercise", 30, frozenset({(0, 0), (1, 0)}))],
        activity_ids_by_title={"Puzzles": 1, "Reading": 2, "Gardening": 3, "Music": 4, "Board games": 5, "Walk": 6,
                               "Mahjong": 20},
    )
    return RepairData(inputs=inputs, patient_ids=list(patients), **kw)


def _build(data):
    """A week from scratch, like Monday's generate."""
    return repair_week({p: None for p in data.patient_ids}, data, set())


def _events(fn):
    with trace.tracing() as t:
        out = fn()
    return out, [(e.outcome, e.reason, e.activity, e.patient_id) for e in t.events]


def _diff(a, b):
    return {(p, d, s) for p in a for d, day in enumerate(a[p]) for s, v in enumerate(day) if b[p][d][s] != v}


class TestNoReason:
    def test_same_data_changes_nothing(self):
        data = _data()
        week = _build(data)
        assert repair_week(copy.deepcopy(week), data, set()) == week

    def test_new_like_changes_nothing(self):
        data = _data()
        week = _build(data)
        data.inputs.patients[1].likes.add(6)
        assert repair_week(copy.deepcopy(week), data, set()) == week


class TestRemovals:
    def _gap_title(self, week, pid, day):
        return next(t for t in week[pid][day] if t not in (FE, "Exercise"))

    def test_new_exclusion_only_touches_that_patient_and_day(self):
        data = _data()
        week = _build(data)
        t = self._gap_title(week, 1, 1)
        data.inputs.patients[1].exclusions[data.inputs.activity_id(t)] = WEEK + datetime.timedelta(days=1, hours=23)
        out, events = _events(lambda: repair_week(copy.deepcopy(week), data, set()))
        assert t not in out[1][1]
        assert {p for p, _, _ in _diff(week, out)} == {1}
        assert {d for _, d, _ in _diff(week, out)} == {1}
        assert ("DROPPED", "excluded", t, 1) in events

    def test_new_dislike_removes_it_all_week(self):
        data = _data()
        week = _build(data)
        t = self._gap_title(week, 2, 0)
        data.inputs.patients[2].dislikes.add(data.inputs.activity_id(t))
        out = repair_week(copy.deepcopy(week), data, set())
        assert all(t not in day for day in out[2])
        assert out[1] == week[1] and out[3] == week[3]

    def test_not_recommended_is_removed(self):
        data = _data()
        week = _build(data)
        t = self._gap_title(week, 3, 0)
        data.inputs.patients[3].not_recommended.add(data.inputs.activity_id(t))
        assert all(t not in day for day in repair_week(copy.deepcopy(week), data, set())[3])

    def test_deleted_activity_is_removed(self):
        data = _data()
        week = _build(data)
        week[1][0][4] = "Old activity"
        out, events = _events(lambda: repair_week(copy.deepcopy(week), data, set()))
        assert "Old activity" not in out[1][0]
        assert ("DROPPED", "activity_gone", "Old activity", 1) in events

    def test_repeat_in_a_day_is_removed(self):
        data = _data()
        week = _build(data)
        t = self._gap_title(week, 1, 0)
        free = [s for s, v in enumerate(week[1][0]) if v != t and v != "Exercise"][-1]
        week[1][0][free] = t if data.inputs.activity_id(t) != 3 else week[1][0][free]
        out = repair_week(copy.deepcopy(week), data, set())
        assert sum(1 for s, v in enumerate(out[1][0]) if v == t and (s == 0 or out[1][0][s - 1] != t)) == 1

    def test_adhoc_activity_is_kept_even_if_disliked(self):
        data = _data(adhoc_new={(1, 0, "Walk")})
        week = _build(data)
        week[1][0][5] = "Walk"
        data.inputs.patients[1].dislikes.add(6)
        assert repair_week(copy.deepcopy(week), data, set())[1][0][5] == "Walk"


class TestAdditions:
    def test_new_recommendation_goes_in_once(self):
        data = _data()
        week = _build(data)
        data.recommended[1] = [Rec(6, "Walk", 1)]
        data.inputs.patients[1].recommended.add(6)
        already = any("Walk" in day for day in week[1])
        out = repair_week(copy.deepcopy(week), data, set())
        runs = sum(1 for day in out[1] for s, v in enumerate(day) if v == "Walk" and (s == 0 or day[s - 1] != "Walk"))
        assert runs >= 1 and (already or runs == 1)
        assert out[2] == week[2] and out[3] == week[3]

    def test_fixed_recommendation_with_no_room_waits(self):
        data = _data()
        week = _build(data)
        data.recommended[1] = [Rec(7, "Physio", 1, frozenset({(0, 0)}))]  # Exercise is there
        out, events = _events(lambda: repair_week(copy.deepcopy(week), data, set()))
        assert out == week
        assert ("SKIPPED", "no_room_this_week", "Physio", 1) in events

    def test_compulsory_time_change_applies_from_today(self):
        data = _data()
        week = _build(data)
        data.inputs.compulsory = [PoolActivity(-1, "Exercise", 30, frozenset({(0, 3), (1, 3)}))]
        out = repair_week(copy.deepcopy(week), data, set())
        for p in (1, 2, 3):
            assert out[p][0][3] == "Exercise" and out[p][1][3] == "Exercise"
            assert out[p][0][0] != "Exercise"

    def test_compulsory_clash_is_left_alone(self):
        data = _data()
        week = _build(data)
        data.inputs.compulsory.append(PoolActivity(-2, "Talk", 30, frozenset({(0, 0)})))
        out, events = _events(lambda: repair_week(copy.deepcopy(week), data, set()))
        assert out == week
        assert ("SKIPPED", "set_time_taken", "Talk", 1) in events

    def test_new_routine_at_its_time(self):
        data = _data()
        week = _build(data)
        data.routines[2] = {(1, 4): (6, "Walk")}
        out = repair_week(copy.deepcopy(week), data, set())
        assert out[2][1][4] == "Walk"
        assert out[1] == week[1] and out[3] == week[3]

    def test_new_patient_gets_a_full_week(self):
        data = _data()
        week = _build(data)
        data = _data(patients=(1, 2, 3, 4))
        saved = {**copy.deepcopy(week), 4: None}
        out = repair_week(saved, data, set())
        assert out[4][0][0] == "Exercise" and FE not in out[4][0][1:4]
        assert all(out[p] == week[p] for p in (1, 2, 3))


class TestLocked:
    def test_past_and_started_slots_never_change(self):
        data = _data()
        week = _build(data)
        data.inputs.patients[1].dislikes.update({1, 2, 3, 4, 5, 6})
        locked = {(0, s) for s in range(6)} | {(1, 0), (1, 1)}
        out = repair_week(copy.deepcopy(week), data, locked)
        assert out[1][0] == week[1][0] and out[1][1][:2] == week[1][1][:2]
        # only an activity that already started at 09:30 can carry on past it
        for s in range(2, 6):
            v = out[1][1][s]
            assert v == FE or (v == week[1][1][1] and all(out[1][1][k] == v for k in range(1, s + 1)))


    def test_started_activity_is_not_cut_by_something_new(self):
        data = _data()
        week = _build(data)
        week[1][1][1:3] = ["Gardening", "Gardening"]
        data.inputs.compulsory.append(PoolActivity(-2, "Talk", 30, frozenset({(1, 2)})))
        out = repair_week(copy.deepcopy(week), data, {(0, s) for s in range(6)} | {(1, 0), (1, 1)})
        assert out[1][1][1:3] == ["Gardening", "Gardening"]


class TestGroups:
    def _with_session(self, members, min_size=2, **kw):
        data = _data(groups={"Mahjong": Group(20, "Mahjong", 2, min_size)}, **kw)
        week = _build(data)
        for p in members:
            week[p][0][2:4] = ["Mahjong", "Mahjong"]
            # one fill may have been cut in half
            for s in (1, 4):
                if week[p][0][s] == "Gardening":
                    week[p][0][s] = FE
        # make the week consistent before the change
        return data, repair_week(copy.deepcopy(week), data, set())

    def test_stable_session_is_kept(self):
        data, week = self._with_session([1, 2])
        assert repair_week(copy.deepcopy(week), data, set()) == week

    def test_member_leaves_and_someone_tops_up(self):
        data, week = self._with_session([1, 2], group_blocked={"Mahjong": set()})
        data.group_blocked["Mahjong"] = {1}
        out, events = _events(lambda: repair_week(copy.deepcopy(week), data, set()))
        assert "Mahjong" not in out[1][0]
        assert out[3][0][2:4] == ["Mahjong", "Mahjong"] and out[2][0][2:4] == ["Mahjong", "Mahjong"]
        assert ("PLACED", "group_top_up", "Mahjong", 3) in events

    def test_cancelled_when_nobody_can_top_up(self):
        data, week = self._with_session([1, 2])
        data.group_blocked["Mahjong"] = {1, 3}
        out, events = _events(lambda: repair_week(copy.deepcopy(week), data, set()))
        assert all("Mahjong" not in out[p][0] for p in (1, 2, 3))
        assert ("DROPPED", "group_below_min_size", "Mahjong", 2) in events
        assert FE not in out[2][0][2:4]  # freed slots get re-filled

    def test_new_group_recommendation_joins(self):
        data, week = self._with_session([1, 2])
        data.group_recommended["Mahjong"] = {3}
        out = repair_week(copy.deepcopy(week), data, set())
        assert out[3][0][2:4] == ["Mahjong", "Mahjong"]

    def test_new_patient_who_likes_it_joins(self):
        data, week = self._with_session([1, 2], group_liked={"Mahjong": {4}})
        data2 = _data(patients=(1, 2, 3, 4), groups=data.groups, group_liked=data.group_liked)
        out = repair_week({**copy.deepcopy(week), 4: None}, data2, set())
        assert out[4][0][2:4] == ["Mahjong", "Mahjong"]
        assert all(out[p] == week[p] for p in (1, 2, 3))


class TestHelpers:
    def test_locked_slots(self):
        cfg = make_scheduler_config(OPEN_DAYS=["Monday", "Tuesday", "Wednesday"],
                                    SLOTS_PER_DAY={d: 4 for d in ["Monday", "Tuesday", "Wednesday"]})
        now = datetime.datetime(2024, 3, 19, 9, 45)  # Tuesday, 09:30 slot started
        locked = locked_slots(cfg, WEEK, now)
        assert {(0, s) for s in range(4)} <= locked
        assert (1, 0) in locked and (1, 1) in locked and (1, 2) not in locked
        assert not any(d == 2 for d, _ in locked)

    def test_midnight_locks_only_past_days(self):
        cfg = make_scheduler_config()
        assert locked_slots(cfg, WEEK, datetime.datetime(2024, 3, 20, 0, 0)) == {(d, s) for d in (0, 1) for s in range(8)}

    def test_saved_grid_reads_the_day_json(self):
        cfg = make_scheduler_config(OPEN_DAYS=["Monday"], SLOTS_PER_DAY={"Monday": 2})
        row = {"Monday": '{"09:00-09:30": "Walk", "09:30-10:00": "Free and Easy"}'}
        assert saved_grid(row, cfg) == [["Walk", FE]]
