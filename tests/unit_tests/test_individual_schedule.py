"""
Tests for individualScheduling.py - fixed/flexible/preferred activity placement,
exclusions, multi-slot fits, and the neutral/Free-and-Easy fallbacks.
"""


import datetime
import pandas as pd
from unittest.mock import patch, MagicMock
from pear_schedule.scheduler.individualScheduling import _get_max_enddate, calculate_activity_availabillity
from tests.utils.scheduler_config import make_scheduler_config

class TestUtils:
    def test_get_max_enddate(self):
        lo_dt = datetime.datetime.now()
        hi_dt = lo_dt + datetime.timedelta(days=1)
        assert _get_max_enddate(None, None) == None
        assert _get_max_enddate(None, lo_dt) == None
        assert _get_max_enddate(lo_dt, None) == None
        assert _get_max_enddate(lo_dt, hi_dt) == hi_dt


class FakeSchedulerCls:
    """Just enough of a cls stub to give calculate_activity_availabillity a config."""
    config = {
        "OPEN_DAYS": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "SLOTS_PER_DAY": {day: 8 for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
    }


class TestFixedRecommendedScheduling:
    """calculate_activity_availabillity - ranks how "constrained" a fixed-time-slot
    activity is at a given (day, slot)."""

    def test_slot_present_in_single_element_set_returns_tally_of_one(self):
        assert calculate_activity_availabillity(FakeSchedulerCls, 0, 2, {(0, 2)}) == 1

    def test_empty_processed_time_slots_returns_inf_not_1000(self):
        """(BUG) no fixed time slots -> should hit the "return 1000" branch per the code,
        but it actually returns inf because the check above it catches first. That branch
        is dead."""
        assert calculate_activity_availabillity(FakeSchedulerCls, 0, 2, set()) == float("inf")

    def test_slot_not_in_nonempty_set_returns_inf(self):
        assert calculate_activity_availabillity(FakeSchedulerCls, 0, 2, {(1, 3)}) == float("inf")

    def test_tally_counts_same_day_later_slots(self):
        assert calculate_activity_availabillity(FakeSchedulerCls, 0, 2, {(0, 2), (0, 5)}) == 2

    def test_tally_excludes_same_day_earlier_slots(self):
        assert calculate_activity_availabillity(FakeSchedulerCls, 0, 5, {(0, 5), (0, 1)}) == 1

    def test_tally_excludes_earlier_days(self):
        assert calculate_activity_availabillity(FakeSchedulerCls, 2, 2, {(2, 2), (0, 5)}) == 1

    def test_tally_excludes_days_beyond_open_days(self):
        """day index >= len(OPEN_DAYS), e.g. a Sat/Sun slot, shouldn't count."""
        assert calculate_activity_availabillity(FakeSchedulerCls, 0, 2, {(0, 2), (5, 2)}) == 1


class TestRoutineScheduling:
    """This whole path is dead in production - ValidRoutineActivitiesView always returns
    empty - so these call __fillRoutines directly just to pin down what it currently does."""

    def _make_patient_schedule(self):
        return [["", "", "", ""]]  # 1 day, 4 empty slots

    def _routine_df(self, activity_id, activity_title, fixed_time_slots):
        import pandas as pd
        return pd.DataFrame({
            "ActivityID": [activity_id],
            "ActivityTitle": [activity_title],
            "FixedTimeSlots": [fixed_time_slots],
        })

    def test_fills_empty_slot_with_routine_activity(self):
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        patient_schedule = self._make_patient_schedule()
        patient_routine = self._routine_df(1, "Cup Stacking Game", "0-1")
        patient_info = {"exclusions": {}, "preferences": set(), "dispreferences": set()}

        RecommendedRoutineActivityScheduler._RecommendedRoutineActivityScheduler__fillRoutines(
            patient_schedule, pd.DataFrame(), patient_routine, patient_info, datetime.datetime(2024, 3, 18)
        )

        assert patient_schedule[0][1] == "Cup Stacking Game"

    def test_excluded_routine_activity_is_not_scheduled(self):
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        patient_schedule = self._make_patient_schedule()
        patient_routine = self._routine_df(1, "Cup Stacking Game", "0-1")
        week_start = datetime.datetime(2024, 3, 18)
        patient_info = {"exclusions": {1: None}, "preferences": set(), "dispreferences": set()}

        RecommendedRoutineActivityScheduler._RecommendedRoutineActivityScheduler__fillRoutines(
            patient_schedule, pd.DataFrame(), patient_routine, patient_info, week_start
        )

        assert patient_schedule[0][1] == ""

    def test_conflicting_slot_reschedules_existing_activity(self):
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        # (0,1) is taken by "Existing Activity" already, but that activity can also run at
        # (0,2) per `activities` below, which is free - so it should get bumped there.
        patient_schedule = [["", "Existing Activity", "", ""]]
        patient_routine = self._routine_df(1, "Cup Stacking Game", "0-1")
        activities = pd.DataFrame({
            "ActivityTitle": ["Existing Activity"],
            "FixedTimeSlots": ["0-1,0-2"],
        })
        patient_info = {"exclusions": {}, "preferences": set(), "dispreferences": set()}

        RecommendedRoutineActivityScheduler._RecommendedRoutineActivityScheduler__fillRoutines(
            patient_schedule, activities, patient_routine, patient_info, datetime.datetime(2024, 3, 18)
        )

        assert patient_schedule[0][1] == "Cup Stacking Game"
        assert patient_schedule[0][2] == "Existing Activity"


class TestFlexibleRecommendedScheduling:
    pass  # covered by TestRecommendedRoutineFillSchedule below instead


def _empty_patients_view_df():
    return pd.DataFrame({
        "PatientID": pd.Series([], dtype="int64"),
        "PreferredActivityID": pd.Series([], dtype="int64"),
        "ActivityEndDate": pd.Series([], dtype="datetime64[ns]"),
    })


def _empty_patients_unpreferred_df():
    return pd.DataFrame({
        "PatientID": pd.Series([], dtype="int64"),
        "DispreferredActivityID": pd.Series([], dtype="int64"),
        "ActivityEndDate": pd.Series([], dtype="datetime64[ns]"),
    })


def _empty_activities_excluded_df():
    return pd.DataFrame({
        "ActivityExclusionID": pd.Series([], dtype="int64"),
        "ActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"),
        "ExclusionRemarks": pd.Series([], dtype="object"),
        "EndDateTime": pd.Series([], dtype="datetime64[ns]"),
        "ActivityTitle": pd.Series([], dtype="object"),
    })


