"""
medicationScheduling.py - time-to-slot conversion, placing the medication text into the
weekly schedule, and caregiver assignment.
"""

import datetime
import types
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from pear_schedule.scheduler.medicationScheduling import (
    medicationScheduleData,
    medicationScheduler,
    getTimeSlot,
)
from tests.utils.scheduler_config import make_scheduler_config

FIXED_NOW = datetime.datetime(2024, 3, 18)  # a Monday
START_OF_WEEK = FIXED_NOW.replace(hour=0, minute=0, second=0, microsecond=0)
END_OF_WEEK = START_OF_WEEK + datetime.timedelta(days=4, hours=23, minutes=59, seconds=59)


@contextmanager
def _freeze_now(monkeypatch, fixed_now=FIXED_NOW):
    class _FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    fake_ns = types.SimpleNamespace(datetime=_FixedDatetime, date=datetime.date, timedelta=datetime.timedelta)
    monkeypatch.setattr("pear_schedule.scheduler.medicationScheduling.datetime", fake_ns)
    yield

# __getMedicationSchedulingData hardcodes end_of_week assuming exactly 5 OPEN_DAYS
# (medicationScheduling.py ~36) - sticking to 5 OPEN_DAYS everywhere here so we don't
# trip over that separate issue

OPEN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _config(**overrides):
    return make_scheduler_config(
        OPEN_DAYS=OPEN_DAYS,
        SLOTS_PER_DAY={day: 8 for day in OPEN_DAYS},
        WORKING_HOURS={day.lower(): {"open": "09:00", "close": "13:00"} for day in OPEN_DAYS},
        **overrides,
    )


def _medication_row(patient_id=1, medication_id=1, administer_time="0900",
                     start_datetime=datetime.datetime(2020, 1, 1),
                     end_datetime=datetime.datetime(2099, 12, 31),
                     instruction=None):
    return pd.DataFrame({
        "PatientID": [patient_id],
        "MedicationID": [medication_id],
        "PrescriptionName": ["Aspirin"],
        "Dosage": ["1 tablet"],
        "AdministerTime": [administer_time],
        "StartDateTime": [start_datetime],
        "EndDateTime": [end_datetime],
        "Instruction": [instruction],
        "IsDeleted": [0],
    })


def _empty_caregiver_df():
    return pd.DataFrame({
        "patientId": pd.Series([], dtype="int64"),
        "caregiverId": pd.Series([], dtype="object"),
        "tempCaregiverId": pd.Series([], dtype="object"),
    })


def _patient_schedule():
    return {1: [["" for _ in range(8)] for _ in range(5)]}


class TestGetTimeSlot:
    def test_exact_opening_time_returns_slot_zero(self):
        cfg = _config()

        class FakeCls:
            config = cfg

        assert getTimeSlot(FakeCls, "monday", "0900") == 0

    def test_drift_across_a_sweep_of_administer_times(self):
        """(BUG) medicationScheduling.py ~203: getTimeSlot divides by
        MIN_ACTIVITY_DURATION - 1 instead of MIN_ACTIVITY_DURATION, drifting
        near-boundary times (e.g. "0959") into the next slot a minute early."""
        cfg = _config()

        class FakeCls:
            config = cfg

        expected = {
            "0900": 0, "0905": 0, "0915": 0, "0929": 0,
            "0930": 1, "0931": 1, "0945": 1,
            "0959": 2,  # drifted a minute early into slot 2, "should" still be slot 1
            "1000": 2, "1015": 2,
            "1030": 3, "1045": 3,
            "1100": 4, "1130": 5, "1200": 6, "1230": 7,
            "0850": -1,  # before opening
        }
        for time, expected_slot in expected.items():
            assert getTimeSlot(FakeCls, "monday", time) == expected_slot, f"time={time}"


