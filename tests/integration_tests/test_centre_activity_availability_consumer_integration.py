"""
Integration tests for Scheduler Service Centre Activity Availability Consumer
Tests the flow: RabbitMQ Message -> Centre Activity Availability Consumer -> REF_CENTRE_ACTIVITY_AVAILABILITY table update -> PROCESSED_EVENTS tracking

Run Pytest with command: pytest tests/integration_tests/test_centre_activity_availability_consumer_integration.py -v -s

Messages mirror what PEAR_activity_service publishes from app/crud/centre_activity_availability_crud.py.
Cleanup only removes the rows this file creates (availability IDs 8801-8899 and CENTRE_ACTIVITY_AVAILABILITY_* processed events).
The seeded REF_ACTIVITY(8801) and REF_CENTRE_ACTIVITY(8801) are left in place for reruns.
SQL Commands to clear DB manually:
DELETE FROM [dbo].[REF_CENTRE_ACTIVITY_AVAILABILITY] WHERE CentreActivityAvailabilityID BETWEEN 8801 AND 8899;
DELETE FROM [dbo].[PROCESSED_EVENTS] WHERE event_type LIKE 'CENTRE_ACTIVITY_AVAILABILITY_%';
"""

import json
import uuid
from datetime import date, datetime, time
from typing import Any, Dict

import pytest

from messaging.centre_activity_availability_consumer import CentreActivityAvailabilityConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
from pear_schedule.models.ref_activity_model import RefActivity
from pear_schedule.models.ref_centre_activity_availability_model import RefCentreActivityAvailability
from pear_schedule.models.ref_centre_activity_model import RefCentreActivity

TEST_ACTIVITY_ID = 8801
TEST_CENTRE_ACTIVITY_ID = 8801
MISSING_CENTRE_ACTIVITY_ID = 8899
TUE_THU = 2 + 8


