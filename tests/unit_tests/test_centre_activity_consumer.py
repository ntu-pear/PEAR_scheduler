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


class TestActivityNotSyncedYet:
    """A centre activity that arrives before its activity used to be dropped as a duplicate."""

    CREATED = {
        "correlation_id": "c2", "centre_activity_id": 40, "created_by": "u1",
        "centre_activity_data": {
            "id": 40, "activity_id": 99, "is_compulsory": False, "is_fixed": False, "is_group": False,
            "start_date": "2026-10-01", "end_date": "2026-12-31", "min_duration": 30, "max_duration": 30,
            "min_people_req": 1, "fixed_time_slots": None,
            "created_date": "2026-10-16T10:00:00", "modified_date": "2026-10-16T10:00:00",
        },
    }

    def _consumer(self, monkeypatch):
        from unittest.mock import MagicMock

        from messaging import centre_activity_consumer
        from messaging.mappers.mapper_util import map_centre_activity_create, map_centre_activity_update

        sleep = MagicMock()
        monkeypatch.setattr(centre_activity_consumer.time, "sleep", sleep)
        consumer = CentreActivityConsumer.__new__(CentreActivityConsumer)
        consumer.config = _config()
        consumer.map_centre_activity_create = map_centre_activity_create
        consumer.map_centre_activity_update = map_centre_activity_update
        consumer.create_ref_centre_activity = MagicMock()
        consumer.update_ref_centre_activity = MagicMock()
        return consumer, sleep

    def test_created_waits_then_retries(self, monkeypatch):
        from pear_schedule.crud.ref_centre_activity_crud import ActivityNotSyncedError
        from pear_schedule.models.processed_events_model import MessageProcessingResult

        consumer, sleep = self._consumer(monkeypatch)
        consumer.create_ref_centre_activity.side_effect = ActivityNotSyncedError("Activity 99 does not exist in REF_ACTIVITY yet")

        assert consumer._handle_centre_activity_created(None, self.CREATED) == MessageProcessingResult.FAILED_RETRYABLE
        sleep.assert_called_once_with(2)

    def test_retry_is_requeued_not_acked(self, monkeypatch):
        from pear_schedule.crud.ref_centre_activity_crud import ActivityNotSyncedError

        consumer, _ = self._consumer(monkeypatch)
        consumer.create_ref_centre_activity.side_effect = ActivityNotSyncedError("not yet")
        consumer.get_db = lambda: iter([None])
        consumer.is_event_already_processed = lambda db, key: False
        consumer._flush_logs = lambda: None
        message = {"data": {**self.CREATED, "event_type": "CENTRE_ACTIVITY_CREATED"}}

        assert consumer._handle_message_wrapper(message) is False

    def test_sync_update_of_a_missing_row_creates_it(self, monkeypatch):
        """The fallback create used to see the update's own record and skip as a duplicate."""
        from pear_schedule.models.processed_events_model import MessageProcessingResult

        consumer, _ = self._consumer(monkeypatch)
        consumer.update_ref_centre_activity.return_value = (None, False)
        consumer.create_ref_centre_activity.return_value = (object(), False)
        message = {"correlation_id": "c3", "centre_activity_id": 40, "modified_by": "u1", "is_sync_event": True,
                   "new_data": self.CREATED["centre_activity_data"]}

        assert consumer._handle_centre_activity_updated(None, message) == MessageProcessingResult.SUCCESS
        kwargs = consumer.create_ref_centre_activity.call_args.kwargs
        assert kwargs["skip_duplicate_check"] is True and kwargs["record_event"] is False

    def test_sync_create_waits_for_the_activity_too(self, monkeypatch):
        from pear_schedule.crud.ref_centre_activity_crud import ActivityNotSyncedError
        from pear_schedule.models.processed_events_model import MessageProcessingResult

        consumer, sleep = self._consumer(monkeypatch)
        consumer.update_ref_centre_activity.return_value = (None, False)
        consumer.create_ref_centre_activity.side_effect = ActivityNotSyncedError("not yet")
        message = {"correlation_id": "c4", "centre_activity_id": 40, "modified_by": "u1", "is_sync_event": True,
                   "new_data": self.CREATED["centre_activity_data"]}

        assert consumer._handle_centre_activity_updated(None, message) == MessageProcessingResult.FAILED_RETRYABLE
        sleep.assert_called_once_with(2)
