"""
Integration tests for Scheduler Service Activity Consumer
Tests the flow: RabbitMQ Message → Activity Consumer → REF_ACTIVITY table update → PROCESSED_EVENTS tracking

Run Pytest with command: pytest tests/integration_tests/test_activity_consumer_integration.py -v -s
SQL Commands to clear DB:
DELETE FROM [fyp_dev_bryan_activity_test].[dbo].[REF_ACTIVITY];
DELETE FROM [fyp_dev_bryan_activity_test].[dbo].[PROCESSED_EVENTS];
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict

import pytest
from sqlalchemy.orm import Session

from messaging.activity_consumer import ActivityConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
from pear_schedule.models.ref_activity_model import RefActivity
from pear_schedule.schemas.ref_activity import (
    RefActivityCreate,
    RefActivityDelete,
    RefActivityUpdate,
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


@pytest.fixture
def activity_consumer():
    """
    Fixture for ActivityConsumer instance.
    """
    consumer = ActivityConsumer()
    yield consumer
    # Cleanup
    if consumer.client:
        consumer.client.close()


@pytest.fixture
def mock_activity_data():
    """
    Mock activity data matching the Activity Service schema
    """
    return {
        "id": 1001,
        "title": "Test Activity",
        "description": "Test Description",
        "is_deleted": False,
        "created_by_id": "test-user-1",
        "modified_by_id": "test-user-1",
        "created_date": datetime.now().isoformat(),
        "modified_date": datetime.now().isoformat()
    }
    
@pytest.fixture
def mock_activity_data_for_indempotency_check():
    """
    Mock activity data matching the Activity Service schema
    """
    return {
        "id": 1002,
        "title": "Test Indempotent Activity",
        "description": "Test Indempotent Description",
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
        
        # Delete all ref activities
        integration_db.query(RefActivity).delete()
        integration_db.commit()
        
        print("\n[CLEANUP] Test data cleared successfully")
    except Exception as e:
        integration_db.rollback()
        print(f"\n[CLEANUP] Warning: Failed to cleanup test data: {str(e)}")


# ===== Helper Functions =====

def create_activity_created_message(activity_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_CREATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "ACTIVITY_CREATED",
            "activity_id": activity_data["id"],
            "activity_data": activity_data,
            "created_by": activity_data.get("created_by_id", "test-user"),
            "created_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_activity_updated_message(activity_id: int, old_data: Dict[str, Any], 
                                   new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_UPDATED message"""
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
            "event_type": "ACTIVITY_UPDATED",
            "activity_id": activity_id,
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("modified_by_id", "test-user"),
            "modified_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_activity_deleted_message(activity_id: int, activity_data: Dict[str, Any], 
                                   correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_DELETED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "ACTIVITY_DELETED",
            "activity_id": activity_id,
            "activity_data": activity_data,
            "deleted_by": "test-user",
            "deleted_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


# ===== Create Activity Tests =====