# ===== Database Fixture =====
@pytest.fixture(scope="function")
def integration_db():
    """
    Uses the real database connection from pear_schedule.database.
    Each test gets a fresh session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def setup_test_centre_activity(integration_db):
    """
    Availabilities reference REF_CENTRE_ACTIVITY, which references REF_ACTIVITY,
    so both must exist before an availability can be written.
    """
    created = []

    if not integration_db.query(RefActivity).filter(RefActivity.ActivityID == TEST_ACTIVITY_ID).first():
        integration_db.add(RefActivity(
            ActivityID=TEST_ACTIVITY_ID,
            ActivityTitle="Availability Test Activity",
            ActivityDesc="Test activity for centre activity availability integration tests",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        ))
        created.append(f"REF_ACTIVITY {TEST_ACTIVITY_ID}")

    if not integration_db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == TEST_CENTRE_ACTIVITY_ID).first():
        integration_db.add(RefCentreActivity(
            CentreActivityID=TEST_CENTRE_ACTIVITY_ID,
            ActivityID=TEST_ACTIVITY_ID,
            IsDeleted="0",
            IsCompulsory="0",
            IsFixed="0",
            IsGroup="0",
            StartDate=date(2026, 1, 1),
            EndDate=date(2999, 12, 31),
            MinDuration=60,
            MaxDuration=60,
            MinPeopleReq=1,
            FixedTimeSlots=None,
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        ))
        created.append(f"REF_CENTRE_ACTIVITY {TEST_CENTRE_ACTIVITY_ID}")

    integration_db.commit()
    print(f"\n[SETUP] Created: {created}" if created else "\n[SETUP] Test activity and centre activity already exist")

    # The FK test relies on this centre activity being absent
    assert integration_db.query(RefCentreActivity).filter(
        RefCentreActivity.CentreActivityID == MISSING_CENTRE_ACTIVITY_ID
    ).first() is None, f"REF_CENTRE_ACTIVITY {MISSING_CENTRE_ACTIVITY_ID} must not exist for these tests"

    yield


@pytest.fixture
def availability_consumer():
    """Fixture for CentreActivityAvailabilityConsumer instance (never connects to RabbitMQ in these tests)."""
    consumer = CentreActivityAvailabilityConsumer()
    yield consumer
    if consumer.client:
        consumer.client.close()


# NOTE: Only removes rows created by this file, so it is safe on a shared test DB.
@pytest.fixture(autouse=True)
def cleanup_test_data(integration_db):
    yield
    try:
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.event_type.like("CENTRE_ACTIVITY_AVAILABILITY_%")
        ).delete(synchronize_session=False)
        integration_db.query(RefCentreActivityAvailability).filter(
            RefCentreActivityAvailability.CentreActivityAvailabilityID.between(8801, 8899)
        ).delete(synchronize_session=False)
        integration_db.commit()
        print("\n[CLEANUP] Test data cleared successfully")
    except Exception as e:
        integration_db.rollback()
        print(f"\n[CLEANUP] Warning: Failed to cleanup test data: {str(e)}")


# ===== Helper Functions =====

def availability_data(availability_id: int, **overrides) -> Dict[str, Any]:
    """An availability row as serialize_data(model_to_dict()) produces it in the activity service."""
    data = {
        "id": availability_id,
        "centre_activity_id": TEST_CENTRE_ACTIVITY_ID,
        "is_deleted": False,
        "days_of_week": TUE_THU,
        "start_time": "14:00:00",
        "end_time": "15:00:00",
        "start_date": "2026-10-01",
        "end_date": "2026-12-31",
        "created_date": datetime.now().isoformat(),
        "modified_date": None,
        "created_by_id": "test-user-1",
        "modified_by_id": None,
    }
    data.update(overrides)
    return data


def new_correlation_id() -> str:
    return str(uuid.uuid4()).upper()


def created_message(data: Dict[str, Any], correlation_id: str = None, is_sync_event: bool = False) -> Dict[str, Any]:
    message_data = {
        "correlation_id": correlation_id or new_correlation_id(),
        "event_type": "CENTRE_ACTIVITY_AVAILABILITY_CREATED",
        "availability_id": data["id"],
        "availability_data": data,
        "created_by": data.get("created_by_id", "test-user"),
        "created_by_name": "Test User",
        "timestamp": datetime.now().isoformat(),
    }
    if is_sync_event:
        message_data["is_sync_event"] = True
        message_data["sync_reason"] = "initial_backfill"
    return {"timestamp": datetime.now().isoformat(), "source_service": "activity-service", "data": message_data}


def updated_message(old_data: Dict[str, Any], new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    changes = {
        key: {"old": old_data[key], "new": new_data[key]}
        for key in new_data
        if key in old_data and old_data[key] != new_data[key]
    }
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id or new_correlation_id(),
            "event_type": "CENTRE_ACTIVITY_AVAILABILITY_UPDATED",
            "availability_id": new_data["id"],
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("modified_by_id") or "test-user",
            "modified_by_name": "Test User",
            "timestamp": datetime.now().isoformat(),
        }
    }


def deleted_message(data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id or new_correlation_id(),
            "event_type": "CENTRE_ACTIVITY_AVAILABILITY_DELETED",
            "availability_id": data["id"],
            "availability_data": data,
            "deleted_by": "test-user-2",
            "deleted_by_name": "Test User",
            "timestamp": datetime.now().isoformat(),
        }
    }


def get_ref_availability(db, availability_id: int):
    db.expire_all()
    return db.query(RefCentreActivityAvailability).filter(
        RefCentreActivityAvailability.CentreActivityAvailabilityID == availability_id
    ).first()


def get_processed_event(db, correlation_id: str):
    db.expire_all()
    return db.query(ProcessedEvent).filter(ProcessedEvent.correlation_id == correlation_id).first()


# ===== Create Tests =====

class TestConsumerCentreActivityAvailabilityCreate:
    """Test consumer processing of CENTRE_ACTIVITY_AVAILABILITY_CREATED events"""

    def test_create_availability_processes_message_successfully(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: CENTRE_ACTIVITY_AVAILABILITY_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_CENTRE_ACTIVITY_AVAILABILITY row is written with converted types and PROCESSED_EVENTS records it

        Goal: Verify the full create path against a real database, including time and date conversion.
        """
        correlation_id = new_correlation_id()
        data = availability_data(8801)

        result = availability_consumer._process_availability_message(created_message(data, correlation_id))

        assert result == MessageProcessingResult.SUCCESS

        ref = get_ref_availability(integration_db, 8801)
        assert ref is not None
        assert ref.CentreActivityID == TEST_CENTRE_ACTIVITY_ID
        assert ref.DaysOfWeek == TUE_THU
        assert ref.StartTime == time(14, 0)
        assert ref.EndTime == time(15, 0)
        assert ref.StartDate == date(2026, 10, 1)
        assert ref.EndDate == date(2026, 12, 31)
        assert ref.IsDeleted == "0"

        print(f"DONE: Created REF_CENTRE_ACTIVITY_AVAILABILITY ID: {ref.CentreActivityAvailabilityID}")

        processed_event = get_processed_event(integration_db, correlation_id)
        assert processed_event is not None
        assert processed_event.event_type == "CENTRE_ACTIVITY_AVAILABILITY_CREATED"
        assert processed_event.aggregate_id == "8801"
        assert json.loads(processed_event.operation_result)["status"] == "success"

    def test_create_without_dates_stores_nulls(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: An availability with no date range (applies indefinitely)
        WHEN: Consumer processes the CREATED message
        THEN: StartDate and EndDate are stored as NULL

        Goal: Verify optional dates are accepted and stored as empty.
        """
        data = availability_data(8802, start_date=None, end_date=None)

        result = availability_consumer._process_availability_message(created_message(data))

        assert result == MessageProcessingResult.SUCCESS
        ref = get_ref_availability(integration_db, 8802)
        assert ref.StartDate is None
        assert ref.EndDate is None

    def test_duplicate_create_message_is_idempotent(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: The same CREATED message delivered twice
        WHEN: Consumer processes the duplicate
        THEN: Returns DUPLICATE and leaves exactly one row and one PROCESSED_EVENTS record

        Goal: Verify a redelivered message is not applied twice.
        """
        correlation_id = new_correlation_id()
        message = created_message(availability_data(8803), correlation_id)

        assert availability_consumer._process_availability_message(message) == MessageProcessingResult.SUCCESS
        assert availability_consumer._process_availability_message(message) == MessageProcessingResult.DUPLICATE

        integration_db.expire_all()
        assert integration_db.query(RefCentreActivityAvailability).filter(
            RefCentreActivityAvailability.CentreActivityAvailabilityID == 8803
        ).count() == 1
        assert integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count() == 1

    def test_sync_event_rerun_overwrites_existing_row(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: The backfill sync script is run twice, and the availability changed in between
        WHEN: Consumer processes both sync CREATED messages
        THEN: Both succeed and the row holds the latest values

        Goal: Verify the sync script can be re-run safely and converges to the source data.
        """
        first = created_message(availability_data(8804), is_sync_event=True)
        second = created_message(
            availability_data(8804, days_of_week=16, start_time="10:00:00", end_time="11:00:00"),
            is_sync_event=True
        )

        assert availability_consumer._process_availability_message(first) == MessageProcessingResult.SUCCESS
        assert availability_consumer._process_availability_message(second) == MessageProcessingResult.SUCCESS

        ref = get_ref_availability(integration_db, 8804)
        assert ref.DaysOfWeek == 16
        assert ref.StartTime == time(10, 0)
        assert ref.EndTime == time(11, 0)

    def test_create_before_centre_activity_synced_is_retryable(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: A CREATED message whose centre activity is not in REF_CENTRE_ACTIVITY yet
        WHEN: Consumer processes the message
        THEN: Returns FAILED_RETRYABLE, writes no row and records no PROCESSED_EVENTS entry

        Goal: Verify the message is retried (and eventually dead-lettered) rather than dropped as a duplicate.
        """
        correlation_id = new_correlation_id()
        data = availability_data(8805, centre_activity_id=MISSING_CENTRE_ACTIVITY_ID)

        result = availability_consumer._process_availability_message(created_message(data, correlation_id))

        assert result == MessageProcessingResult.FAILED_RETRYABLE
        assert get_ref_availability(integration_db, 8805) is None
        # No processed event, so the redelivered message is not mistaken for a duplicate
        assert get_processed_event(integration_db, correlation_id) is None

    def test_create_with_invalid_data_fails_permanently(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: A CREATED message missing its start time
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT and writes nothing

        Goal: Verify bad data is not retried.
        """
        correlation_id = new_correlation_id()
        data = availability_data(8806, start_time=None)

        result = availability_consumer._process_availability_message(created_message(data, correlation_id))

        assert result == MessageProcessingResult.FAILED_PERMANENT
        assert get_ref_availability(integration_db, 8806) is None
        assert get_processed_event(integration_db, correlation_id) is None


# ===== Update Tests =====

class TestConsumerCentreActivityAvailabilityUpdate:
    """Test consumer processing of CENTRE_ACTIVITY_AVAILABILITY_UPDATED events"""

    def test_update_availability_overwrites_row(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: An existing availability
        WHEN: Consumer processes an UPDATED message with new days, times and a cleared start date
        THEN: The row holds the new values, including the cleared date

        Goal: Verify updates replace the whole row so cleared fields are cleared too.
        """
        old_data = availability_data(8811)
        assert availability_consumer._process_availability_message(created_message(old_data)) == MessageProcessingResult.SUCCESS

        new_data = availability_data(
            8811, days_of_week=16, start_time="09:00:00", end_time="10:00:00",
            start_date=None, modified_date=datetime.now().isoformat(), modified_by_id="test-user-2"
        )
        correlation_id = new_correlation_id()

        result = availability_consumer._process_availability_message(updated_message(old_data, new_data, correlation_id))

        assert result == MessageProcessingResult.SUCCESS
        ref = get_ref_availability(integration_db, 8811)
        assert ref.DaysOfWeek == 16
        assert ref.StartTime == time(9, 0)
        assert ref.EndTime == time(10, 0)
        assert ref.StartDate is None
        assert ref.EndDate == date(2026, 12, 31)
        assert ref.ModifiedById == "test-user-2"

        processed_event = get_processed_event(integration_db, correlation_id)
        assert processed_event.event_type == "CENTRE_ACTIVITY_AVAILABILITY_UPDATED"

    def test_update_for_missing_row_creates_it(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: An UPDATED message for an availability the scheduler never received
        WHEN: Consumer processes the message
        THEN: The row is created from the new data and exactly one PROCESSED_EVENTS record exists

        Goal: Verify a lost CREATED event is recovered by the next update without a duplicate-key failure.
        """
        old_data = availability_data(8812)
        new_data = availability_data(8812, start_time="15:00:00", end_time="16:00:00")
        correlation_id = new_correlation_id()

        result = availability_consumer._process_availability_message(updated_message(old_data, new_data, correlation_id))

        assert result == MessageProcessingResult.SUCCESS
        ref = get_ref_availability(integration_db, 8812)
        assert ref is not None
        assert ref.StartTime == time(15, 0)

        integration_db.expire_all()
        assert integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count() == 1

    def test_duplicate_update_message_is_idempotent(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: The same UPDATED message delivered twice
        WHEN: Consumer processes the duplicate
        THEN: Returns DUPLICATE

        Goal: Verify a redelivered update is skipped.
        """
        old_data = availability_data(8813)
        availability_consumer._process_availability_message(created_message(old_data))
        message = updated_message(old_data, availability_data(8813, start_time="16:00:00", end_time="17:00:00"))

        assert availability_consumer._process_availability_message(message) == MessageProcessingResult.SUCCESS
        assert availability_consumer._process_availability_message(message) == MessageProcessingResult.DUPLICATE


# ===== Delete Tests =====

class TestConsumerCentreActivityAvailabilityDelete:
    """Test consumer processing of CENTRE_ACTIVITY_AVAILABILITY_DELETED events"""

    def test_delete_availability_soft_deletes_row(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: An existing availability
        WHEN: Consumer processes a DELETED message
        THEN: The row is kept but marked IsDeleted = "1"

        Goal: Verify deletes are soft deletes, matching the activity service.
        """
        data = availability_data(8821)
        availability_consumer._process_availability_message(created_message(data))
        correlation_id = new_correlation_id()

        result = availability_consumer._process_availability_message(deleted_message(data, correlation_id))

        assert result == MessageProcessingResult.SUCCESS
        ref = get_ref_availability(integration_db, 8821)
        assert ref is not None
        assert ref.IsDeleted == "1"
        assert ref.ModifiedById == "test-user-2"
        assert get_processed_event(integration_db, correlation_id).event_type == "CENTRE_ACTIVITY_AVAILABILITY_DELETED"

    def test_delete_for_missing_row_succeeds(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: A DELETED message for an availability the scheduler does not have
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS without creating anything

        Goal: Verify there is nothing to retry when the row is already absent.
        """
        result = availability_consumer._process_availability_message(deleted_message(availability_data(8822)))

        assert result == MessageProcessingResult.SUCCESS
        assert get_ref_availability(integration_db, 8822) is None


# ===== End-to-end lifecycle =====

class TestCentreActivityAvailabilityLifecycle:
    def test_create_update_delete_sequence(self, integration_db, availability_consumer, setup_test_centre_activity):
        """
        GIVEN: A supervisor creates, edits and then deletes an availability
        WHEN: The three events are processed in order
        THEN: The REF row follows each change and three PROCESSED_EVENTS records exist

        Goal: Verify the reference table stays in step with the activity service across a full lifecycle.
        """
        created = availability_data(8831)
        updated = availability_data(8831, start_time="11:00:00", end_time="12:00:00", modified_by_id="test-user-2")
        correlation_ids = [new_correlation_id() for _ in range(3)]

        assert availability_consumer._process_availability_message(created_message(created, correlation_ids[0])) == MessageProcessingResult.SUCCESS
        assert get_ref_availability(integration_db, 8831).StartTime == time(14, 0)

        assert availability_consumer._process_availability_message(updated_message(created, updated, correlation_ids[1])) == MessageProcessingResult.SUCCESS
        assert get_ref_availability(integration_db, 8831).StartTime == time(11, 0)

        assert availability_consumer._process_availability_message(deleted_message(updated, correlation_ids[2])) == MessageProcessingResult.SUCCESS
        assert get_ref_availability(integration_db, 8831).IsDeleted == "1"

        integration_db.expire_all()
        assert integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id.in_(correlation_ids)
        ).count() == 3