def _empty_disrecommended_df():
    return pd.DataFrame({
        "ActivityID": pd.Series([], dtype="int64"),
        "IsFixed": pd.Series([], dtype="int64"),
        "ActivityTitle": pd.Series([], dtype="object"),
        "PatientID": pd.Series([], dtype="int64"),
        "ActivityEndDate": pd.Series([], dtype="datetime64[ns]"),
    })


from contextlib import ExitStack, contextmanager


@contextmanager
def _patch_recommended_stage(recommendations_df, patients_df=None, unpreferred_df=None, excluded_df=None, disrecommended_df=None):
    """Swaps out the views recommended-activity scheduling reads for fake DataFrames."""
    with ExitStack() as stack:
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.RecommendedActivitiesView.get_data", return_value=recommendations_df
        ))
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.PatientsView.get_data",
            return_value=patients_df if patients_df is not None else _empty_patients_view_df(),
        ))
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.PatientsUnpreferredView.get_data",
            return_value=unpreferred_df if unpreferred_df is not None else _empty_patients_unpreferred_df(),
        ))
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.ActivitiesExcludedView.get_data",
            return_value=excluded_df if excluded_df is not None else _empty_activities_excluded_df(),
        ))
        stack.enter_context(patch(
            "pear_schedule.db_utils.views.DisrecommendedActivitiesView.get_data",
            return_value=disrecommended_df if disrecommended_df is not None else _empty_disrecommended_df(),
        ))
        stack.enter_context(patch(
            "pear_schedule.scheduler.individualScheduling.DB.get_engine", return_value=MagicMock()
        ))
        yield


