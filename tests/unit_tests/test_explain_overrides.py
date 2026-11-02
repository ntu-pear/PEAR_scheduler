"""Trace reasons for decisions that follow the rules but can look like bugs."""

import datetime
from unittest.mock import patch

import pandas as pd

from pear_schedule.scheduler import trace
from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler, RecommendedRoutineActivityScheduler
from tests.unit_tests.test_group_scheduling import _empty_patient_schedules, _group_config, _patch_group_views
from tests.unit_tests.test_individual_schedule import _patch_recommended_stage
from tests.unit_tests.test_trace import _run_pipeline
from tests.utils.scheduler_config import make_scheduler_config

WEEK_START = datetime.datetime(2024, 3, 18)
MAHJONG = pd.DataFrame({
    "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
    "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [2], "MinDuration": [30],
})


def _group_reasons(monkeypatch, patient_ids, target_weekly=0, **views):
    cfg = _group_config(target_weekly=target_weekly)
    monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)
    with trace.tracing() as t, _patch_group_views(patient_ids, MAHJONG, **views):
        GroupActivityScheduler.fillSchedule(_empty_patient_schedules(patient_ids, cfg["OPEN_DAYS"], 8))
    return {pid: reason for (_, pid, _), reason in t.reasons.items()}


class TestGroupReasons:
    def test_recommended_over_dislike(self, monkeypatch):
        reasons = _group_reasons(
            monkeypatch, [1, 2],
            recommendation_df=pd.DataFrame({"CentreActivityID": [1, 1], "PatientID": [1, 2], "DoctorRecommendation": [1, 1]}),
            preference_df=pd.DataFrame({"CentreActivityID": [1], "PatientID": [1], "IsLike": [-1]}),
        )
        assert reasons == {1: "recommended_over_dislike", 2: "recommended"}

    def test_liked_and_filled_to_min_size(self, monkeypatch):
        reasons = _group_reasons(
            monkeypatch, [1, 2],
            preference_df=pd.DataFrame({"CentreActivityID": [1], "PatientID": [1], "IsLike": [1]}),
        )
        assert reasons == {1: "liked", 2: "filled_to_min_size"}

    def test_top_up_to_weekly_target(self, monkeypatch):
        reasons = _group_reasons(
            monkeypatch, [1, 2, 3], target_weekly=1,
            recommendation_df=pd.DataFrame({"CentreActivityID": [1, 1], "PatientID": [1, 2], "DoctorRecommendation": [1, 1]}),
        )
        assert reasons[3] == "top_up_to_weekly_target"

    def test_placement_event_carries_the_reason(self, monkeypatch):
        # the mocked pipeline recommends Mahjong to both patients
        t = trace.ScheduleTrace()
        _run_pipeline(monkeypatch, outer_trace=t)
        group = [e for e in t.events if e.stage == trace.STAGE_GROUP and e.outcome == trace.PLACED]
        assert group and all(e.reason == "recommended" for e in group)


class TestRecommendedReasons:
    def _run(self, monkeypatch, recs, **views):
        cfg = make_scheduler_config(OPEN_DAYS=["Monday", "Tuesday"], SLOTS_PER_DAY={"Monday": 4, "Tuesday": 4})
        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", cfg, raising=False)
        schedules = {1: [["", "", "", ""], ["", "", "", ""]]}
        with trace.tracing() as t, _patch_recommended_stage(recs, **views):
            RecommendedRoutineActivityScheduler.fillSchedule(schedules, week_start=WEEK_START)
        return schedules, [(e.outcome, e.reason, e.activity) for e in t.events]

    def _recs(self, fixed):
        return pd.DataFrame({
            "ActivityID": [7], "IsFixed": [1 if fixed else 0], "MinDuration": [30], "ActivityTitle": ["Physio"],
            "FixedTimeSlots": [fixed], "PatientID": [1], "ActivityEndDate": [pd.Timestamp("2099-12-31")],
        })

    def test_recommended_over_dislike(self, monkeypatch):
        disliked = pd.DataFrame({"PatientID": [1], "DispreferredActivityID": [7], "ActivityEndDate": [pd.Timestamp("2099-12-31")]})
        for fixed in ("0-1", ""):
            _, events = self._run(monkeypatch, self._recs(fixed), unpreferred_df=disliked)
            assert ("PLACED", "recommended_over_dislike", "Physio") in events

    def test_excluded_recommendation_says_excluded(self, monkeypatch):
        excluded = pd.DataFrame({
            "ActivityExclusionID": [1], "ActivityID": [7], "PatientID": [1], "ExclusionRemarks": [""],
            "EndDateTime": [pd.Timestamp("2099-12-31")], "ActivityTitle": ["Physio"],
        })
        for fixed in ("0-1", ""):
            schedules, events = self._run(monkeypatch, self._recs(fixed), excluded_df=excluded)
            assert ("DROPPED", "excluded", "Physio") in events
            assert "Physio" not in sum(schedules[1], [])


class TestLikedNotPlaced:
    def _fill(self, monkeypatch, schedule, activities, patient):
        cfg = make_scheduler_config(OPEN_DAYS=["Monday"], SLOTS_PER_DAY={"Monday": len(schedule[0])})
        monkeypatch.setattr(PreferredActivityScheduler, "config", cfg, raising=False)
        monkeypatch.setattr(pd.DataFrame, "sample", lambda self, frac=1: self)
        with trace.tracing() as t, patch("pear_schedule.db_utils.views.ActivitiesView.get_data", return_value=activities):
            PreferredActivityScheduler.fillPreferences({1: schedule}, patients={1: patient}, week_start=WEEK_START)
        return {e.activity: e.reason for e in t.events if e.outcome == trace.SKIPPED}

    def _acts(self, rows):
        return pd.DataFrame({
            "ActivityID": [r[0] for r in rows], "ActivityTitle": [r[1] for r in rows],
            "FixedTimeSlots": [r[3] for r in rows], "MinDuration": [r[2] for r in rows], "MaxDuration": [r[2] for r in rows],
        })

    def _patient(self, **kw):
        return {"exclusions": {}, "preferences": set(), "dispreferences": set(), "not_recommended": set(), **kw}

    def test_each_reason(self, monkeypatch):
        acts = self._acts([
            (1, "NotRec", 30, ""), (2, "Excluded", 30, ""), (3, "FixedAtLunch", 30, "0-0"),
            (4, "TooLong", 60, ""), (5, "LikedA", 30, ""),
        ])
        patient = self._patient(
            preferences={1, 2, 3, 4, 5}, exclusions={1: None, 2: None}, not_recommended={1},
        )
        reasons = self._fill(monkeypatch, [["Lunch", "", "Lunch"]], acts, patient)
        assert reasons == {
            "NotRec": "liked_but_not_recommended",
            "Excluded": "liked_but_excluded",
            "FixedAtLunch": "liked_but_fixed_time_taken",
            "TooLong": "liked_but_no_gap_long_enough",
        }

    def test_gaps_used_by_other_likes(self, monkeypatch):
        acts = self._acts([(1, "A", 30, ""), (2, "B", 30, "")])
        reasons = self._fill(monkeypatch, [["", "Lunch"]], acts, self._patient(preferences={1, 2}))
        assert reasons == {"B": "liked_but_gaps_used"}
