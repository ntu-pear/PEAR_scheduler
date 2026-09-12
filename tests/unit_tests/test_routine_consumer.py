"""
Unit tests for messaging/routine_consumer.py

The CRUD layer is mocked, but the mappers and pydantic schemas are left REAL so
that mapping/validation regressions surface here rather than in staging. Payloads
mirror exactly what PEAR_activity_service publishes from app/crud/routine_crud.py.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from pear_schedule.models.processed_events_model import MessageProcessingResult
from tests.utils.scheduler_config import make_scheduler_config


TIMESTAMP = "2025-09-11T10:30:00"


class FakeProcessedEvents:
    """Stands in for the processed_events table: empty until a CRUD call records it."""

    def __init__(self):
        self.recorded = set()

    def __call__(self, db, correlation_id):
        return correlation_id in self.recorded


@pytest.fixture
def consumer():
    with patch("messaging.routine_consumer.RabbitMQClient"):
        from messaging.routine_consumer import RoutineConsumer
        consumer = RoutineConsumer()

    consumer.config = make_scheduler_config()

    processed = FakeProcessedEvents()
    consumer.is_event_already_processed = processed
    consumer.processed_events = processed

    def _record(correlation_id):
        processed.recorded.add(correlation_id)

    consumer.create_ref_activity_routine = MagicMock(
        side_effect=lambda **kw: (_record(kw["correlation_id"]), (MagicMock(), False))[1]
    )
    consumer.update_ref_activity_routine = MagicMock(
        side_effect=lambda **kw: (_record(kw["correlation_id"]), (MagicMock(), False))[1]
    )
    consumer.delete_ref_activity_routine = MagicMock(
        side_effect=lambda **kw: (_record(kw["correlation_id"]), (MagicMock(), False))[1]
    )

    consumer.get_db = MagicMock(side_effect=lambda: iter([MagicMock()]))
    return consumer


def routine_data(**overrides):
    """A routine row as _routine_to_dict() serialises it in the activity service."""
    data = {
        "id": 7,
        "patient_id": 4,
        "activity_id": 9,
        "name": "Morning Walk",
        "day_of_week": 5,
        "start_time": "09:00:00",
        "end_time": "10:00:00",
        "start_date": "2025-09-01",
        "end_date": "2025-12-31",
        "is_deleted": False,
        "created_date": TIMESTAMP,
        "modified_date": TIMESTAMP,
        "created_by_id": "1",
        "modified_by_id": "1",
        "activity_title": "Walking",
    }
    data.update(overrides)
    return data


def envelope(payload):
    """RabbitMQClient.publish wraps every payload in this envelope."""
    return {
        "timestamp": TIMESTAMP,
        "source_service": "activity-service",
        "data": payload,
    }


def created_event(correlation_id="corr-create-1", **routine_overrides):
    return envelope({
        "event_type": "ROUTINE_CREATED",
        "routine_id": 7,
        "routine_data": routine_data(**routine_overrides),
        "created_by": "1",
        "created_by_name": "Test User",
        "timestamp": TIMESTAMP,
        "correlation_id": correlation_id,
    })


def updated_event(correlation_id="corr-update-1", new_data=None, **extra):
    payload = {
        "event_type": "ROUTINE_UPDATED",
        "routine_id": 7,
        "old_data": routine_data(),
        "new_data": routine_data() if new_data is None else new_data,
        "changes": {"name": {"old": "Morning Walk", "new": "Evening Walk"}},
        "modified_by": "1",
        "modified_by_name": "Test User",
        "timestamp": TIMESTAMP,
        "correlation_id": correlation_id,
    }
    payload.update(extra)
    return envelope(payload)


def deleted_event(correlation_id="corr-delete-1", **extra):
    payload = {
        "event_type": "ROUTINE_DELETED",
        "routine_id": 7,
        "routine_data": routine_data(is_deleted=True),
        "deleted_by": "1",
        "deleted_by_name": "Test User",
        "timestamp": TIMESTAMP,
        "correlation_id": correlation_id,
    }
    payload.update(extra)
    return envelope(payload)


class TestRoutineCreated:
    def test_create_event_succeeds(self, consumer):
        result = consumer._process_routine_message(created_event())

        assert result == MessageProcessingResult.SUCCESS
        assert consumer.create_ref_activity_routine.call_count == 1

    def test_create_maps_identifiers_onto_schema(self, consumer):
        consumer._process_routine_message(created_event())

        routine = consumer.create_ref_activity_routine.call_args.kwargs["routine"]
        assert routine.RoutineID == 7
        assert routine.PatientID == 4
        assert routine.ActivityID == 9
        assert routine.IsDeleted == "0"
        assert routine.IncludeInSchedule == "1"
        assert routine.CreatedDateTime == datetime(2025, 9, 11, 10, 30, 0)

    def test_create_uses_event_created_by(self, consumer):
        consumer._process_routine_message(created_event())

        assert consumer.create_ref_activity_routine.call_args.kwargs["created_by"] == "1"

    def test_schedule_details_are_now_mapped(self, consumer):
        """day_of_week is a bitmask. Fixture uses 5 = Monday+Wednesday (1+4),
        09:00:00-10:00:00 is two 30min slots on each day."""
        consumer._process_routine_message(created_event())

        routine = consumer.create_ref_activity_routine.call_args.kwargs["routine"]
        assert routine.RoutineTimeSlots == "0-0,0-1,2-0,2-1"
        assert routine.RoutineIssues is None

    def test_missing_required_identifier_is_permanent_failure(self, consumer):
        result = consumer._process_routine_message(
            created_event(patient_id=None)
        )

        assert result == MessageProcessingResult.FAILED_PERMANENT
        consumer.create_ref_activity_routine.assert_not_called()


class TestRoutineUpdated:
    def test_update_event_succeeds(self, consumer):
        result = consumer._process_routine_message(updated_event())

        assert result == MessageProcessingResult.SUCCESS
        assert consumer.update_ref_activity_routine.call_args.kwargs["routine_id"] == 7

    def test_update_without_is_deleted_still_applies(self, consumer):
        """A partial payload (e.g. DriftSync) must not be dropped. IsDeleted is
        Optional on RefActivityRoutineUpdate and must default to None."""
        partial = routine_data()
        del partial["is_deleted"]

        result = consumer._process_routine_message(updated_event(new_data=partial))

        assert result == MessageProcessingResult.SUCCESS
        consumer.update_ref_activity_routine.assert_called_once()

    def test_update_on_missing_routine_is_acked(self, consumer):
        # IdempotencyService still records the event when the operation is a no-op
        consumer.update_ref_activity_routine = MagicMock(
            side_effect=lambda **kw: (
                consumer.processed_events.recorded.add(kw["correlation_id"]), (None, False)
            )[1]
        )

        result = consumer._process_routine_message(updated_event())

        assert result == MessageProcessingResult.SUCCESS

    def test_sync_event_bypasses_idempotency_check(self, consumer):
        consumer.processed_events.recorded.add("corr-sync-1")

        result = consumer._process_routine_message(
            updated_event(correlation_id="corr-sync-1", is_sync_event=True,
                          sync_reason="drift_detected")
        )

        assert result == MessageProcessingResult.SUCCESS
        assert consumer.update_ref_activity_routine.call_args.kwargs["skip_duplicate_check"] is True


class TestRoutineDeleted:
    def test_delete_event_succeeds(self, consumer):
        result = consumer._process_routine_message(deleted_event())

        assert result == MessageProcessingResult.SUCCESS
        assert consumer.delete_ref_activity_routine.call_args.kwargs["routine_id"] == 7

    def test_delete_uses_event_timestamp(self, consumer):
        consumer._process_routine_message(deleted_event())

        payload = consumer.delete_ref_activity_routine.call_args.kwargs["routine_delete"]
        assert payload.UpdatedDateTime == datetime(2025, 9, 11, 10, 30, 0)
        assert payload.ModifiedById == "1"

    def test_delete_without_timestamp_falls_back_to_now(self, consumer):
        """Missing timestamp must not nack forever - adhoc_consumer falls back to
        datetime.now() and routine should behave the same."""
        event = deleted_event()
        del event["data"]["timestamp"]

        result = consumer._process_routine_message(event)

        assert result == MessageProcessingResult.SUCCESS
        payload = consumer.delete_ref_activity_routine.call_args.kwargs["routine_delete"]
        assert isinstance(payload.UpdatedDateTime, datetime)

    def test_delete_with_null_timestamp_falls_back_to_now(self, consumer):
        result = consumer._process_routine_message(deleted_event(timestamp=None))

        assert result == MessageProcessingResult.SUCCESS
        payload = consumer.delete_ref_activity_routine.call_args.kwargs["routine_delete"]
        assert isinstance(payload.UpdatedDateTime, datetime)

    def test_delete_with_unparseable_timestamp_falls_back_to_now(self, consumer):
        result = consumer._process_routine_message(deleted_event(timestamp="not-a-date"))

        assert result == MessageProcessingResult.SUCCESS
        payload = consumer.delete_ref_activity_routine.call_args.kwargs["routine_delete"]
        assert isinstance(payload.UpdatedDateTime, datetime)


class TestMessageParsing:
    @pytest.mark.parametrize("missing", ["correlation_id", "event_type", "routine_id"])
    def test_missing_required_field_is_permanent_failure(self, consumer, missing):
        event = created_event()
        del event["data"][missing]

        assert consumer._process_routine_message(event) == MessageProcessingResult.FAILED_PERMANENT

    def test_unknown_event_type_is_permanent_failure(self, consumer):
        event = created_event()
        event["data"]["event_type"] = "ROUTINE_ARCHIVED"

        assert consumer._process_routine_message(event) == MessageProcessingResult.FAILED_PERMANENT

    def test_already_processed_correlation_id_is_duplicate(self, consumer):
        consumer.processed_events.recorded.add("corr-create-1")

        result = consumer._process_routine_message(created_event())

        assert result == MessageProcessingResult.DUPLICATE
        consumer.create_ref_activity_routine.assert_not_called()

    def test_crud_exception_is_retryable(self, consumer):
        consumer.create_ref_activity_routine = MagicMock(side_effect=RuntimeError("db down"))

        assert consumer._process_routine_message(created_event()) == MessageProcessingResult.FAILED_RETRYABLE

    def test_business_rule_violation_is_permanent(self, consumer):
        consumer.create_ref_activity_routine = MagicMock(
            side_effect=ValueError("RoutineID 7 already exists.")
        )

        assert consumer._process_routine_message(created_event()) == MessageProcessingResult.FAILED_PERMANENT


class TestAcknowledgement:
    @pytest.mark.parametrize("result,should_ack", [
        (MessageProcessingResult.SUCCESS, True),
        (MessageProcessingResult.DUPLICATE, True),
        (MessageProcessingResult.FAILED_PERMANENT, True),   # goes to DLQ, do not requeue
        (MessageProcessingResult.FAILED_RETRYABLE, False),  # nack and requeue
    ])
    def test_ack_semantics(self, consumer, result, should_ack):
        consumer._process_routine_message = MagicMock(return_value=result)

        assert consumer._handle_message_wrapper(created_event()) is should_ack

    def test_shutdown_signal_nacks_without_processing(self, consumer):
        import threading
        shutdown = threading.Event()
        shutdown.set()
        consumer.shutdown_event = shutdown
        consumer._process_routine_message = MagicMock()

        assert consumer._handle_message_wrapper(created_event()) is False
        consumer._process_routine_message.assert_not_called()


class TestHealthStatus:
    def test_reports_the_three_routine_queues(self, consumer):
        status = consumer.get_health_status()

        assert status["service"] == "routine_consumer"
        assert status["queues"] == [
            "scheduler.activity.routine.created",
            "scheduler.activity.routine.updated",
            "scheduler.activity.routine.deleted",
        ]