class TestRecommendedRoutineFillSchedule:
    """RecommendedRoutineActivityScheduler.fillSchedule, end to end."""

    def _config(self, slots_per_day=4):
        return make_scheduler_config(
            OPEN_DAYS=["Monday"],
            SLOTS_PER_DAY={"Monday": slots_per_day},
        )

    def test_fixed_slot_activity_scheduled_at_correct_slot(self, monkeypatch):
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", self._config(), raising=False)
        recommendations_df = pd.DataFrame({
            "ActivityID": [1], "IsFixed": [1], "MinDuration": [30],
            "ActivityTitle": ["Physiotherapy"], "FixedTimeSlots": ["0-1"],
            "PatientID": [1], "ActivityEndDate": [pd.Timestamp("2099-12-31")],
        })
        patients_df = pd.DataFrame({"PatientID": [1], "PreferredActivityID": [999], "ActivityEndDate": [pd.Timestamp("2099-12-31")]})
        schedules = {1: [["", "", "", ""]]}
        week_start = datetime.datetime(2024, 3, 18)

        with _patch_recommended_stage(recommendations_df, patients_df=patients_df):
            RecommendedRoutineActivityScheduler.fillSchedule(schedules, week_start=week_start)

        assert schedules[1][0][1] == "Physiotherapy"

    def test_expired_activity_end_date_is_not_scheduled(self, monkeypatch):
        """An explicit ActivityEndDate in the past should exclude the activity."""
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", self._config(), raising=False)
        recommendations_df = pd.DataFrame({
            "ActivityID": [1], "IsFixed": [1], "MinDuration": [30],
            "ActivityTitle": ["Expired Activity"], "FixedTimeSlots": ["0-1"],
            "PatientID": [1], "ActivityEndDate": [pd.Timestamp("2020-01-01")],  # already expired
        })
        patients_df = pd.DataFrame({"PatientID": [1], "PreferredActivityID": [999], "ActivityEndDate": [pd.Timestamp("2099-12-31")]})
        schedules = {1: [["", "", "", ""]]}
        week_start = datetime.datetime(2024, 3, 18)

        with _patch_recommended_stage(recommendations_df, patients_df=patients_df):
            RecommendedRoutineActivityScheduler.fillSchedule(schedules, week_start=week_start)

        assert schedules[1][0][1] == ""

    def test_null_activity_end_date_is_indefinite_and_still_scheduled(self, monkeypatch):
        """A null ActivityEndDate means the activity never expires."""
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", self._config(), raising=False)
        recommendations_df = pd.DataFrame({
            "ActivityID": [1], "IsFixed": [1], "MinDuration": [30],
            "ActivityTitle": ["Indefinite Activity"], "FixedTimeSlots": ["0-1"],
            "PatientID": [1], "ActivityEndDate": [pd.NaT],
        })
        patients_df = pd.DataFrame({"PatientID": [1], "PreferredActivityID": [999], "ActivityEndDate": [pd.Timestamp("2099-12-31")]})
        schedules = {1: [["", "", "", ""]]}
        week_start = datetime.datetime(2024, 3, 18)

        with _patch_recommended_stage(recommendations_df, patients_df=patients_df):
            RecommendedRoutineActivityScheduler.fillSchedule(schedules, week_start=week_start)

        assert schedules[1][0][1] == "Indefinite Activity"

    def test_all_flexible_recommended_activities_are_scheduled(self, monkeypatch):
        """No fixed activities means no time-slot sets to union; __fillByFixedTimeSlots
        should just no-op and let __fillFlexibleActivities schedule the flexible activity."""
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", self._config(), raising=False)
        recommendations_df = pd.DataFrame({
            "ActivityID": [1], "IsFixed": [0], "MinDuration": [30],
            "ActivityTitle": ["Flexible Activity"], "FixedTimeSlots": [""],
            "PatientID": [1], "ActivityEndDate": [pd.Timestamp("2099-12-31")],
        })
        patients_df = pd.DataFrame({"PatientID": [1], "PreferredActivityID": [999], "ActivityEndDate": [pd.Timestamp("2099-12-31")]})
        schedules = {1: [["", "", "", ""]]}
        week_start = datetime.datetime(2024, 3, 18)

        with _patch_recommended_stage(recommendations_df, patients_df=patients_df):
            RecommendedRoutineActivityScheduler.fillSchedule(schedules, week_start=week_start)

        assert schedules[1][0][0] == "Flexible Activity"

    def test_excluded_activity_is_not_scheduled(self, monkeypatch):
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", self._config(), raising=False)
        recommendations_df = pd.DataFrame({
            "ActivityID": [1], "IsFixed": [1], "MinDuration": [30],
            "ActivityTitle": ["Physiotherapy"], "FixedTimeSlots": ["0-1"],
            "PatientID": [1], "ActivityEndDate": [pd.Timestamp("2099-12-31")],
        })
        patients_df = pd.DataFrame({"PatientID": [1], "PreferredActivityID": [999], "ActivityEndDate": [pd.Timestamp("2099-12-31")]})
        excluded_df = pd.DataFrame({
            "ActivityExclusionID": [1], "ActivityID": [1], "PatientID": [1],
            "ExclusionRemarks": [""], "EndDateTime": [None], "ActivityTitle": ["Physiotherapy"],
        })
        schedules = {1: [["", "", "", ""]]}
        week_start = datetime.datetime(2024, 3, 18)

        with _patch_recommended_stage(recommendations_df, patients_df=patients_df, excluded_df=excluded_df):
            RecommendedRoutineActivityScheduler.fillSchedule(schedules, week_start=week_start)

        assert schedules[1][0][1] == ""

    def test_multi_slot_activity_at_day_end_is_not_scheduled(self, monkeypatch):
        """Unlike compulsory's version of this check, this one actually works - confirms
        the day-bounds check at individualScheduling.py ~196 stops the overflow."""
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", self._config(), raising=False)
        recommendations_df = pd.DataFrame({
            "ActivityID": [1], "IsFixed": [1], "MinDuration": [60],  # needs 2 slots
            "ActivityTitle": ["Late Activity"], "FixedTimeSlots": ["0-3"],  # last slot of a 4-slot day
            "PatientID": [1], "ActivityEndDate": [pd.Timestamp("2099-12-31")],
        })
        patients_df = pd.DataFrame({"PatientID": [1], "PreferredActivityID": [999], "ActivityEndDate": [pd.Timestamp("2099-12-31")]})
        schedules = {1: [["", "", "", ""]]}
        week_start = datetime.datetime(2024, 3, 18)

        with _patch_recommended_stage(recommendations_df, patients_df=patients_df):
            RecommendedRoutineActivityScheduler.fillSchedule(schedules, week_start=week_start)

        assert schedules[1][0][3] == ""


