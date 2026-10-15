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

    def test_flexible_activity_without_fixed_slots_maps_to_none(self):
        """Flexible activities come with None or "", both used to fail the message."""
        class FakeSelf:
            config = _config()
        assert CentreActivityConsumer.reformat_timeslots(FakeSelf, None) is None
        assert CentreActivityConsumer.reformat_timeslots(FakeSelf, "") is None
        assert CentreActivityConsumer.reformat_timeslots(FakeSelf, "  ") is None


class TestUpdateFixedTimeSlots:
    """Updates used to crash on fixed_time_slots None and end up dead-lettered."""

    def _consumer(self):
        from unittest.mock import MagicMock

        from messaging.mappers.mapper_util import map_centre_activity_update

        consumer = CentreActivityConsumer.__new__(CentreActivityConsumer)
        consumer.config = _config()
        consumer.map_centre_activity_update = map_centre_activity_update
        consumer.update_ref_centre_activity = MagicMock(return_value=(object(), False))
        return consumer

    def _update(self, consumer, **new_data):
        message = {
            "correlation_id": "c1", "centre_activity_id": 15, "modified_by": "u1",
            "new_data": {"id": 15, "activity_id": 7, "modified_date": "2026-10-15T20:49:00", "modified_by_id": "u1", **new_data},
        }
        result = consumer._handle_centre_activity_updated(None, message)
        update = consumer.update_ref_centre_activity.call_args.kwargs["centre_activity_update"] \
            if consumer.update_ref_centre_activity.called else None
        return result, update

    def test_fixed_to_flexible_clears_the_slots(self):
        from pear_schedule.models.processed_events_model import MessageProcessingResult

        result, update = self._update(self._consumer(), is_fixed=False, fixed_time_slots=None)
        assert result == MessageProcessingResult.SUCCESS
        dumped = update.model_dump(exclude_unset=True)
        assert dumped["IsFixed"] == "0"
        assert "FixedTimeSlots" in dumped and dumped["FixedTimeSlots"] is None

    def test_empty_string_clears_too(self):
        _, update = self._update(self._consumer(), is_fixed=False, fixed_time_slots="")
        assert update.model_dump(exclude_unset=True)["FixedTimeSlots"] is None

    def test_new_slots_are_reformatted(self):
        _, update = self._update(self._consumer(), is_fixed=True, fixed_time_slots="Tuesday 10:00")
        assert update.FixedTimeSlots == "1-2"

    def test_slots_not_sent_are_left_alone(self):
        _, update = self._update(self._consumer(), min_duration=60)
        assert "FixedTimeSlots" not in update.model_dump(exclude_unset=True)
