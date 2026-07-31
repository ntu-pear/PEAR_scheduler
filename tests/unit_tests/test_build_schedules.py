"""
End-to-end build_schedules() with all 6 stages mocked together
(Compulsory -> Recommended/Routine -> Group -> Preferred -> Adhoc -> Medication).

2 patients, 3 OPEN_DAYS. Patient 1 goes through every stage; patient 2 only gets
compulsory + group + preferred-fallback, just to prove stages don't touch each
other's patients. Patient 2 gets no recommended activity at all, since that's not
what this test is checking.
"""

import datetime
import types
from contextlib import ExitStack, contextmanager
from unittest.mock import patch, MagicMock

import pandas as pd

from tests.utils.scheduler_config import make_scheduler_config

from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
from pear_schedule.scheduler.individualScheduling import RecommendedRoutineActivityScheduler, PreferredActivityScheduler
from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from pear_schedule.scheduler.adhocScheduling import AdhocScheduler
from pear_schedule.scheduler.medicationScheduling import medicationScheduler, medicationScheduleData
from pear_schedule.scheduler.utils import build_schedules

FIXED_NOW = datetime.datetime(2024, 3, 18)  # a Monday
WEEK_START = FIXED_NOW.date()
OPEN_DAYS = ["Monday", "Tuesday", "Wednesday"]

SCHEDULER_CLASSES = [
    ("Compulsory", CompulsoryActivityScheduler),
    ("RecommendedRoutine", RecommendedRoutineActivityScheduler),
    ("Group", GroupActivityScheduler),
    ("Preferred", PreferredActivityScheduler),
    ("Adhoc", AdhocScheduler),
    ("Medication", medicationScheduler),
]


def _config():
    return make_scheduler_config(
        OPEN_DAYS=OPEN_DAYS,
        SLOTS_PER_DAY={d: 8 for d in OPEN_DAYS},
        TARGET_WEEKLY_GROUP_ACTIVITIES=1,
        DAYS=len(OPEN_DAYS),
        WORKING_HOURS={d.lower(): {"open": "09:00", "close": "13:00"} for d in OPEN_DAYS},
    )


def _empty_df(columns):
    return pd.DataFrame({col: pd.Series([], dtype="object") for col in columns})


@contextmanager
def _freeze_now(monkeypatch):
    class _FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_NOW

    fake_ns = types.SimpleNamespace(datetime=_FixedDatetime, date=datetime.date, timedelta=datetime.timedelta)
    monkeypatch.setattr("pear_schedule.scheduler.individualScheduling.datetime", fake_ns)
    monkeypatch.setattr("pear_schedule.scheduler.adhocScheduling.datetime", fake_ns)
    monkeypatch.setattr("pear_schedule.scheduler.medicationScheduling.datetime", fake_ns)
    yield


