import pytest

from app import validate_group_timeslot_mapping
from tests.utils.scheduler_config import make_scheduler_config


def _config(**overrides):
    return make_scheduler_config(
        OPEN_DAYS=overrides.pop("OPEN_DAYS", ["Monday", "Tuesday"]),
        SLOTS_PER_DAY=overrides.pop("SLOTS_PER_DAY", {"Monday": 8, "Tuesday": 8}),
        WORKING_HOURS=overrides.pop("WORKING_HOURS", {
            "monday": {"open": "09:00", "close": "13:00"},
            "tuesday": {"open": "09:00", "close": "13:00"},
        }),
        **overrides,
    )


class TestValidateGroupTimeslotMapping:
    def test_converts_day_time_string_to_day_slot_tuple(self):
        config = _config(GROUP_TIMESLOT_MAPPING=["Monday 09:30"])
        result = validate_group_timeslot_mapping(config)
        assert result["GROUP_TIMESLOT_MAPPING"] == [(0, 1)]

    def test_mutates_config_in_place(self):
        config = _config(GROUP_TIMESLOT_MAPPING=["Monday 09:30"])
        result = validate_group_timeslot_mapping(config)
        assert result is config

    def test_no_drift_near_slot_boundary(self):
        config = _config(GROUP_TIMESLOT_MAPPING=["Monday 09:59"])
        result = validate_group_timeslot_mapping(config)
        assert result["GROUP_TIMESLOT_MAPPING"] == [(0, 1)]  # used to drift to (0, 2)

    def test_raises_when_centre_not_open_on_mapped_day(self):
        config = _config(OPEN_DAYS=["Monday"], SLOTS_PER_DAY={"Monday": 8},
                          WORKING_HOURS={"monday": {"open": "09:00", "close": "13:00"}},
                          GROUP_TIMESLOT_MAPPING=["Tuesday 09:30"])
        with pytest.raises(Exception, match="centre is not open"):
            validate_group_timeslot_mapping(config)

    def test_raises_when_slot_out_of_bounds(self):
        config = _config(SLOTS_PER_DAY={"Monday": 1, "Tuesday": 1},
                          GROUP_TIMESLOT_MAPPING=["Monday 12:30"])
        with pytest.raises(Exception, match="timing is out of bounds"):
            validate_group_timeslot_mapping(config)
