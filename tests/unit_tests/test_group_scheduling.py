"""
groupScheduling.py tests. Keeping activity/patient counts small here (<=3 activities,
<=5 patients) on purpose - bruteForceGroupScheduling backtracks, gets slow fast otherwise.
"""

from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pandas as pd

from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from tests.utils.scheduler_config import make_scheduler_config


def _empty_group_preference_df():
    return pd.DataFrame({
        "CentreActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"),
        "IsLike": pd.Series([], dtype="int64"),
    })


def _empty_group_recommendation_df():
    return pd.DataFrame({
        "CentreActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"),
        "DoctorRecommendation": pd.Series([], dtype="int64"),
    })


def _empty_group_exclusion_df():
    return pd.DataFrame({
        "CentreActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"),
    })


@contextmanager
def _patch_group_views(patient_ids, group_activity_df, preference_df=None, recommendation_df=None, exclusion_df=None):
    patients_df = pd.DataFrame({"PatientID": patient_ids})
    with ExitStack() as stack:
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.PatientsOnlyView.get_data", return_value=patients_df
        ))
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.GroupActivitiesOnlyView.get_data", return_value=group_activity_df
        ))
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.GroupActivitiesPreferenceView.get_data",
            return_value=preference_df if preference_df is not None else _empty_group_preference_df(),
        ))
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.GroupActivitiesRecommendationView.get_data",
            return_value=recommendation_df if recommendation_df is not None else _empty_group_recommendation_df(),
        ))
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.GroupActivitiesExclusionView.get_data",
            return_value=exclusion_df if exclusion_df is not None else _empty_group_exclusion_df(),
        ))
        yield


def _empty_patient_schedules(patient_ids, open_days, slots_per_day):
    return {pid: [["" for _ in range(slots_per_day)] for _ in open_days] for pid in patient_ids}


def _group_config(target_weekly=0):
    """TARGET_WEEKLY_GROUP_ACTIVITIES=0 disables the top-up round, isolating min-size logic."""
    return make_scheduler_config(
        OPEN_DAYS=["Monday", "Tuesday", "Wednesday"],
        SLOTS_PER_DAY={"Monday": 8, "Tuesday": 8, "Wednesday": 8},
        TARGET_WEEKLY_GROUP_ACTIVITIES=target_weekly,
    )


def _scheduled_bins(result, patient_id, activity_title):
    return [bin_ for bin_ in result[patient_id] if bin_[0] == activity_title]