class TestFillFlexibleActivities:
    """Calls __fillFlexibleActivities directly, skipping the rest of the stage."""

    def test_gap_sized_exactly_to_duration_is_scheduled(self, monkeypatch):
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        cfg = make_scheduler_config(OPEN_DAYS=["Monday"], SLOTS_PER_DAY={"Monday": 4})
        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", cfg, raising=False)

        patient_schedule = [["", "", "Pre-Existing", ""]]  # 2-slot free run at the start
        activities = pd.DataFrame({"ActivityID": [1], "ActivityTitle": ["Board Games"], "MinDuration": [60]})
        patient_info = {"exclusions": {}}
        week_start = datetime.datetime(2024, 3, 18)

        RecommendedRoutineActivityScheduler._RecommendedRoutineActivityScheduler__fillFlexibleActivities(
            patient_schedule, activities, patient_info, week_start
        )

        assert patient_schedule[0][0] == "Board Games"
        assert patient_schedule[0][1] == "Board Games"

    def test_gap_shorter_than_duration_left_unfilled(self, monkeypatch):
        from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler

        cfg = make_scheduler_config(OPEN_DAYS=["Monday"], SLOTS_PER_DAY={"Monday": 2})
        monkeypatch.setattr(RecommendedRoutineActivityScheduler, "config", cfg, raising=False)

        patient_schedule = [["", "Pre-Existing"]]  # only a 1-slot gap available
        activities = pd.DataFrame({"ActivityID": [1], "ActivityTitle": ["Board Games"], "MinDuration": [60]})  # needs 2 slots
        patient_info = {"exclusions": {}}
        week_start = datetime.datetime(2024, 3, 18)

        RecommendedRoutineActivityScheduler._RecommendedRoutineActivityScheduler__fillFlexibleActivities(
            patient_schedule, activities, patient_info, week_start
        )

        assert patient_schedule[0][0] == ""  # left unfilled - no partial placement
        assert patient_schedule[0][1] == "Pre-Existing"