@contextmanager
def _patch_all_views():
    patients_only_df = pd.DataFrame({"PatientID": [1, 2]})
    group_activity_df = pd.DataFrame({
        "ActivityID": [20], "CentreActivityID": [20], "ActivityTitle": ["Mahjong"],
        "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [1], "MinDuration": [30],
    })
    compulsory_df = pd.DataFrame({
        "ActivityTitle": ["Breathing+Vital Check"], "IsFixed": [1], "FixedTimeSlots": ["0-0"], "MinDuration": [30],
    })
    recommended_df = pd.DataFrame({
        "ActivityID": [10], "IsFixed": [1], "MinDuration": [30],
        "ActivityTitle": ["Physiotherapy"], "FixedTimeSlots": ["0-1"],
        "PatientID": [1], "ActivityEndDate": [pd.Timestamp("2099-12-31")],
    })
    patients_view_df = pd.DataFrame({
        "PatientID": [1, 2], "PreferredActivityID": [999, 999],
        "ActivityEndDate": [pd.Timestamp("2099-12-31")] * 2,
    })
    empty_unpreferred = pd.DataFrame({
        "PatientID": pd.Series([], dtype="int64"),
        "DispreferredActivityID": pd.Series([], dtype="int64"),
        "ActivityEndDate": pd.Series([], dtype="datetime64[ns]"),
    })
    empty_excluded = pd.DataFrame({
        "ActivityExclusionID": pd.Series([], dtype="int64"), "ActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"), "ExclusionRemarks": pd.Series([], dtype="object"),
        "EndDateTime": pd.Series([], dtype="datetime64[ns]"), "ActivityTitle": pd.Series([], dtype="object"),
    })
    empty_disrecommended = pd.DataFrame({
        "ActivityID": pd.Series([], dtype="int64"), "IsFixed": pd.Series([], dtype="int64"),
        "ActivityTitle": pd.Series([], dtype="object"), "PatientID": pd.Series([], dtype="int64"),
        "ActivityEndDate": pd.Series([], dtype="datetime64[ns]"),
    })
    empty_activities_view = pd.DataFrame({
        "ActivityID": pd.Series([], dtype="int64"), "ActivityTitle": pd.Series([], dtype="object"),
        "FixedTimeSlots": pd.Series([], dtype="object"), "MinDuration": pd.Series([], dtype="int64"),
        "MaxDuration": pd.Series([], dtype="int64"), "EndDate": pd.Series([], dtype="datetime64[ns]"),
        "StartDate": pd.Series([], dtype="datetime64[ns]"),
    })
    empty_group_pref = pd.DataFrame({
        "CentreActivityID": pd.Series([], dtype="int64"), "PatientID": pd.Series([], dtype="int64"),
        "IsLike": pd.Series([], dtype="int64"),
    })
    group_recommend_df = pd.DataFrame({"CentreActivityID": [20, 20], "PatientID": [1, 2], "DoctorRecommendation": [1, 1]})
    empty_group_excl = pd.DataFrame({
        "CentreActivityID": pd.Series([], dtype="int64"), "PatientID": pd.Series([], dtype="int64"),
    })
    adhoc_df = pd.DataFrame({
        "AdhocID": [1], "PatientID": [1], "OldActivityTitle": ["Breathing+Vital Check"],
        "NewActivityTitle": ["Adhoc Replacement Activity"],
        "StartDate": [WEEK_START], "EndDate": [WEEK_START + datetime.timedelta(days=2)],
    })
    medication_df = pd.DataFrame({
        "PatientID": [1], "MedicationID": [1], "PrescriptionName": ["Aspirin"], "Dosage": ["1 tablet"],
        "AdministerTime": ["0900"], "StartDateTime": [datetime.datetime(2020, 1, 1)],
        "EndDateTime": [datetime.datetime(2099, 12, 31)], "Instruction": ["Take with food"], "IsDeleted": [0],
    })
    empty_caregiver = pd.DataFrame({
        "patientId": pd.Series([], dtype="int64"), "caregiverId": pd.Series([], dtype="object"),
        "tempCaregiverId": pd.Series([], dtype="object"),
    })

    with ExitStack() as stack:
        p = lambda target, value: stack.enter_context(patch(target, return_value=value))
        p("pear_schedule.db_utils.views.PatientsOnlyView.get_data", patients_only_df)
        p("pear_schedule.db_utils.views.GroupActivitiesOnlyView.get_data", group_activity_df)
        p("pear_schedule.db_utils.views.CompulsoryActivitiesOnlyView.get_data", compulsory_df)
        p("pear_schedule.db_utils.views.RecommendedActivitiesView.get_data", recommended_df)
        p("pear_schedule.db_utils.views.PatientsView.get_data", patients_view_df)
        p("pear_schedule.db_utils.views.PatientsUnpreferredView.get_data", empty_unpreferred)
        p("pear_schedule.db_utils.views.ActivitiesExcludedView.get_data", empty_excluded)
        p("pear_schedule.db_utils.views.DisrecommendedActivitiesView.get_data", empty_disrecommended)
        p("pear_schedule.db_utils.views.ActivitiesView.get_data", empty_activities_view)
        p("pear_schedule.db_utils.views.GroupActivitiesPreferenceView.get_data", empty_group_pref)
        p("pear_schedule.db_utils.views.GroupActivitiesRecommendationView.get_data", group_recommend_df)
        p("pear_schedule.db_utils.views.GroupActivitiesExclusionView.get_data", empty_group_excl)
        p("pear_schedule.db_utils.views.AdhocActivityView.get_data", adhoc_df)
        p("pear_schedule.db_utils.views.MedicationView.get_data", medication_df)
        p("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", empty_caregiver)
        stack.enter_context(patch("pear_schedule.scheduler.individualScheduling.DB.get_engine", return_value=MagicMock()))
        yield


class TestBuildSchedulesEndToEnd:
    def test_full_pipeline_produces_expected_schedule(self, monkeypatch):
        cfg = _config()
        for _, cls in SCHEDULER_CLASSES:
            monkeypatch.setattr(cls, "config", cfg, raising=False)

        with _freeze_now(monkeypatch), _patch_all_views():
            patient_schedules = {}
            result = build_schedules(cfg, patient_schedules)

        # input dict is mutated in place; that's the real output, not the return value
        assert set(patient_schedules.keys()) == {1, 2}

        # compulsory placed for both patients
        assert patient_schedules[2][0][0] == "Breathing+Vital Check"
        # patient 1's compulsory slot got replaced by adhoc -> proves stage order
        assert patient_schedules[1][0][0].startswith("Adhoc Replacement Activity")

        # fixed-slot recommended activity untouched by later stages
        assert patient_schedules[1][0][1] == "Physiotherapy"

        # group activity present for both patients (by title, not exact slot)
        assert any("Mahjong" in slot for slot in patient_schedules[1][0])
        assert any("Mahjong" in slot for slot in patient_schedules[2][0])

        # medication appended to the adhoc-replaced slot, not overwriting it
        assert "Give Medication@0900" in patient_schedules[1][0][0]
        assert patient_schedules[1][0][0].startswith("Adhoc Replacement Activity")

        # no empty slots left in patient 2's schedule
        for day in patient_schedules[2]:
            assert all(slot != "" for slot in day)

        # return value is medicationScheduleData, not patientSchedules
        assert isinstance(result, medicationScheduleData)

    def test_stage_order_is_preserved(self, monkeypatch):
        """Confirms stage order by spying on each fillSchedule call, independent of
        the side-effect-based proof above."""
        cfg = _config()
        call_order = []

        for name, cls in SCHEDULER_CLASSES:
            monkeypatch.setattr(cls, "config", cfg, raising=False)
            original_func = cls.fillSchedule.__func__

            def make_spy(name=name, original_func=original_func):
                def spy(cls_arg, *args, **kwargs):
                    call_order.append(name)
                    return original_func(cls_arg, *args, **kwargs)
                return spy

            monkeypatch.setattr(cls, "fillSchedule", classmethod(make_spy()))

        with _freeze_now(monkeypatch), _patch_all_views():
            build_schedules(cfg, {})

        assert call_order == ["Compulsory", "RecommendedRoutine", "Group", "Preferred", "Adhoc", "Medication"]