class TestGroupScheduling:
    def test_min_size_met_by_recommended_patients(self, monkeypatch):
        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
            "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [2], "MinDuration": [30],
        })
        recommendation_df = pd.DataFrame({
            "CentreActivityID": [1, 1], "PatientID": [1, 2], "DoctorRecommendation": [1, 1],
        })
        patient_schedules = _empty_patient_schedules([1, 2], cfg["OPEN_DAYS"], 8)

        with _patch_group_views([1, 2], group_activity_df, recommendation_df=recommendation_df):
            result = GroupActivityScheduler.fillSchedule(patient_schedules)

        assert len(_scheduled_bins(result, 1, "Mahjong")) == 1
        assert len(_scheduled_bins(result, 2, "Mahjong")) == 1

    def test_shortfall_filled_from_least_booked_leftover_patients(self, monkeypatch):
        """MinPeopleReq=3, only patient 1 recommended -> shortfall filled from the 4
        leftover patients with the lowest activity count (tied at 0, so lowest IDs win)."""
        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
            "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [3], "MinDuration": [30],
        })
        recommendation_df = pd.DataFrame({
            "CentreActivityID": [1], "PatientID": [1], "DoctorRecommendation": [1],
        })
        patient_ids = [1, 2, 3, 4, 5]
        patient_schedules = _empty_patient_schedules(patient_ids, cfg["OPEN_DAYS"], 8)

        with _patch_group_views(patient_ids, group_activity_df, recommendation_df=recommendation_df):
            result = GroupActivityScheduler.fillSchedule(patient_schedules)

        assert len(_scheduled_bins(result, 1, "Mahjong")) == 1
        assert len(_scheduled_bins(result, 2, "Mahjong")) == 1
        assert len(_scheduled_bins(result, 3, "Mahjong")) == 1
        assert len(_scheduled_bins(result, 4, "Mahjong")) == 0
        assert len(_scheduled_bins(result, 5, "Mahjong")) == 0

    def test_shortfall_not_met_activity_is_dropped(self, monkeypatch):
        """MinPeopleReq=3, only patient 1 recommended, and excluding everyone else leaves
        no leftover patients to cover the shortfall -> activity is never scheduled."""
        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
            "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [3], "MinDuration": [30],
        })
        recommendation_df = pd.DataFrame({
            "CentreActivityID": [1], "PatientID": [1], "DoctorRecommendation": [1],
        })
        exclusion_df = pd.DataFrame({
            "CentreActivityID": [1, 1], "PatientID": [2, 3],
        })
        patient_ids = [1, 2, 3]
        patient_schedules = _empty_patient_schedules(patient_ids, cfg["OPEN_DAYS"], 8)

        with _patch_group_views(patient_ids, group_activity_df, recommendation_df=recommendation_df, exclusion_df=exclusion_df):
            result = GroupActivityScheduler.fillSchedule(patient_schedules)

        for pid in patient_ids:
            assert len(_scheduled_bins(result, pid, "Mahjong")) == 0

    def test_zero_preference_activity_scheduled_in_second_round(self, monkeypatch):
        """An activity with no recommended/preferred patients at all still gets scheduled
        in the second round, filled from least-booked patients."""
        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
            "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [2], "MinDuration": [30],
        })
        patient_ids = [1, 2, 3]
        patient_schedules = _empty_patient_schedules(patient_ids, cfg["OPEN_DAYS"], 8)

        with _patch_group_views(patient_ids, group_activity_df):
            result = GroupActivityScheduler.fillSchedule(patient_schedules)

        scheduled_count = sum(1 for pid in patient_ids if _scheduled_bins(result, pid, "Mahjong"))
        assert scheduled_count == 2  # exactly MinPeopleReq patients picked

    def test_excluded_patient_wins_over_recommendation(self, monkeypatch):
        """A patient both recommended AND excluded for the same activity is not scheduled, the
        exclusion takes precedence."""
        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
            "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [1], "MinDuration": [30],
        })
        recommendation_df = pd.DataFrame({
            "CentreActivityID": [1], "PatientID": [1], "DoctorRecommendation": [1],
        })
        exclusion_df = pd.DataFrame({"CentreActivityID": [1], "PatientID": [1]})
        patient_ids = [1, 2]
        patient_schedules = _empty_patient_schedules(patient_ids, cfg["OPEN_DAYS"], 8)

        with _patch_group_views(patient_ids, group_activity_df, recommendation_df=recommendation_df, exclusion_df=exclusion_df):
            result = GroupActivityScheduler.fillSchedule(patient_schedules)

        assert len(_scheduled_bins(result, 1, "Mahjong")) == 0

    def test_get_fixed_time_arr_always_returns_empty_list(self, monkeypatch):
        """
        (BUG) fixed group time slots are not recognised
        because the code compares string values like "0-2" with tuples like (0, 2).
        As a result, fixed group activities cannot be scheduled.
        """
        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        assert GroupActivityScheduler.getFixedTimeArr("0-2") == []

    def test_fixed_group_activity_is_never_scheduled(self, monkeypatch):
        """Full fillSchedule confirmation of the getFixedTimeArr bug: an IsFixed=1
        activity is never scheduled for anyone, even with enough recommended patients."""
        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Fixed Group Activity"],
            "IsFixed": [1], "FixedTimeSlots": ["0-2"], "MinPeopleReq": [2], "MinDuration": [30],
        })
        recommendation_df = pd.DataFrame({
            "CentreActivityID": [1, 1], "PatientID": [1, 2], "DoctorRecommendation": [1, 1],
        })
        patient_ids = [1, 2]
        patient_schedules = _empty_patient_schedules(patient_ids, cfg["OPEN_DAYS"], 8)

        with _patch_group_views(patient_ids, group_activity_df, recommendation_df=recommendation_df):
            result = GroupActivityScheduler.fillSchedule(patient_schedules)

        for pid in patient_ids:
            assert len(_scheduled_bins(result, pid, "Fixed Group Activity")) == 0

    def test_pre_occupied_slot_marked_unavailable(self, monkeypatch):
        """Checks that a group activity is not scheduled in a slot that already contains another activity for the patient."""
        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
            "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [1], "MinDuration": [30],
        })
        recommendation_df = pd.DataFrame({
            "CentreActivityID": [1], "PatientID": [1], "DoctorRecommendation": [1],
        })
        patient_ids = [1]
        patient_schedules = _empty_patient_schedules(patient_ids, cfg["OPEN_DAYS"], 8)
        # pre-fill every mapped group timeslot's starting sub-slot for patient 1
        for day, hour in cfg["GROUP_TIMESLOT_MAPPING"]:
            patient_schedules[1][day][hour] = "Pre-Existing Activity"

        with _patch_group_views(patient_ids, group_activity_df, recommendation_df=recommendation_df):
            result = GroupActivityScheduler.fillSchedule(patient_schedules)

        # every bin should be marked unavailable ("-") since all mapped slots were pre-occupied
        assert all(bin_[0] == "-" for bin_ in result[1])

    def test_top_up_round_adds_patient_below_target(self, monkeypatch):
        cfg = _group_config(target_weekly=1)
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)

        group_activity_df = pd.DataFrame({
            "ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mahjong"],
            "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [1], "MinDuration": [30],
        })
        recommendation_df = pd.DataFrame({
            "CentreActivityID": [1], "PatientID": [1], "DoctorRecommendation": [1],
        })
        patient_ids = [1, 2]
        patient_schedules = _empty_patient_schedules(patient_ids, cfg["OPEN_DAYS"], 8)

        with _patch_group_views(patient_ids, group_activity_df, recommendation_df=recommendation_df):
            result = GroupActivityScheduler.fillSchedule(patient_schedules)

        # patient 2 wasn't recommended, but is below TARGET_WEEKLY_GROUP_ACTIVITIES=1 and
        # the only scheduled activity has room, so top-up adds them too.
        assert len(_scheduled_bins(result, 1, "Mahjong")) == 1
        assert len(_scheduled_bins(result, 2, "Mahjong")) == 1
