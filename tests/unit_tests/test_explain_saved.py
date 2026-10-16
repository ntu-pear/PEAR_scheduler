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

    def test_rules_broken_since_the_save_are_named(self):
        data = _data(routines={1: {(0, 1): (6, "Walk")}})
        rules = data.inputs.patients[1]
        rules.dislikes.add(2)  # Reading, picked as neutral
        rules.exclusions[1] = None  # Puzzles, excluded with no end
        rules.not_recommended.add(5)  # Board games
        rules.exclusions[6] = None  # Walk is a routine, now excluded
        saved = {1: [["Exercise", "Walk", "Reading", "Puzzles", "Board games", FE],
                     ["Exercise", FE, FE, FE, FE, FE]], 2: None, 3: None}
        t = explain.saved_week_trace(saved, data)
        reasons = {}
        for e in t.events:
            if e.patient_id == 1:
                reasons.setdefault((e.day, e.slot), []).append(e.reason)
        assert reasons[(0, 2)] == ["now_disliked"]
        assert reasons[(0, 3)] == ["now_excluded"]
        assert reasons[(0, 4)] == ["now_not_recommended"]
        # a routine keeps its reason, the broken rule is added next to it
        assert reasons[(0, 1)] == ["routine_slot", "now_excluded"]

    def test_recommended_over_dislike_is_not_a_broken_rule(self):
        data = _data(recommended={1: [Rec(7, "Physio", 1)]})
        data.inputs.patients[1].dislikes.add(7)
        data.inputs.patients[1].recommended.add(7)
        data.inputs.activity_ids_by_title["Physio"] = 7
        saved = {1: [["Exercise", "Physio", FE, FE, FE, FE], ["Exercise", FE, FE, FE, FE, FE]], 2: None, 3: None}
        reasons = [e.reason for e in explain.saved_week_trace(saved, data).events if e.patient_id == 1 and e.slot == 1]
        assert reasons == ["recommended_over_dislike"]

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


class TestAdhocNotInTableYet:
    """The schedule has the request before activity service's ADHOC_CREATED reaches the ADHOC table."""

    def _load(self, adhoc_rows):
        import pandas as pd
        from pear_schedule.db_utils import views

        empty = pd.DataFrame()
        cols = {
            "RecommendedActivitiesView": empty, "ValidRoutineActivitiesView": empty,
            "GroupActivitiesOnlyView": empty, "GroupActivitiesExclusionView": empty,
            "GroupActivitiesRecommendationView": empty, "GroupActivitiesPreferenceView": empty,
            "PatientsOnlyView": pd.DataFrame({"PatientID": [1, 2, 3]}),
            "AdhocActivityView": pd.DataFrame(adhoc_rows),
        }
        patches = [patch.object(getattr(views, n), "get_data", return_value=df) for n, df in cols.items()]
        patches.append(patch.object(explain, "collect_rule_inputs", return_value=_data().inputs))
        for p in patches:
            p.start()
        try:
            return repair.load_repair_data(CFG, WEEK)
        finally:
            for p in patches:
                p.stop()

    def setup_method(self):
        repair._pending_adhoc.clear()

    def teardown_method(self):
        repair._pending_adhoc.clear()

    def test_pending_request_counts_as_adhoc(self):
        repair.record_adhoc(1, "Reading", "Music", WEEK.date() + datetime.timedelta(days=1), WEEK.date() + datetime.timedelta(days=1))
        data = self._load([])
        assert data.adhoc_new == {(1, 1, "Music")}
        assert data.adhoc_old[(1, 1, "Music")] == "Reading"

    def test_pending_request_is_not_a_rule_break(self):
        repair.record_adhoc(1, "Reading", "Music", WEEK.date() + datetime.timedelta(days=1), WEEK.date() + datetime.timedelta(days=1))
        data = self._load([])
        data.inputs.patients[1].dislikes.add(4)  # Music
        saved = {1: [["Exercise", FE, FE, FE, FE, FE], ["Exercise", "Music", FE, FE, FE, FE]], 2: None, 3: None}
        t = explain.saved_week_trace(saved, data)
        out = explain.build_explanation({1: saved[1]}, t, data.inputs, CFG)
        assert [v for v in out["patients"]["1"]["violations"] if v["activity"] == "Music"] == []
        event = next(e for e in t.events if e.reason == "adhoc_request")
        assert event.details == {"replaced": "Reading"}

    def test_dropped_once_the_table_has_it(self):
        day = WEEK + datetime.timedelta(days=1)
        repair.record_adhoc(1, "Reading", "Music", day.date(), day.date())
        self._load([{"PatientID": 1, "OldActivityTitle": "Reading", "NewActivityTitle": "Music", "StartDate": day, "EndDate": day}])
        assert repair._pending_adhoc == []

    def test_past_requests_are_forgotten(self):
        last_week = WEEK.date() - datetime.timedelta(days=7)
        repair.record_adhoc(1, "Reading", "Music", last_week, last_week)
        assert self._load([]).adhoc_new == set()
        assert repair._pending_adhoc == []

    def test_replaced_title_from_the_table(self):
        day = WEEK + datetime.timedelta(days=1)
        data = self._load([{"PatientID": 1, "OldActivityTitle": "Reading", "NewActivityTitle": "Music", "StartDate": day, "EndDate": day}])
        assert data.adhoc_old == {(1, 1, "Music"): "Reading"}


class TestGapFillStrategy:
    def test_saved_week_says_the_configured_strategy(self):
        data = _data()
        saved = {1: [["Exercise", FE, FE, FE, FE, FE], ["Exercise", FE, FE, FE, FE, FE]]}
        t = explain.saved_week_trace(saved, data)
        cfg = make_scheduler_config(OPEN_DAYS=["Monday", "Tuesday"], SLOTS_PER_DAY={"Monday": 6, "Tuesday": 6},
                                    GAP_FILL_STRATEGY="optimal")
        assert explain.build_explanation(saved, t, data.inputs, cfg)["gap_fill_strategy"] == "optimal"

    def test_unknown_strategy_reads_as_greedy(self):
        assert explain.gap_fill_strategy({"GAP_FILL_STRATEGY": "fast"}) == "greedy"
        assert explain.gap_fill_strategy({}) == "greedy"