class TestConsumerActivityCreate:
    """Test consumer processing of ACTIVITY_CREATED events"""
    
    def test_create_activity_processes_message_successfully(self, integration_db, activity_consumer, mock_activity_data):
        """
        GIVEN: ACTIVITY_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY record is created and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_CREATED message creates the activity in REF_ACTIVITY table
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_activity_created_message(mock_activity_data, correlation_id)
        
        print(f"\nProcessing ACTIVITY_CREATED message with correlation_id: {correlation_id}")
        
        # Process the message
        result = activity_consumer._process_activity_message(message)
        
        print(f"Processing result: {result}")
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY record created
        ref_activity = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        
        assert ref_activity is not None
        assert ref_activity.ActivityTitle == mock_activity_data["title"]
        assert ref_activity.ActivityDesc == mock_activity_data["description"]
        assert ref_activity.IsDeleted == "0"
        
        print(f"DONE: Created REF_ACTIVITY ID: {ref_activity.ActivityID}")
        print(f"  Title: {ref_activity.ActivityTitle}")
        print(f"  IsDeleted: {ref_activity.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        processed_event_status = json.loads(processed_event.operation_result)["status"]
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_CREATED"
        assert processed_event.aggregate_id == str(mock_activity_data["id"])
        assert processed_event_status == "success"
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
        print(f"  Event Type: {processed_event.event_type}")
        print(f"  Status: {processed_event_status}")
    
    def test_duplicate_create_message_is_idempotent(self, integration_db, activity_consumer, mock_activity_data):
        """
        GIVEN: ACTIVITY_CREATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and no additional records created
        
        Goal: Verify idempotency - duplicate messages don't create duplicate records
        """
        mock_activity_data["id"] = 1002  # Ensure unique ID for this test"
        mock_activity_data["title"] = "Test Indempotent Activity"
        mock_activity_data["description"] = "Test Indempotent Description"
        correlation_id = str(uuid.uuid4()).upper()
        message = create_activity_created_message(mock_activity_data, correlation_id)
        
        print(f"\nProcessing initial ACTIVITY_CREATED message: {correlation_id}")
        
        # Process first time
        result1 = activity_consumer._process_activity_message(message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        initial_activity_count = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).count()
        initial_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        print(f"Initial counts - Activities: {initial_activity_count}, Processed Events: {initial_processed_count}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_CREATED message: {correlation_id}")
        result2 = activity_consumer._process_activity_message(message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify no additional records created
        final_activity_count = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).count()
        final_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        assert final_activity_count == initial_activity_count
        assert final_processed_count == initial_processed_count
        
        print(f"DONE: Duplicate message handled correctly - no new records created")
        print(f"Final counts - Activities: {final_activity_count}, Processed Events: {final_processed_count}")
    
    def test_create_with_invalid_data_fails_permanently(self, integration_db, activity_consumer):
        """
        GIVEN: ACTIVITY_CREATED message with invalid/missing data
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
                "event_type": "ACTIVITY_CREATED",
                # Missing activity_id and activity_data
            }
        }
        
        print(f"\nProcessing invalid ACTIVITY_CREATED message: {correlation_id}")
        
        # Process the message
        result = activity_consumer._process_activity_message(invalid_message)
        
        # Should fail permanently
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        # Verify no records created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Invalid message rejected permanently - no records created")
    
    def test_create_with_mapping_failure_fails_permanently(self, integration_db, activity_consumer, mock_activity_data, monkeypatch):
        """
        GIVEN: ACTIVITY_CREATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)
        
        Goal: Verify that mapping errors are treated as permanent failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_activity_created_message(mock_activity_data, correlation_id)
        
        print(f"\nProcessing CREATE message with mapping error: {correlation_id}")
        
        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(activity_consumer, "map_activity_create", lambda x: None)
        
        # Process the message
        result = activity_consumer._process_activity_message(message)
        
        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")
    
    def test_create_with_database_error_returns_retryable(self, integration_db, activity_consumer, mock_activity_data, monkeypatch):
        """
        GIVEN: ACTIVITY_CREATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_activity_created_message(mock_activity_data, correlation_id)
        
        print(f"\nSimulating database error for CREATE: {correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_create_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(activity_consumer, "create_ref_activity", mock_create_failure)
        
        # Process the message
        result = activity_consumer._process_activity_message(message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Update Activity Tests =====

class TestConsumerActivityUpdate:
    """Test consumer processing of ACTIVITY_UPDATED events"""
    
    def test_update_activity_processes_message_successfully(self, integration_db, activity_consumer, mock_activity_data):
        """
        GIVEN: Existing REF_ACTIVITY record and ACTIVITY_UPDATED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY record is updated and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_UPDATED message updates the activity in REF_ACTIVITY table
        """
        # First create the activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_activity_created_message(mock_activity_data, create_correlation_id)
        activity_consumer._process_activity_message(create_message)
        
        print(f"\nCreated initial activity ID: {mock_activity_data['id']}")
        
        # Clear processed events for clean test
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == create_correlation_id
        ).delete()
        integration_db.commit()
        
        # Update the activity
        updated_data = mock_activity_data.copy()
        updated_data["title"] = "Updated Activity Title"
        updated_data["description"] = "Updated Description"
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_activity_updated_message(
            mock_activity_data["id"],
            mock_activity_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing ACTIVITY_UPDATED message: {update_correlation_id}")
        
        # Process update message
        result = activity_consumer._process_activity_message(update_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY record updated
        ref_activity = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        
        assert ref_activity is not None
        assert ref_activity.ActivityTitle == "Updated Activity Title"
        assert ref_activity.ActivityDesc == "Updated Description"
        assert ref_activity.IsDeleted == "0"
        
        print(f"DONE: Updated REF_ACTIVITY ID: {ref_activity.ActivityID}")
        print(f"  New Title: {ref_activity.ActivityTitle}")
        print(f"  New Description: {ref_activity.ActivityDesc}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_UPDATED"
        assert processed_event.aggregate_id == str(mock_activity_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_update_nonexistent_activity_succeeds_gracefully(self, integration_db, activity_consumer):
        """
        GIVEN: ACTIVITY_UPDATED message for non-existent activity
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that updates for non-existent activities don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "title": "Non-existent",
            "description": "This activity doesn't exist",
            "is_deleted": False,
            "modified_by_id": "test-user",
            "modified_date": datetime.now().isoformat()
        }
        
        update_message = create_activity_updated_message(
            99999,
            non_existent_data,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing UPDATE for non-existent activity 99999")
        
        # Process the message
        result = activity_consumer._process_activity_message(update_message)
        
        # Should succeed gracefully (no crash/retry)
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created (for idempotency tracking)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent activity update handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_update_message_is_idempotent(self, integration_db, activity_consumer, mock_activity_data):
        """
        GIVEN: ACTIVITY_UPDATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and activity not updated again
        
        Goal: Verify idempotency for update messages
        """
        # Create initial activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_activity_created_message(mock_activity_data, create_correlation_id)
        activity_consumer._process_activity_message(create_message)
        
        print(f"\nCreated initial activity ID: {mock_activity_data['id']}")
        
        # Update the activity
        updated_data = mock_activity_data.copy()
        updated_data["title"] = "First Update"
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_activity_updated_message(
            mock_activity_data["id"],
            mock_activity_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing initial ACTIVITY_UPDATED message: {update_correlation_id}")
        
        # Process first time
        result1 = activity_consumer._process_activity_message(update_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Get the updated timestamp
        first_update = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        first_updated_datetime = first_update.UpdatedDateTime
        
        print(f"First update completed at: {first_updated_datetime}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_UPDATED message: {update_correlation_id}")
        result2 = activity_consumer._process_activity_message(update_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify UpdatedDateTime hasn't changed
        second_check = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        
        assert second_check.UpdatedDateTime == first_updated_datetime
        
        print(f"DONE: Duplicate update message handled correctly")
        print(f"Timestamp unchanged: {second_check.UpdatedDateTime}")
    
    def test_update_with_mapping_failure_fails_permanently(self, integration_db, activity_consumer, mock_activity_data, monkeypatch):
        """
        GIVEN: ACTIVITY_UPDATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)
        
        Goal: Verify that mapping errors are treated as permanent failures
        """
        # Create initial activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_activity_created_message(mock_activity_data, create_correlation_id)
        activity_consumer._process_activity_message(create_message)
        
        print(f"\nCreated initial activity ID: {mock_activity_data['id']}")
        
        # Update message
        updated_data = mock_activity_data.copy()
        updated_data["title"] = "Should Fail Mapping"
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_activity_updated_message(
            mock_activity_data["id"],
            mock_activity_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing UPDATE message with mapping error: {update_correlation_id}")
        
        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(activity_consumer, "map_activity_update", lambda x: None)
        
        # Process the message
        result = activity_consumer._process_activity_message(update_message)
        
        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")
    
    def test_update_with_database_error_returns_retryable(self, integration_db, activity_consumer, mock_activity_data, monkeypatch):
        """
        GIVEN: ACTIVITY_UPDATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_activity_created_message(mock_activity_data, create_correlation_id)
        activity_consumer._process_activity_message(create_message)
        
        print(f"\nCreated initial activity ID: {mock_activity_data['id']}")
        
        # Update message
        updated_data = mock_activity_data.copy()
        updated_data["title"] = "Should Trigger DB Error"
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_activity_updated_message(
            mock_activity_data["id"],
            mock_activity_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Simulating database error for UPDATE: {update_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_update_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(activity_consumer, "update_ref_activity", mock_update_failure)
        
        # Process the message
        result = activity_consumer._process_activity_message(update_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Delete Activity Tests =====

class TestConsumerActivityDelete:
    """Test consumer processing of ACTIVITY_DELETED events"""
    
    def test_delete_activity_processes_message_successfully(self, integration_db, activity_consumer, mock_activity_data):
        """
        GIVEN: Existing REF_ACTIVITY record and ACTIVITY_DELETED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY record is soft-deleted and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_DELETED message soft-deletes the activity
        """
        # First create the activity
        create_correlation_id = str(uuid.uuid4()).upper()
        mock_activity_data["id"] = 1003  # Ensure unique ID for this test"
        mock_activity_data["is_deleted"] = False
        mock_activity_data["title"] = "Activity to be Deleted"
        mock_activity_data["description"] = "This activity will be deleted in the test"
        create_message = create_activity_created_message(mock_activity_data, create_correlation_id)
        activity_consumer._process_activity_message(create_message)
        
        print(f"\nCreated initial activity ID: {mock_activity_data['id']}")
        
        # Verify activity exists and is not deleted
        activity_before = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        assert activity_before.IsDeleted == "0"
        print(f"Activity before delete - IsDeleted: {activity_before.IsDeleted}")
        
        # Delete the activity
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_activity_deleted_message(
            mock_activity_data["id"],
            mock_activity_data,
            delete_correlation_id
        )
        
        print(f"Processing ACTIVITY_DELETED message: {delete_correlation_id}")
        
        # Process delete message
        result = activity_consumer._process_activity_message(delete_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        
        # Verify REF_ACTIVITY record soft-deleted
        ref_activity = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        
        integration_db.refresh(ref_activity)
        
        assert ref_activity is not None
        assert ref_activity.IsDeleted == "1"
        
        print(f"DONE: Soft-deleted REF_ACTIVITY ID: {ref_activity.ActivityID}")
        print(f"  IsDeleted: {ref_activity.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_DELETED"
        assert processed_event.aggregate_id == str(mock_activity_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_delete_nonexistent_activity_succeeds_gracefully(self, integration_db, activity_consumer):
        """
        GIVEN: ACTIVITY_DELETED message for non-existent activity
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that deletes for non-existent activities don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "title": "Non-existent",
            "description": "This activity doesn't exist",
            "is_deleted": False
        }
        
        delete_message = create_activity_deleted_message(
            99999,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing DELETE for non-existent activity 99999")
        
        # Process the message
        result = activity_consumer._process_activity_message(delete_message)
        
        # Should succeed gracefully
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent activity deletion handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_delete_message_is_idempotent(self, integration_db, activity_consumer, mock_activity_data):
        """
        GIVEN: ACTIVITY_DELETED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and activity stays deleted
        
        Goal: Verify idempotency for delete messages
        """
        # Create initial activity
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_activity_created_message(mock_activity_data, create_correlation_id)
        activity_consumer._process_activity_message(create_message)
        
        print(f"\nCreated initial activity ID: {mock_activity_data['id']}")
        
        # Delete the activity
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_activity_deleted_message(
            mock_activity_data["id"],
            mock_activity_data,
            delete_correlation_id
        )
        
        print(f"Processing initial ACTIVITY_DELETED message: {delete_correlation_id}")
        
        # Process first time
        result1 = activity_consumer._process_activity_message(delete_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Verify deleted
        deleted_activity = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        assert deleted_activity.IsDeleted == "1"
        
        print(f"Activity soft-deleted: IsDeleted = {deleted_activity.IsDeleted}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_DELETED message: {delete_correlation_id}")
        result2 = activity_consumer._process_activity_message(delete_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify still deleted
        still_deleted = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        assert still_deleted.IsDeleted == "1"
        
        print(f"DONE: Duplicate delete message handled correctly")
        print(f"Activity remains deleted: IsDeleted = {still_deleted.IsDeleted}")
    
    def test_delete_with_database_error_returns_retryable(self, integration_db, activity_consumer, mock_activity_data, monkeypatch):
        """
        GIVEN: ACTIVITY_DELETED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial activity
        mock_activity_data["id"] = 1005  # Ensure unique ID for this test"
        mock_activity_data["is_deleted"] = False
        mock_activity_data["title"] = "Activity to be Deleted"
        mock_activity_data["description"] = "This activity will be deleted in the test"
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_activity_created_message(mock_activity_data, create_correlation_id)
        activity_consumer._process_activity_message(create_message)
        
        print(f"\nCreated initial activity ID: {mock_activity_data['id']}")
        
        # Delete message
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_activity_deleted_message(
            mock_activity_data["id"],
            mock_activity_data,
            delete_correlation_id
        )
        
        print(f"Simulating database error for DELETE: {delete_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_delete_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(activity_consumer, "delete_ref_activity", mock_delete_failure)
        
        # Process the message
        result = activity_consumer._process_activity_message(delete_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is None
        
        # Verify activity was NOT deleted (operation failed before completion)
        activity_check = integration_db.query(RefActivity).filter(
            RefActivity.ActivityID == mock_activity_data["id"]
        ).first()
        assert activity_check.IsDeleted == "0"
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")
        print(f"Activity remains active (IsDeleted=0) - will be deleted on retry")