class TestMedicationSchedulerFillSchedule:
    def test_medication_scheduled_across_all_active_days_at_correct_slot(self, monkeypatch):
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)
        patient_schedules = _patient_schedule()

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=_medication_row()), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=_empty_caregiver_df()):
            medicationScheduler.fillSchedule(patient_schedules)

        for day in range(5):
            assert "Give Medication@0900" in patient_schedules[1][day][0]

    def test_medication_starting_mid_week(self, monkeypatch):
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)
        patient_schedules = _patient_schedule()

        row = _medication_row(start_datetime=START_OF_WEEK + datetime.timedelta(days=2))  # Wednesday

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=row), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=_empty_caregiver_df()):
            medicationScheduler.fillSchedule(patient_schedules)

        assert patient_schedules[1][0][0] == ""  # Monday - before start, untouched
        assert patient_schedules[1][1][0] == ""  # Tuesday - before start, untouched
        assert "Give Medication" in patient_schedules[1][2][0]  # Wednesday onward

    def test_medication_ending_mid_week(self, monkeypatch):
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)
        patient_schedules = _patient_schedule()

        row = _medication_row(
            end_datetime=START_OF_WEEK + datetime.timedelta(days=1, hours=23, minutes=59, seconds=59)  # end of Tuesday
        )

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=row), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=_empty_caregiver_df()):
            medicationScheduler.fillSchedule(patient_schedules)

        assert "Give Medication" in patient_schedules[1][0][0]  # Monday
        assert "Give Medication" in patient_schedules[1][1][0]  # Tuesday
        assert patient_schedules[1][2][0] == ""  # Wednesday onward - after end, untouched

    def test_two_colliding_medications_use_correct_separators(self, monkeypatch):
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)
        patient_schedules = _patient_schedule()

        two_meds = pd.concat([
            _medication_row(medication_id=1, administer_time="0900"),
            _medication_row(medication_id=2, administer_time="0900"),
        ]).reset_index(drop=True)

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=two_meds), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=_empty_caregiver_df()):
            medicationScheduler.fillSchedule(patient_schedules)

        text = patient_schedules[1][0][0]
        assert " | Give Medication@0900" in text  # first uses " | "
        assert ", Give Medication@0900" in text  # second uses ", "

    def test_caregiver_id_used_when_present(self, monkeypatch):
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)
        caregiver_df = pd.DataFrame({"patientId": [1], "caregiverId": ["CG1"], "tempCaregiverId": [""]})

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=_medication_row()), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=caregiver_df):
            data = medicationScheduleData(medicationScheduler)

        assert data.medicationSchedules[1][0]["assignedTo"] == "CG1"

    def test_missing_caregiver_and_temp_raises_keyerror_on_supervisor_id(self, monkeypatch):
        """(BUG) medicationScheduling.py ~54: falls back to allocation_row['supervisorId'],
        but the view never selects that column - raises KeyError when caregiverId
        and tempCaregiverId are both empty."""
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)
        caregiver_df = pd.DataFrame({"patientId": [1], "caregiverId": [""], "tempCaregiverId": [""]})

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=_medication_row()), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=caregiver_df):
            raised = False
            try:
                medicationScheduleData(medicationScheduler)
            except KeyError:
                raised = True
            assert raised, "expected KeyError on missing supervisorId column"

    def test_no_allocation_row_falls_back_to_unassigned(self, monkeypatch):
        """Contrast with the KeyError case above: when there's no allocation row at all,
        the `if not allocation_row.empty else "UNASSIGNED"` guard short-circuits before
        ever reaching the supervisorId access."""
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=_medication_row()), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=_empty_caregiver_df()):
            data = medicationScheduleData(medicationScheduler)

        assert data.medicationSchedules[1][0]["assignedTo"] == "UNASSIGNED"

    def test_blank_and_nil_instructions_omit_suffix(self, monkeypatch):
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)

        for instruction in [None, "", "  ", "nil", "NIL", "-"]:
            patient_schedules = _patient_schedule()
            row = _medication_row(instruction=instruction)
            with _freeze_now(monkeypatch), \
                 patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=row), \
                 patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=_empty_caregiver_df()):
                medicationScheduler.fillSchedule(patient_schedules)

            assert "**" not in patient_schedules[1][0][0], f"instruction={instruction!r}"

    def test_real_instruction_appended_with_double_asterisk(self, monkeypatch):
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)
        patient_schedules = _patient_schedule()
        row = _medication_row(instruction="Take with food")

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=row), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=_empty_caregiver_df()):
            medicationScheduler.fillSchedule(patient_schedules)

        assert "**Take with food" in patient_schedules[1][0][0]

    def test_out_of_bounds_slot_skipped_without_error(self, monkeypatch):
        monkeypatch.setattr(medicationScheduler, "config", _config(), raising=False)
        patient_schedules = _patient_schedule()
        row = _medication_row(administer_time="0830")  # before opening -> getTimeSlot returns -1

        with _freeze_now(monkeypatch), \
             patch("pear_schedule.db_utils.views.MedicationView.get_data", return_value=row), \
             patch("pear_schedule.db_utils.views.CaregiverAllocatedView.get_data", return_value=_empty_caregiver_df()):
            medicationScheduler.fillSchedule(patient_schedules)  # should not raise

        assert patient_schedules[1] == [["" for _ in range(8)] for _ in range(5)]