class TestPreferredScheduling:
    """PreferredActivityScheduler.fillPreferences. Passes `patients` straight in instead
    of mocking out _get_patient_data's views."""

    def _config(self):
        return make_scheduler_config(OPEN_DAYS=["Monday"], SLOTS_PER_DAY={"Monday": 4})

    def _neutralize_shuffle(self, monkeypatch):
        # __findActivityBySlot shuffles candidates via .sample(frac=1) - kill that so
        # results are deterministic
        monkeypatch.setattr(pd.DataFrame, "sample", lambda self, frac=1: self)

    def test_preferred_activity_fills_empty_gap(self, monkeypatch):
        from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler

        self._neutralize_shuffle(monkeypatch)
        monkeypatch.setattr(PreferredActivityScheduler, "config", self._config(), raising=False)

        activities_df = pd.DataFrame({
            "ActivityID": [1], "ActivityTitle": ["Board Games"],
            "FixedTimeSlots": [""], "MinDuration": [30], "MaxDuration": [30],
        })
        schedules = {1: [["", "", "", ""]]}
        patients = {1: {"exclusions": set(), "preferences": {1}, "dispreferences": set()}}

        with patch("pear_schedule.db_utils.views.ActivitiesView.get_data", return_value=activities_df):
            PreferredActivityScheduler.fillPreferences(schedules, patients=patients)

        assert schedules[1][0][0] == "Board Games"

    def test_activity_exceeding_gap_falls_back_to_free_and_easy(self, monkeypatch):
        '''Fixed the bug where a preferred activity too long for the gap can still get picked.
        Now it should fall back to "Free and Easy" directly.'''
        from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler

        self._neutralize_shuffle(monkeypatch)
        monkeypatch.setattr(PreferredActivityScheduler, "config", self._config(), raising=False)

        activities_df = pd.DataFrame({
            "ActivityID": [1], "ActivityTitle": ["Long Activity"],
            "FixedTimeSlots": [""], "MinDuration": [60], "MaxDuration": [60],
        })
        schedules = {1: [["", "Pre-Existing", "", ""]]}  # only a 1-slot gap at index 0
        patients = {1: {"exclusions": set(), "preferences": {1}, "dispreferences": set()}}

        with patch("pear_schedule.db_utils.views.ActivitiesView.get_data", return_value=activities_df):
            PreferredActivityScheduler.fillPreferences(schedules, patients=patients)

        assert schedules[1][0][0] == "Free and Easy"
        assert schedules[1][0][1] == "Pre-Existing"

    def test_falls_back_to_neutral_activity_when_nothing_preferred(self, monkeypatch):
        from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler

        self._neutralize_shuffle(monkeypatch)
        monkeypatch.setattr(PreferredActivityScheduler, "config", self._config(), raising=False)

        activities_df = pd.DataFrame({
            "ActivityID": [2], "ActivityTitle": ["Neutral Activity"],
            "FixedTimeSlots": [""], "MinDuration": [30], "MaxDuration": [30],
        })
        schedules = {1: [["", "", "", ""]]}
        patients = {1: {"exclusions": set(), "preferences": set(), "dispreferences": set()}}

        with patch("pear_schedule.db_utils.views.ActivitiesView.get_data", return_value=activities_df):
            PreferredActivityScheduler.fillPreferences(schedules, patients=patients)

        assert schedules[1][0][0] == "Neutral Activity"

    def test_falls_back_to_free_and_easy_when_nothing_fits(self, monkeypatch):
        from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler

        self._neutralize_shuffle(monkeypatch)
        monkeypatch.setattr(PreferredActivityScheduler, "config", self._config(), raising=False)

        activities_df = pd.DataFrame({
            "ActivityID": [2], "ActivityTitle": ["Dispreferred Activity"],
            "FixedTimeSlots": [""], "MinDuration": [30], "MaxDuration": [30],
        })
        schedules = {1: [["", "", "", ""]]}
        patients = {1: {"exclusions": set(), "preferences": set(), "dispreferences": {2}}}

        with patch("pear_schedule.db_utils.views.ActivitiesView.get_data", return_value=activities_df):
            PreferredActivityScheduler.fillPreferences(schedules, patients=patients)

        assert schedules[1][0][0] == "Free and Easy"

    def test_excluded_activity_never_considered_even_if_preferred(self, monkeypatch):
        from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler

        self._neutralize_shuffle(monkeypatch)
        monkeypatch.setattr(PreferredActivityScheduler, "config", self._config(), raising=False)

        activities_df = pd.DataFrame({
            "ActivityID": [2], "ActivityTitle": ["Excluded But Preferred"],
            "FixedTimeSlots": [""], "MinDuration": [30], "MaxDuration": [30],
        })
        schedules = {1: [["", "", "", ""]]}
        patients = {1: {"exclusions": {2}, "preferences": {2}, "dispreferences": set()}}

        with patch("pear_schedule.db_utils.views.ActivitiesView.get_data", return_value=activities_df):
            PreferredActivityScheduler.fillPreferences(schedules, patients=patients)

        assert schedules[1][0][0] == "Free and Easy"


