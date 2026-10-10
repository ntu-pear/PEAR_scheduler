"""
Unit tests for messaging/centre_activity_availability_consumer.py and its mapper config.

The CRUD layer is mocked, but the mappers and pydantic schemas are left REAL so that
mapping/validation regressions surface here. Payloads mirror exactly what
PEAR_activity_service publishes from app/crud/centre_activity_availability_crud.py
(serialize_data(model_to_dict(obj)) wrapped in the RabbitMQ {"data": ...} envelope).
"""

import pytest
from datetime import datetime, date, time
from unittest.mock import MagicMock, patch

from messaging.mappers.mapper_util import (
    mapper,
    map_centre_activity_availability_create,
)
from pear_schedule.models.processed_events_model import MessageProcessingResult


TIMESTAMP = "2026-10-09T10:30:00"


class FakeProcessedEvents:
    """Stands in for the processed_events table: empty until a CRUD call records it."""

    def __init__(self):
        self.recorded = set()

    def __call__(self, db, correlation_id):
        return correlation_id in self.recorded


@pytest.fixture
def consumer():
    with patch("messaging.centre_activity_availability_consumer.RabbitMQClient"):
        from messaging.centre_activity_availability_consumer import CentreActivityAvailabilityConsumer
        consumer = CentreActivityAvailabilityConsumer()

    processed = FakeProcessedEvents()
    consumer.is_event_already_processed = processed
    consumer.processed_events = processed

    def _record(correlation_id):
        processed.recorded.add(correlation_id)

    consumer.create_ref_centre_activity_availability = MagicMock(
        side_effect=lambda **kw: (_record(kw["correlation_id"]), (MagicMock(), False))[1]
    )
    consumer.update_ref_centre_activity_availability = MagicMock(
        side_effect=lambda **kw: (_record(kw["correlation_id"]), (MagicMock(), False))[1]
    )
    consumer.delete_ref_centre_activity_availability = MagicMock(
        side_effect=lambda **kw: (_record(kw["correlation_id"]), (MagicMock(), False))[1]
    )

    consumer.get_db = MagicMock(side_effect=lambda: iter([MagicMock()]))
    return consumer


def availability_data(**overrides):
    """An availability row as _availability_to_dict() serialises it in the activity service."""
    data = {
        "id": 12,
        "centre_activity_id": 5,
        "is_deleted": False,
        "days_of_week": 10,  # Tue + Thu
        "start_time": "14:00:00",
        "end_time": "16:00:00",
        "start_date": "2026-10-01",
        "end_date": "2026-12-31",
        "created_date": TIMESTAMP,
        "modified_date": None,
        "created_by_id": "1",
        "modified_by_id": None,
    }
    data.update(overrides)
    return data


def envelope(**data):
    return {"timestamp": TIMESTAMP, "source_service": "activity-service", "data": data}


def created_message(correlation_id="CORR-C", **overrides):
    return envelope(
        event_type="CENTRE_ACTIVITY_AVAILABILITY_CREATED",
        availability_id=12,
        availability_data=availability_data(**overrides),
        created_by="1",
        created_by_name="Supervisor",
        timestamp=TIMESTAMP,
        correlation_id=correlation_id,
    )


def updated_message(correlation_id="CORR-U", **new_overrides):
    return envelope(
        event_type="CENTRE_ACTIVITY_AVAILABILITY_UPDATED",
        availability_id=12,
        old_data=availability_data(),
        new_data=availability_data(modified_date=TIMESTAMP, modified_by_id="2", **new_overrides),
        changes={},
        modified_by="2",
        modified_by_name="Supervisor",
        timestamp=TIMESTAMP,
        correlation_id=correlation_id,
    )


def deleted_message(correlation_id="CORR-D"):
    return envelope(
        event_type="CENTRE_ACTIVITY_AVAILABILITY_DELETED",
        availability_id=12,
        availability_data=availability_data(),
        deleted_by="2",
        deleted_by_name="Supervisor",
        timestamp=TIMESTAMP,
        correlation_id=correlation_id,
    )


