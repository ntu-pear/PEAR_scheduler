"""
Explaining the saved week without building it again. No DB.
"""

import copy
import datetime
from unittest.mock import patch

from pear_schedule.scheduler import explain, repair, trace
from pear_schedule.scheduler.repair import Group, Rec, repair_week
from tests.unit_tests.test_repair import FE, WEEK, _data
from tests.utils.scheduler_config import make_scheduler_config

CFG = make_scheduler_config(OPEN_DAYS=["Monday", "Tuesday"], SLOTS_PER_DAY={"Monday": 6, "Tuesday": 6})


def _reasons(t, pid):
    return {(e.day, e.slot): (e.stage, e.reason, e.activity) for e in t.events if e.patient_id == pid}


class TestSavedWeekTrace:
    def test_each_kind_gets_its_reason(self):
        data = _data(
            recommended={1: [Rec(7, "Physio", 1)]},
            routines={1: {(0, 1): (6, "Walk")}},
            groups={"Mahjong": Group(20, "Mahjong", 2, 2)},
            group_recommended={"Mahjong": {1}},
            adhoc_new={(1, 1, "Music")},
        )
        data.inputs.patients[1].likes.add(1)
        saved = {1: [["Exercise", "Walk", "Mahjong", "Mahjong", "Puzzles", "Reading"],
                     ["Exercise", "Music", "Physio", FE, FE, FE]], 2: None, 3: None}
        reasons = _reasons(explain.saved_week_trace(saved, data), 1)
        assert reasons[(0, 0)] == ("compulsory", "fixed_slot", "Exercise")
        assert reasons[(0, 1)] == ("recommended_routine", "routine_slot", "Walk")
        assert reasons[(0, 2)] == ("group", "recommended", "Mahjong")
        assert reasons[(0, 4)] == ("preferred", "preferred", "Puzzles")
        assert reasons[(0, 5)] == ("preferred", "neutral", "Reading")
        assert reasons[(1, 1)] == ("adhoc", "adhoc_request", "Music")
        assert reasons[(1, 2)] == ("recommended_routine", "doctor_recommended", "Physio")

    def test_every_slot_has_a_writer(self):
        data = _data()
        week = repair_week({p: None for p in data.patient_ids}, data, set())
        t = explain.saved_week_trace(week, data)
        assert all((p, d, s) in t.provenance for p in week for d, day in enumerate(week[p]) for s in range(len(day)))


class TestExplainSavedWeek:
    def _run(self, data, saved, changes=(), now=WEEK):
        with patch.object(repair, "load_repair_data", return_value=data), \
             patch.object(repair, "load_saved", return_value=saved), \
             patch.object(repair, "changes_this_week", return_value=list(changes)):
            return explain.explain_saved_week(CFG, now=now)

    def test_nothing_saved_means_none(self):
        assert self._run(_data(), {1: None, 2: None, 3: None}) is None

    def test_explains_what_is_saved_and_what_will_change(self):
        data = _data()
        week = repair_week({p: None for p in data.patient_ids}, data, set())
        title = next(t for t in week[1][1] if t not in (FE, "Exercise"))
        data.inputs.patients[1].exclusions[data.inputs.activity_id(title)] = None
        done = trace.TraceEvent("repair", 2, trace.DROPPED, "disliked", activity="Reading", day=0, slot=3,
                                details={"at": "2024-03-18T00:00"})
        out = self._run(data, copy.deepcopy(week), [done])

        assert out["source"] == "saved"
        assert [s["activity"] for s in out["patients"]["1"]["days"][1]["slots"]] == week[1][1]
        assert list(out["pending"]) == ["1"]
        assert any(e["reason"] == "excluded" and e["activity"] == title for e in out["pending"]["1"])
        assert any(e["stage"] == "repair" for e in out["patients"]["2"]["days"][0]["slots"][3]["events"])

    def test_passed_days_are_not_flagged(self):
        """Excluded after it was saved: Monday already passed, only Tuesday needs attention."""
        data = _data()
        week = repair_week({p: None for p in data.patient_ids}, data, set())
        title = next(t for t in week[1][0] if t not in (FE, "Exercise") and t in week[1][1])
        data.inputs.patients[1].exclusions[data.inputs.activity_id(title)] = None
        out = self._run(data, copy.deepcopy(week), now=WEEK + datetime.timedelta(days=1, hours=7))
        flagged = [v for v in out["patients"]["1"]["violations"] if v["rule"] == "R1"]
        assert flagged and {v["day"] for v in flagged} == {1}

    def test_what_if_on_the_saved_week(self):
        data = _data()
        week = repair_week({p: None for p in data.patient_ids}, data, set())
        with patch.object(repair, "load_repair_data", return_value=data), \
             patch.object(repair, "load_saved", return_value=copy.deepcopy(week)), \
             patch.object(repair, "changes_this_week", return_value=[]):
            out = explain.explain_saved_week(CFG, now=WEEK, with_what_if=True)
        assert out["what_if"]["free_and_easy"] == out["summary"]["free_and_easy"]["total"]
        assert all(o["fills"] or o["fills_rearranged"] for o in out["what_if"]["options"])
