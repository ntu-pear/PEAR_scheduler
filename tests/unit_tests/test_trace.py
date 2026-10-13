"""
scheduler/trace.py. End-to-end cases reuse the mocked pipeline from test_build_schedules.
"""

import copy
import datetime
from unittest.mock import patch

import pandas as pd

from pear_schedule.scheduler import trace
from pear_schedule.scheduler.utils import build_schedules
from tests.unit_tests.test_build_schedules import SCHEDULER_CLASSES, _config, _freeze_now, _patch_all_views
from tests.utils.scheduler_config import make_scheduler_config


def _run_pipeline(monkeypatch, outer_trace=None):
    cfg = _config()
    for _, cls in SCHEDULER_CLASSES:
        monkeypatch.setattr(cls, "config", cfg, raising=False)
    schedules = {}
    with _freeze_now(monkeypatch), _patch_all_views():
        if outer_trace is None:
            build_schedules(cfg, schedules)
        else:
            with trace.tracing(outer_trace):
                build_schedules(cfg, schedules)
    return schedules


class TestTraceBasics:
    def test_record_is_a_no_op_without_an_active_trace(self):
        assert trace.current() is None
        trace.record(trace.STAGE_PREFERRED, 1, trace.PLACED, "preferred", activity="Walk")
        assert trace.current() is None

    def test_tracing_collects_events_and_resets(self):
        with trace.tracing() as t:
            trace.record(trace.STAGE_PREFERRED, 1, trace.PLACED, "preferred", activity="Walk", day=0, slot=2)
            assert trace.current() is t
        assert trace.current() is None
        assert len(t.events) == 1
        event = t.events[0]
        assert (event.patient_id, event.activity, event.day, event.slot) == (1, "Walk", 0, 2)

    def test_end_stage_records_which_stage_wrote_each_slot(self):
        t = trace.ScheduleTrace()
        schedules = {1: [["", ""]]}
        t.start_snapshot(schedules)
        schedules[1][0][0] = "Lunch"
        t.end_stage("compulsory", schedules)
        schedules[1][0][0] = "Walk"
        schedules[1][0][1] = "Free and Easy"
        t.end_stage("adhoc", schedules)

        prov = t.provenance_for(1)
        assert [(w.stage, w.activity, w.previous) for w in prov[(0, 0)]] == [
            ("compulsory", "Lunch", ""), ("adhoc", "Walk", "Lunch"),
        ]
        assert [(w.stage, w.activity) for w in prov[(0, 1)]] == [("adhoc", "Free and Easy")]

    def test_summary_counts_by_stage_and_outcome(self):
        with trace.tracing() as t:
            trace.record(trace.STAGE_PREFERRED, 1, trace.FREE_AND_EASY, "no_candidate_fits")
            trace.record(trace.STAGE_PREFERRED, 2, trace.FREE_AND_EASY, "no_candidate_fits")
            trace.record(trace.STAGE_GROUP, None, trace.DROPPED, "below_min_group_size")
        summary = t.summary()
        assert summary["by_outcome"]["preferred:FREE_AND_EASY"] == 2
        assert summary["by_reason"]["group:DROPPED:below_min_group_size"] == 1
        assert [e.reason for e in t.notable()] == ["below_min_group_size"]


class TestPipelineTrace:
    def test_tracing_does_not_change_the_schedule(self, monkeypatch):
        untraced = _run_pipeline(monkeypatch)
        traced = _run_pipeline(monkeypatch, outer_trace=trace.ScheduleTrace())
        assert traced == untraced

    def test_every_filled_slot_has_provenance(self, monkeypatch):
        t = trace.ScheduleTrace()
        schedules = _run_pipeline(monkeypatch, outer_trace=t)

        for pid, days in schedules.items():
            prov = t.provenance_for(pid)
            for d, day in enumerate(days):
                for s, activity in enumerate(day):
                    if activity:
                        assert (d, s) in prov, f"patient {pid} day {d} slot {s} ({activity}) has no provenance"
                        assert prov[(d, s)][-1].activity == activity

    def test_adhoc_replacement_is_traced_over_compulsory(self, monkeypatch):
        t = trace.ScheduleTrace()
        _run_pipeline(monkeypatch, outer_trace=t)

        stages = [w.stage for w in t.provenance_for(1)[(0, 0)]]
        assert stages[:2] == [trace.STAGE_COMPULSORY, trace.STAGE_ADHOC]
        replaced = [e for e in t.events_for(1) if e.outcome == trace.REPLACED]
        assert replaced and replaced[0].details["replaced"] == "Breathing+Vital Check"

    def test_free_and_easy_slots_carry_a_reason(self, monkeypatch):
        # no individual activities in the mock, every gap is Free and Easy
        t = trace.ScheduleTrace()
        schedules = _run_pipeline(monkeypatch, outer_trace=t)

        fe_events = {(e.day, e.slot) for e in t.events_for(2) if e.outcome == trace.FREE_AND_EASY}
        fe_slots = {(d, s) for d, day in enumerate(schedules[2]) for s, a in enumerate(day) if a.startswith("Free and Easy")}
        assert fe_slots and fe_slots == fe_events
        assert all(e.reason == "no_candidate_fits" for e in t.events_for(2) if e.outcome == trace.FREE_AND_EASY)

    def test_untraced_run_still_logs_a_summary(self, monkeypatch, caplog):
        caplog.set_level("INFO", logger="pear_schedule.scheduler.utils")
        _run_pipeline(monkeypatch)
        assert any("Schedule trace summary" in r.message for r in caplog.records)