# ===== mapper =====

@pytest.mark.parametrize("raw, expected", [
    ("14:00:00", time(14, 0)),
    ("14:00", time(14, 0)),
    ("09:30:00+00:00", time(9, 30)),
    ("09:30:00Z", time(9, 30)),
    (time(8, 15), time(8, 15)),
    (None, None),
    ("not-a-time", None),
])
def test_parse_time(raw, expected):
    assert mapper._parse_time(raw) == expected


def test_map_create_converts_types():
    mapped = map_centre_activity_availability_create(availability_data())

    assert mapped["CentreActivityAvailabilityID"] == 12
    assert mapped["CentreActivityID"] == 5
    assert mapped["DaysOfWeek"] == 10
    assert mapped["StartTime"] == time(14, 0)
    assert mapped["EndTime"] == time(16, 0)
    assert mapped["StartDate"] == date(2026, 10, 1)
    assert mapped["EndDate"] == date(2026, 12, 31)
    assert mapped["IsDeleted"] == "0"
    assert mapped["CreatedDateTime"] == datetime(2026, 10, 9, 10, 30)
    assert mapped["CreatedById"] == "1"


def test_map_create_missing_required_field_fails():
    data = availability_data()
    del data["start_time"]
    assert map_centre_activity_availability_create(data) is None


# ===== consumer: created =====

def test_created_success(consumer):
    result = consumer._process_availability_message(created_message())

    assert result == MessageProcessingResult.SUCCESS
    kwargs = consumer.create_ref_centre_activity_availability.call_args.kwargs
    ref = kwargs["availability"]
    assert ref.CentreActivityAvailabilityID == 12
    assert ref.DaysOfWeek == 10
    assert ref.StartTime == time(14, 0)
    assert kwargs["skip_duplicate_check"] is False


def test_created_without_dates_success(consumer):
    result = consumer._process_availability_message(created_message(start_date=None, end_date=None))

    assert result == MessageProcessingResult.SUCCESS
    ref = consumer.create_ref_centre_activity_availability.call_args.kwargs["availability"]
    assert ref.StartDate is None
    assert ref.EndDate is None


def test_created_duplicate_is_skipped(consumer):
    consumer.processed_events.recorded.add("CORR-C")

    result = consumer._process_availability_message(created_message())

    assert result == MessageProcessingResult.DUPLICATE
    consumer.create_ref_centre_activity_availability.assert_not_called()


def test_created_sync_event_bypasses_duplicate_check(consumer):
    consumer.processed_events.recorded.add("CORR-C")
    message = created_message()
    message["data"]["is_sync_event"] = True

    result = consumer._process_availability_message(message)

    assert result == MessageProcessingResult.SUCCESS
    assert consumer.create_ref_centre_activity_availability.call_args.kwargs["skip_duplicate_check"] is True


def test_created_invalid_data_is_permanent_failure(consumer):
    result = consumer._process_availability_message(created_message(start_time=None))

    assert result == MessageProcessingResult.FAILED_PERMANENT
    consumer.create_ref_centre_activity_availability.assert_not_called()


def test_created_db_error_is_retryable(consumer):
    consumer.create_ref_centre_activity_availability.side_effect = Exception(
        'The INSERT statement conflicted with the FOREIGN KEY constraint ... table "dbo.REF_CENTRE_ACTIVITY"'
    )

    result = consumer._process_availability_message(created_message())

    assert result == MessageProcessingResult.FAILED_RETRYABLE


def test_created_before_centre_activity_synced_is_retryable(consumer):
    """An availability arriving before its centre activity must be requeued, not acked as a duplicate."""
    from pear_schedule.crud.ref_centre_activity_availability_crud import CentreActivityNotSyncedError

    consumer.create_ref_centre_activity_availability.side_effect = CentreActivityNotSyncedError(
        "Centre activity 5 does not exist in REF_CENTRE_ACTIVITY yet"
    )

    result = consumer._process_availability_message(created_message())

    assert result == MessageProcessingResult.FAILED_RETRYABLE
    assert "CORR-C" not in consumer.processed_events.recorded
    assert consumer._handle_message_wrapper(created_message()) is False  # nack -> requeue


