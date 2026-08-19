from messaging.centre_activity_consumer import CentreActivityConsumer
from tests.utils.scheduler_config import make_scheduler_config


def _config(**overrides):
    return make_scheduler_config(
        OPEN_DAYS=["Monday", "Tuesday"],
        SLOTS_PER_DAY={"Monday": 8, "Tuesday": 8},
        WORKING_HOURS={"monday": {"open": "09:00", "close": "13:00"},
                       "tuesday": {"open": "09:00", "close": "13:00"}},
        **overrides,
    )


class TestReformatTimeslots:
    def test_single_entry_converts_to_day_slot_string(self):
        class FakeSelf:
            config = _config()
        assert CentreActivityConsumer.reformat_timeslots(FakeSelf, "Monday 09:30") == "0-1"

    def test_multiple_comma_separated_entries(self):
        class FakeSelf:
            config = _config()
        result = CentreActivityConsumer.reformat_timeslots(FakeSelf, "Monday 09:30,Tuesday 12:00")
        assert result == "0-1,1-6"

    def test_no_drift_near_slot_boundary(self):
        class FakeSelf:
            config = _config()
        assert CentreActivityConsumer.reformat_timeslots(FakeSelf, "Monday 09:59") == "0-1"  # used to be "0-2"
