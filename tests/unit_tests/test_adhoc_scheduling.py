"""Tests for adhocScheduling.py."""

import datetime
import types
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from pear_schedule.scheduler.adhocScheduling import AdhocScheduler
from tests.utils.scheduler_config import make_scheduler_config

FIXED_NOW = datetime.datetime(2024, 3, 18)  # a Monday
WEEK_START = FIXED_NOW.date()


@contextmanager
def _freeze_now(monkeypatch, fixed_now=FIXED_NOW):
    """Temporarily makes the scheduler think the current date is always 18 March 2024."""

    class _FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    fake_ns = types.SimpleNamespace(datetime=_FixedDatetime, date=datetime.date, timedelta=datetime.timedelta)
    monkeypatch.setattr("pear_schedule.scheduler.adhocScheduling.datetime", fake_ns)
    yield


def _config(open_days=5, days=None):
    days_list = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][:open_days]
    return make_scheduler_config(
        OPEN_DAYS=days_list,
        SLOTS_PER_DAY={day: 4 for day in days_list},
        DAYS=days if days is not None else open_days,
    )


def _schedule(num_days=5, num_slots=4):
    return {1: [["" for _ in range(num_slots)] for _ in range(num_days)]}


def _adhoc_row(patient_id=1, old_title="Old Activity", new_title="New Activity",
               start_date=WEEK_START, end_date=WEEK_START):
    return pd.DataFrame({
        "AdhocID": [1],
        "PatientID": [patient_id],
        "OldActivityTitle": [old_title],
        "NewActivityTitle": [new_title],
        "StartDate": [start_date],
        "EndDate": [end_date],
    })


class TestAdhocScheduling:
    def test_replaces_old_activity_across_overlapping_days(self, monkeypatch):
        cfg = _config()
        monkeypatch.setattr(AdhocScheduler, "config", cfg, raising=False)
        schedules = _schedule()
        schedules[1][0][0] = "Old Activity"
        schedules[1][1][0] = "Old Activity"

        adhoc_df = _adhoc_row(start_date=WEEK_START, end_date=WEEK_START + datetime.timedelta(days=1))

        with _freeze_now(monkeypatch), patch(
            "pear_schedule.db_utils.views.AdhocActivityView.get_data", return_value=adhoc_df
        ):
            AdhocScheduler.fillSchedule(schedules)

        assert schedules[1][0][0] == "New Activity"
        assert schedules[1][1][0] == "New Activity"

    def test_range_ending_before_week_is_skipped(self, monkeypatch):
        cfg = _config()
        monkeypatch.setattr(AdhocScheduler, "config", cfg, raising=False)
        schedules = _schedule()
        schedules[1][0][0] = "Old Activity"

        adhoc_df = _adhoc_row(
            start_date=datetime.date(2024, 3, 1), end_date=datetime.date(2024, 3, 10)
        )

        with _freeze_now(monkeypatch), patch(
            "pear_schedule.db_utils.views.AdhocActivityView.get_data", return_value=adhoc_df
        ):
            AdhocScheduler.fillSchedule(schedules)

        assert schedules[1][0][0] == "Old Activity"  # unchanged

    def test_unknown_patient_id_skipped_without_error(self, monkeypatch):
        cfg = _config()
        monkeypatch.setattr(AdhocScheduler, "config", cfg, raising=False)
        schedules = _schedule()

        adhoc_df = _adhoc_row(patient_id=99)

        with _freeze_now(monkeypatch), patch(
            "pear_schedule.db_utils.views.AdhocActivityView.get_data", return_value=adhoc_df
        ):
            AdhocScheduler.fillSchedule(schedules)  # should not raise

        assert schedules[1] == [["", "", "", ""] for _ in range(5)]

    def test_missing_old_or_new_activity_title_skipped(self, monkeypatch):
        cfg = _config()
        monkeypatch.setattr(AdhocScheduler, "config", cfg, raising=False)
        schedules = _schedule()
        schedules[1][0][0] = "Old Activity"

        adhoc_df = _adhoc_row(old_title=None, new_title="New Activity")

        with _freeze_now(monkeypatch), patch(
            "pear_schedule.db_utils.views.AdhocActivityView.get_data", return_value=adhoc_df
        ):
            AdhocScheduler.fillSchedule(schedules)

        assert schedules[1][0][0] == "Old Activity"  # unchanged

    def test_unparseable_dates_row_is_dropped(self, monkeypatch):
        """No null/unparseable-date handling here at all (unlike other stages),
        a bad date just drops the whole row."""
        cfg = _config()
        monkeypatch.setattr(AdhocScheduler, "config", cfg, raising=False)
        schedules = _schedule()
        schedules[1][0][0] = "Old Activity"

        adhoc_df = _adhoc_row(start_date=None, end_date=WEEK_START)

        with _freeze_now(monkeypatch), patch(
            "pear_schedule.db_utils.views.AdhocActivityView.get_data", return_value=adhoc_df
        ):
            AdhocScheduler.fillSchedule(schedules)

        assert schedules[1][0][0] == "Old Activity"  # unchanged

    def test_days_vs_open_days_mismatch_does_not_overflow_schedule(self, monkeypatch):
        """week_end is derived from len(OPEN_DAYS), not the stale config["DAYS"].
        With DAYS=6 but 5 OPEN_DAYS, a row spanning the whole DAYS=6 range must have
        its overlap clipped to the real 5-day week (indices 0-4) instead of walking
        into the nonexistent 6th day and raising IndexError. The row still overlaps
        the real week (days 0-4), so the in-range replacement still happens - only
        the out-of-bounds day 5 access is what the fix prevents."""
        cfg = _config(open_days=5, days=6)
        monkeypatch.setattr(AdhocScheduler, "config", cfg, raising=False)
        schedules = _schedule(num_days=5)
        schedules[1][0][0] = "Old Activity"

        # Old (buggy) week_end = week_start + (DAYS-1) = +5 days would let the loop
        # reach day_idx=5, past the 5-day schedule -> IndexError.
        # Correct week_end = week_start + (len(OPEN_DAYS)-1) = +4 days clips overlap_end
        # to day 4, so the loop only ever touches valid indices 0-4.
        adhoc_df = _adhoc_row(
            start_date=WEEK_START, end_date=WEEK_START + datetime.timedelta(days=5)
        )

        with _freeze_now(monkeypatch), patch(
            "pear_schedule.db_utils.views.AdhocActivityView.get_data", return_value=adhoc_df
        ):
            AdhocScheduler.fillSchedule(schedules)  # should not raise

        assert schedules[1][0][0] == "New Activity"  # day 0 is within the real week, still replaced
        assert len(schedules[1]) == 5  # untouched - no out-of-bounds day was ever created/accessed

    def test_replacement_does_not_expand_into_adjacent_slots(self, monkeypatch):
        cfg = _config()
        monkeypatch.setattr(AdhocScheduler, "config", cfg, raising=False)
        schedules = _schedule()
        schedules[1][0][0] = "Old Activity"
        schedules[1][0][1] = "Unrelated Activity"

        adhoc_df = _adhoc_row()

        with _freeze_now(monkeypatch), patch(
            "pear_schedule.db_utils.views.AdhocActivityView.get_data", return_value=adhoc_df
        ):
            AdhocScheduler.fillSchedule(schedules)

        assert schedules[1][0][0] == "New Activity"
        assert schedules[1][0][1] == "Unrelated Activity"  # untouched, no expansion
