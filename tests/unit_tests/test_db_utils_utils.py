from datetime import datetime, timedelta

from pear_schedule.db_utils import utils
from pear_schedule.db_utils.utils import (
    day_timeslot_label,
    day_timeslot_labels,
    decode_day_of_week_bitmask,
    routine_time_slots,
    timeslot_index,
)


class TestGetWeekStartAndGetWeekEnd:
    """get_week_end() used to skip to next Sunday on Sundays instead of today."""

    def _freeze(self, monkeypatch, fixed_now: datetime):
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        monkeypatch.setattr(utils, "datetime", FixedDatetime)

    def test_sunday_uses_current_week_sunday_not_next_week(self, monkeypatch):
        # Sunday 2024-03-24 is the last day of the week starting Monday 2024-03-18.
        self._freeze(monkeypatch, datetime(2024, 3, 24, 10, 0, 0))

        assert utils.get_week_start() == datetime(2024, 3, 18, 0, 0, 0)
        assert utils.get_week_end() == datetime(2024, 3, 24, 23, 59, 59)

    def test_midweek_day_still_returns_current_week_sunday(self, monkeypatch):
        # Wednesday 2024-03-20, same week as above.
        self._freeze(monkeypatch, datetime(2024, 3, 20, 10, 0, 0))

        assert utils.get_week_start() == datetime(2024, 3, 18, 0, 0, 0)
        assert utils.get_week_end() == datetime(2024, 3, 24, 23, 59, 59)


class TestTimeslotIndex:
    def test_zero_offset_returns_slot_zero(self):
        assert timeslot_index(timedelta(minutes=0), 30) == 0

    def test_no_drift_across_a_sweep_of_offsets(self):
        expected = {
            0: 0, 5: 0, 15: 0, 29: 0,
            30: 1, 31: 1, 45: 1, 59: 1,  # fixed: no longer drifts into slot 2
            60: 2, 75: 2,
            90: 3, 105: 3,
            120: 4, 150: 5, 180: 6, 210: 7,
        }
        for minutes, expected_slot in expected.items():
            assert timeslot_index(timedelta(minutes=minutes), 30) == expected_slot, f"minutes={minutes}"


# Copied from configprod.py's DAY_TIMESLOTS.
# Not imported because configprod.py requires a real DB connection.
# Used only for comparison in these tests.
PROD_DAY_TIMESLOTS = [
    "09:00-09:30", "09:30-10:00", "10:00-10:30", "10:30-11:00",
    "11:00-11:30", "11:30-12:00", "12:00-12:30", "12:30-13:00",
    "13:00-13:30", "13:30-14:00", "14:00-14:30", "14:30-15:00",
    "15:00-15:30", "15:30-16:00", "16:00-16:30", "16:30-17:00",
]


class TestDayTimeslotLabels:
    def test_two_slots_from_nine(self):
        working_hours = {"monday": {"open": "09:00", "close": "10:00"}}
        assert day_timeslot_labels("Monday", 2, working_hours, 30) == ["09:00-09:30", "09:30-10:00"]

    def test_day_lookup_is_case_insensitive(self):
        working_hours = {"monday": {"open": "09:00", "close": "10:00"}}
        assert day_timeslot_labels("MONDAY", 2, working_hours, 30) == ["09:00-09:30", "09:30-10:00"]

    def test_matches_real_weekday_hours(self):
        """Checks that the dynamic labels match the current weekday DAY_TIMESLOTS."""
        working_hours = {"monday": {"open": "09:00", "close": "17:00"}}
        assert day_timeslot_labels("Monday", 16, working_hours, 30) == PROD_DAY_TIMESLOTS

    def test_matches_real_saturday_hours(self):
        """Checks that Saturday labels match the current shorter opening hours."""
        working_hours = {"saturday": {"open": "09:00", "close": "13:00"}}
        assert day_timeslot_labels("Saturday", 8, working_hours, 30) == PROD_DAY_TIMESLOTS[:8]


class TestDayTimeslotLabel:
    def test_single_label_matches_the_list_version(self):
        working_hours = {"monday": {"open": "09:00", "close": "10:00"}}
        assert day_timeslot_label("Monday", 1, working_hours, 30) == "09:30-10:00"

    def test_index_does_not_need_the_full_day_length(self):
        """Checks that a single label only depends on its slot index."""
        working_hours = {"monday": {"open": "09:00", "close": "17:00"}}
        assert day_timeslot_label("Monday", 5, working_hours, 30) == PROD_DAY_TIMESLOTS[5]


DAY_OF_WEEK_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
OPEN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
WORKING_HOURS = {day.lower(): {"open": "09:00", "close": "17:00"} for day in OPEN_DAYS}


class TestDecodeDayOfWeekBitmask:
    def test_single_day(self):
        assert decode_day_of_week_bitmask(1, DAY_OF_WEEK_ORDER) == ["Monday"]

    def test_monday_plus_tuesday_is_1_plus_2(self):
        assert decode_day_of_week_bitmask(3, DAY_OF_WEEK_ORDER) == ["Monday", "Tuesday"]

    def test_matches_test_routine_consumer_fixture(self):
        # test_routine_consumer.py's routine_data() fixture uses day_of_week=5 (Mon+Wed)
        assert decode_day_of_week_bitmask(5, DAY_OF_WEEK_ORDER) == ["Monday", "Wednesday"]

    def test_zero_returns_empty(self):
        assert decode_day_of_week_bitmask(0, DAY_OF_WEEK_ORDER) == []

    def test_none_returns_empty(self):
        assert decode_day_of_week_bitmask(None, DAY_OF_WEEK_ORDER) == []


class TestRoutineTimeSlots:
    def test_single_day_single_slot(self):
        result = routine_time_slots(1, "09:00:00", "09:30:00", DAY_OF_WEEK_ORDER, OPEN_DAYS, WORKING_HOURS, 30)
        assert result == "0-0"

    def test_monday_plus_tuesday_is_1_plus_2(self):
        result = routine_time_slots(3, "09:00:00", "09:30:00", DAY_OF_WEEK_ORDER, OPEN_DAYS, WORKING_HOURS, 30)
        assert result == "0-0,1-0"

    def test_multi_slot_span_expands_to_consecutive_slots(self):
        # 09:00-10:00 is two 30min slots, __fillRoutines has no duration logic of its own
        result = routine_time_slots(1, "09:00:00", "10:00:00", DAY_OF_WEEK_ORDER, OPEN_DAYS, WORKING_HOURS, 30)
        assert result == "0-0,0-1"

    def test_bit_on_a_closed_day_is_dropped(self):
        # Monday (1) + Saturday (32), centre isn't open Saturday
        result = routine_time_slots(1 + 32, "09:00:00", "09:30:00", DAY_OF_WEEK_ORDER, OPEN_DAYS, WORKING_HOURS, 30)
        assert result == "0-0"

    def test_all_bits_on_closed_days_returns_none(self):
        result = routine_time_slots(32, "09:00:00", "09:30:00", DAY_OF_WEEK_ORDER, OPEN_DAYS, WORKING_HOURS, 30)
        assert result is None

    def test_zero_day_of_week_returns_none(self):
        result = routine_time_slots(0, "09:00:00", "09:30:00", DAY_OF_WEEK_ORDER, OPEN_DAYS, WORKING_HOURS, 30)
        assert result is None

    def test_end_not_after_start_defaults_to_one_slot(self):
        result = routine_time_slots(1, "09:30:00", "09:00:00", DAY_OF_WEEK_ORDER, OPEN_DAYS, WORKING_HOURS, 30)
        assert result == "0-1"