class TestRoutineTrace:
    def _call_fill_routines(self, monkeypatch, schedule, routines, fixed_activities):
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        cfg = make_scheduler_config(OPEN_DAYS=["Monday"], SLOTS_PER_DAY={"Monday": 4})
        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", cfg, raising=False)
        with trace.tracing() as t:
            RecommendedRoutineActivityScheduler._RecommendedRoutineActivityScheduler__fillRoutines(
                schedule, fixed_activities, routines, {"exclusions": {}}, datetime.datetime(2024, 3, 18), patient_id=1,
            )
        return t

    def test_routine_blocked_by_compulsory_is_dropped_not_crashing(self, monkeypatch):
        """Compulsory in the routine's slot used to raise KeyError and abort the patient."""
        schedule = [["Lunch", "", "", ""]]
        routines = pd.DataFrame({"PatientID": [1], "ActivityID": [5], "ActivityTitle": ["Walk"], "FixedTimeSlots": ["0-0,0-2"]})
        no_fixed = pd.DataFrame(columns=["ActivityTitle", "FixedTimeSlots"])

        t = self._call_fill_routines(monkeypatch, schedule, routines, no_fixed)

        assert schedule[0] == ["Lunch", "", "Walk", ""]
        dropped = [e for e in t.events if e.outcome == trace.DROPPED]
        assert [(e.reason, e.details["occupied_by"]) for e in dropped] == [("routine_slot_held_by_higher_priority", "Lunch")]

    def test_routine_displacing_recommended_activity_is_traced_as_moved(self, monkeypatch):
        schedule = [["Physio", "", "", ""]]
        routines = pd.DataFrame({"PatientID": [1], "ActivityID": [5], "ActivityTitle": ["Walk"], "FixedTimeSlots": ["0-0"]})
        fixed = pd.DataFrame({"ActivityTitle": ["Physio"], "FixedTimeSlots": ["0-0,0-3"]})

        t = self._call_fill_routines(monkeypatch, schedule, routines, fixed)

        assert schedule[0] == ["Walk", "", "", "Physio"]
        moved = [e for e in t.events if e.outcome == trace.MOVED]
        assert [(e.activity, e.day, e.slot, e.details["from_slot"]) for e in moved] == [("Physio", 0, 3, 0)]


class TestGroupTrace:
    def test_group_activity_below_min_size_is_traced_as_dropped(self, monkeypatch):
        from tests.unit_tests.test_group_scheduling import _group_config, _empty_patient_schedules, _patch_group_views
        from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler

        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)
        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
            "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [3], "MinDuration": [30],
        })
        recommendation_df = pd.DataFrame({"CentreActivityID": [1], "PatientID": [1], "DoctorRecommendation": [1]})
        exclusion_df = pd.DataFrame({"CentreActivityID": [1, 1], "PatientID": [2, 3]})

        with trace.tracing() as t, _patch_group_views([1, 2, 3], group_activity_df,
                                                      recommendation_df=recommendation_df, exclusion_df=exclusion_df):
            GroupActivityScheduler.fillSchedule(_empty_patient_schedules([1, 2, 3], cfg["OPEN_DAYS"], 8))

        dropped = [e for e in t.events if e.outcome == trace.DROPPED]
        assert [(e.activity, e.reason, e.details["min_people"]) for e in dropped] == [("Mahjong", "below_min_group_size", 3)]
