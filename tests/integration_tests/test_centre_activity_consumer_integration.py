"""
Integration tests for Scheduler Service Centre Activity Consumer
Tests the flow: RabbitMQ Message → Centre Activity Consumer → REF_CENTRE_ACTIVITY table update → PROCESSED_EVENTS tracking
"""

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict

import pytest
from sqlalchemy.orm import Session

from messaging.centre_activity_consumer import CentreActivityConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
from pear_schedule.models.ref_activity_model import RefActivity
from pear_schedule.models.ref_centre_activity_model import RefCentreActivity
from pear_schedule.schemas.ref_centre_activity import (
    RefCentreActivityCreate,
    RefCentreActivityDelete,
    RefCentreActivityUpdate,
)

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
def setup_test_data(integration_db):
    """
    Create test activities required for foreign key constraints.
    """
    # ===== CREATE TEST ACTIVITIES =====
    existing_act_1 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 1).first()
    existing_act_2 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 2).first()
    existing_act_3 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 3).first()
    
    activities_created = []
    
    if not existing_act_1:
        activity_1 = RefActivity(
            ActivityID=1,
            ActivityTitle="Test Activity 1",
            ActivityDesc="Test activity for centre activities",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(activity_1)
        activities_created.append(1)
    
    if not existing_act_2:
        activity_2 = RefActivity(
            ActivityID=2,
            ActivityTitle="Test Activity 2",
            ActivityDesc="Test activity for centre activities",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(activity_2)
        activities_created.append(2)
    
    if not existing_act_3:
        activity_3 = RefActivity(
            ActivityID=3,
            ActivityTitle="Test Activity 3",
            ActivityDesc="Test activity for centre activities",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(activity_3)
        activities_created.append(3)
    
    integration_db.commit()
    
    if activities_created:
        print(f"\n[SETUP] Created test activities: {activities_created}")
    else:
        print(f"\n[SETUP] Test activities already exist: [1, 2, 3]")
    
    yield


@pytest.fixture
def centre_activity_consumer():
    """
    Fixture for CentreActivityConsumer instance.
    """
    consumer = CentreActivityConsumer()
    yield consumer
    # Cleanup
    if consumer.client:
        consumer.client.close()


@pytest.fixture
def mock_centre_activity_data():
    """
    Mock centre activity data matching the Activity Service schema
    """
    return {
        "id": 5001,
        "activity_id": 1,
        "is_compulsory": True,
        "is_fixed": False,
        "is_group": True,
        "start_date": date.today().isoformat(),
        "end_date": (date.today() + timedelta(days=30)).isoformat(),
        "min_duration": 30,
        "max_duration": 60,
        "min_people_req": 2,
        "fixed_time_slots": "09:00-10:00,14:00-15:00",
        "is_deleted": False,
        "created_by_id": "test-user-1",
        "modified_by_id": "test-user-1",
        "created_date": datetime.now().isoformat(),
        "modified_date": datetime.now().isoformat()
    }


@pytest.fixture
def mock_centre_activity_data_for_idempotency_check():
    """
    Mock centre activity data for idempotency tests
    """
    return {
        "id": 5002,
        "activity_id": 2,
        "is_compulsory": False,
        "is_fixed": True,
        "is_group": False,
        "start_date": date.today().isoformat(),
        "end_date": (date.today() + timedelta(days=60)).isoformat(),
        "min_duration": 45,
        "max_duration": 90,
        "min_people_req": 1,
        "fixed_time_slots": "10:00-11:00",
        "is_deleted": False,
        "created_by_id": "test-user-1",
        "modified_by_id": "test-user-1",
        "created_date": datetime.now().isoformat(),
        "modified_date": datetime.now().isoformat()
    }


# Uncomment this when you are testing to ensure clean state.
# NOTE (IMPORTANT): This will delete ALL records in the tables after each test function, so make sure you point to the testing DB, and not PROD!
@pytest.fixture(autouse=True)
def cleanup_test_data(integration_db):
    """
    Cleanup fixture that runs after each test.
    Deletes all test data created during the test.
    """
    # This runs BEFORE the test
    yield
    
    # This runs AFTER the test - cleanup
    try:
        # Delete all processed events first
        integration_db.query(ProcessedEvent).delete()
        integration_db.commit()
        
        # Delete all ref centre activities
        integration_db.query(RefCentreActivity).delete()
        integration_db.commit()
        
        print("\n[CLEANUP] Test data cleared successfully")
    except Exception as e:
        integration_db.rollback()
        print(f"\n[CLEANUP] Warning: Failed to cleanup test data: {str(e)}")


# ===== Helper Functions =====

def create_centre_activity_created_message(centre_activity_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create CENTRE_ACTIVITY_CREATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "CENTRE_ACTIVITY_CREATED",
            "centre_activity_id": centre_activity_data["id"],
            "centre_activity_data": centre_activity_data,
            "created_by": centre_activity_data.get("created_by_id", "test-user"),
            "created_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_centre_activity_updated_message(centre_activity_id: int, old_data: Dict[str, Any], 
                                          new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create CENTRE_ACTIVITY_UPDATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    changes = {}
    for key in new_data:
        if key in old_data and old_data[key] != new_data[key]:
            changes[key] = {"old": old_data[key], "new": new_data[key]}
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "CENTRE_ACTIVITY_UPDATED",
            "centre_activity_id": centre_activity_id,
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("modified_by_id", "test-user"),
            "modified_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_centre_activity_deleted_message(centre_activity_id: int, centre_activity_data: Dict[str, Any], 
                                          correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create CENTRE_ACTIVITY_DELETED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "CENTRE_ACTIVITY_DELETED",
            "centre_activity_id": centre_activity_id,
            "centre_activity_data": centre_activity_data,
            "deleted_by": "test-user",
            "deleted_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


# ===== Create Centre Activity Tests =====

class TestConsumerCentreActivityCreate:
    """Test consumer processing of CENTRE_ACTIVITY_CREATED events"""
    
    def test_create_centre_activity_processes_message_successfully(self, integration_db, centre_activity_consumer, mock_centre_activity_data, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_CENTRE_ACTIVITY record is created and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming a CENTRE_ACTIVITY_CREATED message creates the centre activity in REF_CENTRE_ACTIVITY table
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_centre_activity_created_message(mock_centre_activity_data, correlation_id)
        
        print(f"\nProcessing CENTRE_ACTIVITY_CREATED message with correlation_id: {correlation_id}")
        
        # Process the message
        result = centre_activity_consumer._process_centre_activity_message(message)
        
        print(f"Processing result: {result}")
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_CENTRE_ACTIVITY record created
        ref_centre_activity = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        
        assert ref_centre_activity is not None
        assert ref_centre_activity.ActivityID == mock_centre_activity_data["activity_id"]
        assert ref_centre_activity.IsCompulsory == "1"  # True -> "1"
        assert ref_centre_activity.IsFixed == "0"  # False -> "0"
        assert ref_centre_activity.IsGroup == "1"  # True -> "1"
        assert ref_centre_activity.MinDuration == mock_centre_activity_data["min_duration"]
        assert ref_centre_activity.MaxDuration == mock_centre_activity_data["max_duration"]
        assert ref_centre_activity.MinPeopleReq == mock_centre_activity_data["min_people_req"]
        assert ref_centre_activity.IsDeleted == "0"
        
        print(f"DONE: Created REF_CENTRE_ACTIVITY ID: {ref_centre_activity.CentreActivityID}")
        print(f"  ActivityID: {ref_centre_activity.ActivityID}")
        print(f"  IsCompulsory: {ref_centre_activity.IsCompulsory}")
        print(f"  IsGroup: {ref_centre_activity.IsGroup}")
        print(f"  IsDeleted: {ref_centre_activity.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        processed_event_status = json.loads(processed_event.operation_result)["status"]
        
        assert processed_event is not None
        assert processed_event.event_type == "CENTRE_ACTIVITY_CREATED"
        assert processed_event.aggregate_id == str(mock_centre_activity_data["id"])
        assert processed_event_status == "success"
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
        print(f"  Event Type: {processed_event.event_type}")
        print(f"  Status: {processed_event_status}")
    
    def test_duplicate_create_message_is_idempotent(self, integration_db, centre_activity_consumer, mock_centre_activity_data_for_idempotency_check, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_CREATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and no additional records created
        
        Goal: Verify idempotency - duplicate messages don't create duplicate records
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_centre_activity_created_message(mock_centre_activity_data_for_idempotency_check, correlation_id)
        
        print(f"\nProcessing initial CENTRE_ACTIVITY_CREATED message: {correlation_id}")
        
        # Process first time
        result1 = centre_activity_consumer._process_centre_activity_message(message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        initial_centre_activity_count = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data_for_idempotency_check["id"]
        ).count()
        initial_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        print(f"Initial counts - Centre Activities: {initial_centre_activity_count}, Processed Events: {initial_processed_count}")
        
        # Process duplicate message
        print(f"Processing duplicate CENTRE_ACTIVITY_CREATED message: {correlation_id}")
        result2 = centre_activity_consumer._process_centre_activity_message(message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify no additional records created
        final_centre_activity_count = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data_for_idempotency_check["id"]
        ).count()
        final_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        assert final_centre_activity_count == initial_centre_activity_count
        assert final_processed_count == initial_processed_count
        
        print(f"DONE: Duplicate message handled correctly - no new records created")
        print(f"Final counts - Centre Activities: {final_centre_activity_count}, Processed Events: {final_processed_count}")
    
    def test_create_with_invalid_data_fails_permanently(self, integration_db, centre_activity_consumer, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_CREATED message with invalid/missing data
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT and no records created
        
        Goal: Verify that invalid messages are rejected permanently
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        # Create message with missing required fields
        invalid_message = {
            "timestamp": datetime.now().isoformat(),
            "source_service": "activity-service",
            "data": {
                "correlation_id": correlation_id,
                "event_type": "CENTRE_ACTIVITY_CREATED",
                # Missing centre_activity_id and centre_activity_data
            }
        }
        
        print(f"\nProcessing invalid CENTRE_ACTIVITY_CREATED message: {correlation_id}")
        
        # Process the message
        result = centre_activity_consumer._process_centre_activity_message(invalid_message)
        
        # Should fail permanently
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        # Verify no records created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Invalid message rejected permanently - no records created")
    
    def test_create_with_mapping_failure_fails_permanently(self, integration_db, centre_activity_consumer, mock_centre_activity_data, monkeypatch, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_CREATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)
        
        Goal: Verify that mapping errors are treated as permanent failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_centre_activity_created_message(mock_centre_activity_data, correlation_id)
        
        print(f"\nProcessing CREATE message with mapping error: {correlation_id}")
        
        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(centre_activity_consumer, "map_centre_activity_create", lambda x: None)
        
        # Process the message
        result = centre_activity_consumer._process_centre_activity_message(message)
        
        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")
    
    def test_create_with_database_error_returns_retryable(self, integration_db, centre_activity_consumer, mock_centre_activity_data, monkeypatch, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_CREATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_centre_activity_created_message(mock_centre_activity_data, correlation_id)
        
        print(f"\nSimulating database error for CREATE: {correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_create_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(centre_activity_consumer, "create_ref_centre_activity", mock_create_failure)
        
        # Process the message
        result = centre_activity_consumer._process_centre_activity_message(message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Update Centre Activity Tests =====

class TestConsumerCentreActivityUpdate:
    """Test consumer processing of CENTRE_ACTIVITY_UPDATED events"""
    
    def test_update_centre_activity_processes_message_successfully(self, integration_db, centre_activity_consumer, mock_centre_activity_data, setup_test_data):
        """
        GIVEN: Existing REF_CENTRE_ACTIVITY record and CENTRE_ACTIVITY_UPDATED message
        WHEN: Consumer processes the message
        THEN: REF_CENTRE_ACTIVITY record is updated and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming a CENTRE_ACTIVITY_UPDATED message updates the centre activity in REF_CENTRE_ACTIVITY table
        """
        # First create the centre activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_centre_activity_created_message(mock_centre_activity_data, create_correlation_id)
        centre_activity_consumer._process_centre_activity_message(create_message)
        
        print(f"\nCreated initial centre activity ID: {mock_centre_activity_data['id']}")
        
        # Clear processed events for clean test
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == create_correlation_id
        ).delete()
        integration_db.commit()
        
        # Update the centre activity
        updated_data = mock_centre_activity_data.copy()
        updated_data["activity_id"] = 3
        updated_data["min_duration"] = 45
        updated_data["max_duration"] = 90
        updated_data["is_compulsory"] = False
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_centre_activity_updated_message(
            mock_centre_activity_data["id"],
            mock_centre_activity_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing CENTRE_ACTIVITY_UPDATED message: {update_correlation_id}")
        
        # Process update message
        result = centre_activity_consumer._process_centre_activity_message(update_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_CENTRE_ACTIVITY record updated
        ref_centre_activity = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        
        assert ref_centre_activity is not None
        assert ref_centre_activity.ActivityID == 3
        assert ref_centre_activity.MinDuration == 45
        assert ref_centre_activity.MaxDuration == 90
        assert ref_centre_activity.IsCompulsory == "0"  # False -> "0"
        assert ref_centre_activity.IsDeleted == "0"
        
        print(f"DONE: Updated REF_CENTRE_ACTIVITY ID: {ref_centre_activity.CentreActivityID}")
        print(f"  New ActivityID: {ref_centre_activity.ActivityID}")
        print(f"  New MinDuration: {ref_centre_activity.MinDuration}")
        print(f"  New IsCompulsory: {ref_centre_activity.IsCompulsory}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "CENTRE_ACTIVITY_UPDATED"
        assert processed_event.aggregate_id == str(mock_centre_activity_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_update_nonexistent_centre_activity_succeeds_gracefully(self, integration_db, centre_activity_consumer, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_UPDATED message for non-existent centre activity
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that updates for non-existent centre activities don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "activity_id": 1,
            "is_compulsory": False,
            "is_fixed": False,
            "is_group": False,
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=30)).isoformat(),
            "min_duration": 30,
            "max_duration": 60,
            "min_people_req": 1,
            "fixed_time_slots": "",
            "is_deleted": False,
            "modified_by_id": "test-user",
            "modified_date": datetime.now().isoformat()
        }
        
        update_message = create_centre_activity_updated_message(
            99999,
            non_existent_data,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing UPDATE for non-existent centre activity 99999")
        
        # Process the message
        result = centre_activity_consumer._process_centre_activity_message(update_message)
        
        # Should succeed gracefully (no crash/retry)
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created (for idempotency tracking)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent centre activity update handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_update_message_is_idempotent(self, integration_db, centre_activity_consumer, mock_centre_activity_data, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_UPDATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and centre activity not updated again
        
        Goal: Verify idempotency for update messages
        """
        # Create initial centre activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_centre_activity_created_message(mock_centre_activity_data, create_correlation_id)
        centre_activity_consumer._process_centre_activity_message(create_message)
        
        print(f"\nCreated initial centre activity ID: {mock_centre_activity_data['id']}")
        
        # Update the centre activity
        updated_data = mock_centre_activity_data.copy()
        updated_data["activity_id"] = 3
        updated_data["min_duration"] = 50
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_centre_activity_updated_message(
            mock_centre_activity_data["id"],
            mock_centre_activity_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing initial CENTRE_ACTIVITY_UPDATED message: {update_correlation_id}")
        
        # Process first time
        result1 = centre_activity_consumer._process_centre_activity_message(update_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Get the updated timestamp
        first_update = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        first_updated_datetime = first_update.UpdatedDateTime
        
        print(f"First update completed at: {first_updated_datetime}")
        
        # Process duplicate message
        print(f"Processing duplicate CENTRE_ACTIVITY_UPDATED message: {update_correlation_id}")
        result2 = centre_activity_consumer._process_centre_activity_message(update_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify UpdatedDateTime hasn't changed
        second_check = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        
        assert second_check.UpdatedDateTime == first_updated_datetime
        
        print(f"DONE: Duplicate update message handled correctly")
        print(f"Timestamp unchanged: {second_check.UpdatedDateTime}")
    
    def test_update_with_database_error_returns_retryable(self, integration_db, centre_activity_consumer, mock_centre_activity_data, monkeypatch, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_UPDATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial centre activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_centre_activity_created_message(mock_centre_activity_data, create_correlation_id)
        centre_activity_consumer._process_centre_activity_message(create_message)
        
        print(f"\nCreated initial centre activity ID: {mock_centre_activity_data['id']}")
        
        # Update message
        updated_data = mock_centre_activity_data.copy()
        updated_data["activity_id"] = 3
        updated_data["min_duration"] = 40
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_centre_activity_updated_message(
            mock_centre_activity_data["id"],
            mock_centre_activity_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Simulating database error for UPDATE: {update_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_update_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(centre_activity_consumer, "update_ref_centre_activity", mock_update_failure)
        
        # Process the message
        result = centre_activity_consumer._process_centre_activity_message(update_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Delete Centre Activity Tests =====

class TestConsumerCentreActivityDelete:
    """Test consumer processing of CENTRE_ACTIVITY_DELETED events"""
    
    def test_delete_centre_activity_processes_message_successfully(self, integration_db, centre_activity_consumer, mock_centre_activity_data, setup_test_data):
        """
        GIVEN: Existing REF_CENTRE_ACTIVITY record and CENTRE_ACTIVITY_DELETED message
        WHEN: Consumer processes the message
        THEN: REF_CENTRE_ACTIVITY record is soft-deleted and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming a CENTRE_ACTIVITY_DELETED message soft-deletes the centre activity
        """
        # First create the centre activity
        create_correlation_id = str(uuid.uuid4()).upper()
        mock_centre_activity_data["id"] = 5003
        mock_centre_activity_data["is_deleted"] = False
        create_message = create_centre_activity_created_message(mock_centre_activity_data, create_correlation_id)
        centre_activity_consumer._process_centre_activity_message(create_message)
        
        print(f"\nCreated initial centre activity ID: {mock_centre_activity_data['id']}")
        
        # Verify centre activity exists and is not deleted
        centre_activity_before = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        assert centre_activity_before.IsDeleted == "0"
        print(f"Centre activity before delete - IsDeleted: {centre_activity_before.IsDeleted}")
        
        # Delete the centre activity
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_centre_activity_deleted_message(
            mock_centre_activity_data["id"],
            mock_centre_activity_data,
            delete_correlation_id
        )
        
        print(f"Processing CENTRE_ACTIVITY_DELETED message: {delete_correlation_id}")
        
        # Process delete message
        result = centre_activity_consumer._process_centre_activity_message(delete_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_CENTRE_ACTIVITY record soft-deleted
        ref_centre_activity = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        
        integration_db.refresh(ref_centre_activity)
        
        assert ref_centre_activity is not None
        assert ref_centre_activity.IsDeleted == "1"
        
        print(f"DONE: Soft-deleted REF_CENTRE_ACTIVITY ID: {ref_centre_activity.CentreActivityID}")
        print(f"  IsDeleted: {ref_centre_activity.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "CENTRE_ACTIVITY_DELETED"
        assert processed_event.aggregate_id == str(mock_centre_activity_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_delete_nonexistent_centre_activity_succeeds_gracefully(self, integration_db, centre_activity_consumer, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_DELETED message for non-existent centre activity
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that deletes for non-existent centre activities don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "activity_id": 1,
            "is_compulsory": False,
            "is_fixed": False,
            "is_group": False,
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=30)).isoformat(),
            "min_duration": 30,
            "max_duration": 60,
            "min_people_req": 1,
            "fixed_time_slots": "",
            "is_deleted": False
        }
        
        delete_message = create_centre_activity_deleted_message(
            99999,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing DELETE for non-existent centre activity 99999")
        
        # Process the message
        result = centre_activity_consumer._process_centre_activity_message(delete_message)
        
        # Should succeed gracefully
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent centre activity deletion handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_delete_message_is_idempotent(self, integration_db, centre_activity_consumer, mock_centre_activity_data, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_DELETED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and centre activity stays deleted
        
        Goal: Verify idempotency for delete messages
        """
        # Create initial centre activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_centre_activity_created_message(mock_centre_activity_data, create_correlation_id)
        centre_activity_consumer._process_centre_activity_message(create_message)
        
        print(f"\nCreated initial centre activity ID: {mock_centre_activity_data['id']}")
        
        # Delete the centre activity
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_centre_activity_deleted_message(
            mock_centre_activity_data["id"],
            mock_centre_activity_data,
            delete_correlation_id
        )
        
        print(f"Processing initial CENTRE_ACTIVITY_DELETED message: {delete_correlation_id}")
        
        # Process first time
        result1 = centre_activity_consumer._process_centre_activity_message(delete_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Verify deleted
        deleted_centre_activity = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        assert deleted_centre_activity.IsDeleted == "1"
        
        print(f"Centre activity soft-deleted: IsDeleted = {deleted_centre_activity.IsDeleted}")
        
        # Process duplicate message
        print(f"Processing duplicate CENTRE_ACTIVITY_DELETED message: {delete_correlation_id}")
        result2 = centre_activity_consumer._process_centre_activity_message(delete_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify still deleted
        still_deleted = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        assert still_deleted.IsDeleted == "1"
        
        print(f"DONE: Duplicate delete message handled correctly")
        print(f"Centre activity remains deleted: IsDeleted = {still_deleted.IsDeleted}")
    
    def test_delete_with_database_error_returns_retryable(self, integration_db, centre_activity_consumer, mock_centre_activity_data, monkeypatch, setup_test_data):
        """
        GIVEN: CENTRE_ACTIVITY_DELETED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial centre activity
        mock_centre_activity_data["id"] = 5005
        mock_centre_activity_data["is_deleted"] = False
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_centre_activity_created_message(mock_centre_activity_data, create_correlation_id)
        centre_activity_consumer._process_centre_activity_message(create_message)
        
        print(f"\nCreated initial centre activity ID: {mock_centre_activity_data['id']}")
        
        # Delete message
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_centre_activity_deleted_message(
            mock_centre_activity_data["id"],
            mock_centre_activity_data,
            delete_correlation_id
        )
        
        print(f"Simulating database error for DELETE: {delete_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_delete_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(centre_activity_consumer, "delete_ref_centre_activity", mock_delete_failure)
        
        # Process the message
        result = centre_activity_consumer._process_centre_activity_message(delete_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is None
        
        # Verify centre activity was NOT deleted (operation failed before completion)
        centre_activity_check = integration_db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == mock_centre_activity_data["id"]
        ).first()
        assert centre_activity_check.IsDeleted == "0"
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")
        print(f"Centre activity remains active (IsDeleted=0) - will be deleted on retry")