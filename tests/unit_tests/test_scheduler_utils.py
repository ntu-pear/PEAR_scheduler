"""Tests for the small pure helpers in scheduler/utils.py."""

import datetime

from pear_schedule.scheduler.utils import (
    parseFixedTimeArr,
    checkActivityExcluded,
    rescheduleActivity,
)

class TestParseFixedTimeArr:
    """Checks whether fixed time-slot strings are converted correctly."""
    def test_single_slot(self):
        assert parseFixedTimeArr("0-2") == [(0, 2)]

    def test_multiple_slots(self):
        assert parseFixedTimeArr("0-2,1-5") == [(0, 2), (1, 5)]


class TestCheckActivityExcluded:
    """Checks whether an activity should be blocked for a patient."""
    def setup_method(self):
        self.week_start = datetime.datetime(2024, 3, 18)  # a Monday

    def test_activity_not_in_exclusions(self):
        assert checkActivityExcluded(1, {}, 0, self.week_start) is False

    def test_exclusion_end_none_is_always_excluded(self):
        """Null exclusion end date = patient is permanently blocked."""
        patient_exclusions = {1: None}
        assert checkActivityExcluded(1, patient_exclusions, 0, self.week_start) is True

    def test_exclusion_end_same_day_as_slot_is_excluded(self):
        slot_datetime = self.week_start + datetime.timedelta(days=2)
        patient_exclusions = {1: slot_datetime}
        assert checkActivityExcluded(1, patient_exclusions, 2, self.week_start) is True

    def test_exclusion_ended_before_slot_is_not_excluded(self):
        exclusion_end = self.week_start + datetime.timedelta(days=1)
        patient_exclusions = {1: exclusion_end}
        assert checkActivityExcluded(1, patient_exclusions, 2, self.week_start) is False


class TestRescheduleActivity:
    """Checks whether the scheduler can find another empty slot when an activity needs to be moved."""
    def test_returns_first_free_slot(self):
        patient_schedule = [["", "Existing Activity"], ["", ""]]
        potential_slots = [(0, 1), (0, 0), (1, 0)]
        assert rescheduleActivity(patient_schedule, 0, 0, potential_slots) == (0, 0)

    def test_returns_none_if_all_occupied(self):
        patient_schedule = [["Activity A", "Activity B"]]
        potential_slots = [(0, 0), (0, 1)]
        assert rescheduleActivity(patient_schedule, 0, 0, potential_slots) is None

    def test_day_and_time_params_are_unused(self):
        """day and time are unused - only potential_slots and patient_schedule matter."""
        patient_schedule = [["", ""]]
        potential_slots = [(0, 0)]
        result_a = rescheduleActivity(patient_schedule, 0, 0, potential_slots)
        result_b = rescheduleActivity(patient_schedule, 999, -999, potential_slots)
        assert result_a == result_b == (0, 0)
