"""compulsoryScheduling.py. A few of these pin down existing bugs on purpose so
they're supposed to start failing once those get fixed."""

import pandas as pd
from unittest.mock import patch

from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
from tests.utils.scheduler_config import make_scheduler_config


def _config(open_days=("Monday",), slots_per_day=4):
    days = list(open_days)
    return make_scheduler_config(
        OPEN_DAYS=days,
        SLOTS_PER_DAY={day: slots_per_day for day in days},
    )


def _empty_schedule(num_patients=1, num_days=1, num_slots=4):
    return {
        pid: [["" for _ in range(num_slots)] for _ in range(num_days)]
        for pid in range(1, num_patients + 1)
    }


class TestCompulsoryScheduling:
    def test_fixed_activity_scheduled_at_correct_slot_for_every_patient(self, monkeypatch):
        cfg = _config()
        monkeypatch.setattr(CompulsoryActivityScheduler, "config", cfg, raising=False)
        df = pd.DataFrame({
            "ActivityTitle": ["Breathing+Vital Check"],
            "FixedTimeSlots": ["0-1"],
            "MinDuration": [30],
        })
        patient_schedules = _empty_schedule(num_patients=2)

        with patch(
            "pear_schedule.scheduler.compulsoryScheduling.CompulsoryActivitiesOnlyView.get_data",
            return_value=df,
        ):
            CompulsoryActivityScheduler.fillSchedule(patient_schedules)

        assert patient_schedules[1][0][1] == "Breathing+Vital Check"
        assert patient_schedules[2][0][1] == "Breathing+Vital Check"

    def test_min_duration_not_divisible_truncates_slot_count(self, monkeypatch):
        """MinDuration=45 with MIN_ACTIVITY_DURATION=30 -> 45 // 30 = 1 slot, not 2.
        Documents the floor-division truncation, not a bug fix."""
        cfg = _config()
        monkeypatch.setattr(CompulsoryActivityScheduler, "config", cfg, raising=False)
        df = pd.DataFrame({
            "ActivityTitle": ["Physiotherapy"],
            "FixedTimeSlots": ["0-1"],
            "MinDuration": [45],
        })
        patient_schedules = _empty_schedule()

        with patch(
            "pear_schedule.scheduler.compulsoryScheduling.CompulsoryActivitiesOnlyView.get_data",
            return_value=df,
        ):
            CompulsoryActivityScheduler.fillSchedule(patient_schedules)

        assert patient_schedules[1][0][1] == "Physiotherapy"
        assert patient_schedules[1][0][2] == ""  # second slot NOT claimed, despite 45 min needing 2 slots

    def test_second_same_day_activity_is_incorrectly_skipped(self, monkeypatch):
        """(BUG) conflict guard scans from index 0, not the target hour, 
        so a second same-day activity gets skipped even though its slot doesn't actually overlap."""
        cfg = _config()
        monkeypatch.setattr(CompulsoryActivityScheduler, "config", cfg, raising=False)
        df = pd.DataFrame({
            "ActivityTitle": ["Activity A", "Activity B"],
            "FixedTimeSlots": ["0-0", "0-2"],
            "MinDuration": [30, 30],
        })
        patient_schedules = _empty_schedule()

        with patch(
            "pear_schedule.scheduler.compulsoryScheduling.CompulsoryActivitiesOnlyView.get_data",
            return_value=df,
        ):
            CompulsoryActivityScheduler.fillSchedule(patient_schedules)

        assert patient_schedules[1][0][0] == "Activity A"
        assert patient_schedules[1][0][2] == ""  # Activity B incorrectly never scheduled

    def test_out_of_range_day_and_hour_silently_skipped(self, monkeypatch):
        cfg = _config()
        monkeypatch.setattr(CompulsoryActivityScheduler, "config", cfg, raising=False)
        df = pd.DataFrame({
            "ActivityTitle": ["Out Of Range Activity"],
            "FixedTimeSlots": ["5-0"],  # day index 5, but patient schedule only has 1 day
            "MinDuration": [30],
        })
        patient_schedules = _empty_schedule()

        with patch(
            "pear_schedule.scheduler.compulsoryScheduling.CompulsoryActivitiesOnlyView.get_data",
            return_value=df,
        ):
            # should not raise IndexError
            CompulsoryActivityScheduler.fillSchedule(patient_schedules)

        assert patient_schedules[1] == [["", "", "", ""]]

    def test_overwrites_pre_occupied_target_slot(self, monkeypatch):
        """(BUG) no check that the target hour is actually free before writing, 
        so it can overwrite whatever's already there."""
        cfg = _config()
        monkeypatch.setattr(CompulsoryActivityScheduler, "config", cfg, raising=False)
        df = pd.DataFrame({
            "ActivityTitle": ["Compulsory Activity"],
            "FixedTimeSlots": ["0-3"],
            "MinDuration": [30],
        })
        patient_schedules = _empty_schedule()
        patient_schedules[1][0][3] = "Pre-Existing Activity"

        with patch(
            "pear_schedule.scheduler.compulsoryScheduling.CompulsoryActivitiesOnlyView.get_data",
            return_value=df,
        ):
            CompulsoryActivityScheduler.fillSchedule(patient_schedules)

        assert patient_schedules[1][0][3] == "Compulsory Activity"  # overwrote "Pre-Existing Activity"