def test_missing_envelope_fields_is_permanent_failure(consumer):
    message = created_message()
    del message["data"]["availability_id"]

    assert consumer._process_availability_message(message) == MessageProcessingResult.FAILED_PERMANENT


def test_unknown_event_type_is_permanent_failure(consumer):
    message = created_message()
    message["data"]["event_type"] = "CENTRE_ACTIVITY_AVAILABILITY_EXPLODED"

    assert consumer._process_availability_message(message) == MessageProcessingResult.FAILED_PERMANENT


# ===== consumer: updated =====

def test_updated_success_overwrites_all_fields(consumer):
    result = consumer._process_availability_message(
        updated_message(start_time="10:00:00", end_time="11:00:00", start_date=None)
    )

    assert result == MessageProcessingResult.SUCCESS
    kwargs = consumer.update_ref_centre_activity_availability.call_args.kwargs
    update = kwargs["availability_update"]
    assert kwargs["availability_id"] == 12
    assert update.StartTime == time(10, 0)
    assert update.EndTime == time(11, 0)
    assert update.ModifiedById == "2"
    # A cleared date must be sent through explicitly so the REF row is cleared too
    dumped = update.model_dump(exclude_unset=True)
    assert "StartDate" in dumped and dumped["StartDate"] is None


def test_updated_missing_row_falls_back_to_create(consumer):
    consumer.update_ref_centre_activity_availability.side_effect = (
        lambda **kw: (consumer.processed_events.recorded.add(kw["correlation_id"]), (None, False))[1]
    )

    result = consumer._process_availability_message(updated_message())

    assert result == MessageProcessingResult.SUCCESS
    kwargs = consumer.create_ref_centre_activity_availability.call_args.kwargs
    assert kwargs["record_event"] is False
    assert kwargs["availability"].CentreActivityAvailabilityID == 12


def test_updated_duplicate_is_skipped(consumer):
    consumer.processed_events.recorded.add("CORR-U")

    assert consumer._process_availability_message(updated_message()) == MessageProcessingResult.DUPLICATE
    consumer.update_ref_centre_activity_availability.assert_not_called()


# ===== consumer: deleted =====

def test_deleted_success(consumer):
    result = consumer._process_availability_message(deleted_message())

    assert result == MessageProcessingResult.SUCCESS
    kwargs = consumer.delete_ref_centre_activity_availability.call_args.kwargs
    assert kwargs["availability_id"] == 12
    assert kwargs["availability_delete"].ModifiedById == "2"
    assert kwargs["availability_delete"].UpdatedDateTime == datetime(2026, 10, 9, 10, 30)


def test_deleted_db_error_is_retryable(consumer):
    consumer.delete_ref_centre_activity_availability.side_effect = Exception("db down")

    assert consumer._process_availability_message(deleted_message()) == MessageProcessingResult.FAILED_RETRYABLE


# ===== ack / nack =====

@pytest.mark.parametrize("result, should_ack", [
    (MessageProcessingResult.SUCCESS, True),
    (MessageProcessingResult.DUPLICATE, True),
    (MessageProcessingResult.FAILED_PERMANENT, True),
    (MessageProcessingResult.FAILED_RETRYABLE, False),
])
def test_wrapper_ack_mapping(consumer, result, should_ack):
    consumer._process_availability_message = MagicMock(return_value=result)
    assert consumer._handle_message_wrapper(created_message()) is should_ack


def test_registered_in_consumer_manager():
    from messaging.consumer_manager import create_scheduler_consumer_manager
    from messaging.centre_activity_availability_consumer import CentreActivityAvailabilityConsumer

    manager = create_scheduler_consumer_manager()
    assert manager.consumers["centre_activity_availability"] is CentreActivityAvailabilityConsumer