class TestFindActivityBySlot:
    """PreferredActivityScheduler.__findActivityBySlot (name-mangled, hence the odd call syntax)."""

    def _config(self):
        return make_scheduler_config(OPEN_DAYS=["Monday"], SLOTS_PER_DAY={"Monday": 8})

    def _call(self, activities, used_activities, day, slot, slot_size):
        from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler
        return PreferredActivityScheduler._PreferredActivityScheduler__findActivityBySlot(
            activities, used_activities, day, slot, slot_size
        )

    def test_fixed_slot_activity_matching_window_is_selected_others_excluded(self, monkeypatch):
        monkeypatch.setattr(pd.DataFrame, "sample", lambda self, frac=1: self)
        from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler
        monkeypatch.setattr(PreferredActivityScheduler, "config", self._config(), raising=False)

        activities = pd.DataFrame({
            "ActivityID": [1, 2],
            "ActivityTitle": ["Fits", "OutOfWindow"],
            "FixedTimeSlots": ["0-2", "0-5"],
            "MinDuration": [30, 30],
        })
        activities = activities.assign(ProcessedTimeSlots=[{(0, 2)}, {(0, 5)}])

        result = self._call(activities, set(), day=0, slot=2, slot_size=2)
        assert result == "Fits"

    def test_tie_is_resolved_deterministically_by_row_order_once_shuffle_neutralized(self, monkeypatch):
        monkeypatch.setattr(pd.DataFrame, "sample", lambda self, frac=1: self)
        from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler
        monkeypatch.setattr(PreferredActivityScheduler, "config", self._config(), raising=False)

        activities = pd.DataFrame({
            "ActivityID": [1, 2],
            "ActivityTitle": ["First", "Second"],
            "FixedTimeSlots": ["", ""],
            "MinDuration": [30, 30],
        })
        activities = activities.assign(ProcessedTimeSlots=[set(), set()])

        result = self._call(activities, set(), day=0, slot=0, slot_size=1)
        assert result == "First"
