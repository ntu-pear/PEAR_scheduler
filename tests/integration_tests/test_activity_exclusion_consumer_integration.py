"""
Integration tests for Scheduler Service Activity Exclusion Consumer
Tests the flow: RabbitMQ Message → Activity Exclusion Consumer → REF_ACTIVITY_EXCLUSION table update → PROCESSED_EVENTS tracking
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict

import pytest
from sqlalchemy.orm import Session

from messaging.activity_exclusion_consumer import ActivityExclusionConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
from pear_schedule.models.ref_activity_exclusion_model import RefActivityExclusion
from pear_schedule.models.ref_activity_model import RefActivity

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

''' 
Activity Exclusions Setup Fixture:
As activity exclusions depend on existing activities and patients (foreign keys), we need to ensure those exist before running tests.
Hence, we need a setup fixture that creates test activities and patients if they don't already exist.
'''
@pytest.fixture(scope="function")
def setup_test_activities(integration_db):
    """
    Create test activities and patients in database that are required for foreign key constraints.
    These must exist before we can create activity exclusions.
    """
    from pear_schedule.models.ref_patient_model import RefPatient

    # ===== CREATE TEST PATIENTS =====
    existing_patient_1 = integration_db.query(RefPatient).filter(RefPatient.PatientID == 1).first()
    existing_patient_2 = integration_db.query(RefPatient).filter(RefPatient.PatientID == 2).first()
    
    patients_created = []
    
    if not existing_patient_1:
        patient_1 = RefPatient(
            PatientID=1,
            Name="Name",
            PreferredName="Patient 1",
            IsDeleted="0",
            StartDate=datetime.now(),
            EndDate=datetime.now(),
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(patient_1)
        patients_created.append(1)
    
    if not existing_patient_2:
        patient_2 = RefPatient(
            PatientID=2,
            Name="Test",
            PreferredName="Patient 2",
            IsDeleted="0",
            StartDate=datetime.now(),
            EndDate=datetime.now(),
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(patient_2)
        patients_created.append(2)
    
    # ===== CREATE TEST ACTIVITIES =====
    existing_101 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 101).first()
    existing_102 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 102).first()
    existing_999 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 999).first()
    
    activities_created = []
    
    if not existing_101:
        activity_101 = RefActivity(
            ActivityID=101,
            ActivityTitle="Test Activity 101",
            ActivityDesc="Test activity for integration tests",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(activity_101)
        activities_created.append(101)
    
    if not existing_102:
        activity_102 = RefActivity(
            ActivityID=102,
            ActivityTitle="Test Activity 102",
            ActivityDesc="Test activity for integration tests",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(activity_102)
        activities_created.append(102)
    
    if not existing_999:
        activity_999 = RefActivity(
            ActivityID=999,
            ActivityTitle="Test Activity 999",
            ActivityDesc="Test activity for integration tests",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(activity_999)
        activities_created.append(999)
    
    integration_db.commit()
    
    if patients_created:
        print(f"\n[SETUP] Created test patients: {patients_created}")
    if activities_created:
        print(f"\n[SETUP] Created test activities: {activities_created}")
    if not patients_created and not activities_created:
        print(f"\n[SETUP] Test patients [1, 2] and activities [101, 102, 999] already exist")
    
    yield
    
    # Optional cleanup - uncomment if you want to delete test data after tests
    # print(f"\n[CLEANUP] Cleaning up test patients and activities")
    # integration_db.query(RefPatient).filter(RefPatient.PatientID.in_([1, 2])).delete()
    # integration_db.query(RefActivity).filter(RefActivity.ActivityID.in_([101, 102, 999])).delete()
    # integration_db.commit()


@pytest.fixture
def exclusion_consumer():
    """
    Fixture for ActivityExclusionConsumer instance.
    """
    consumer = ActivityExclusionConsumer()
    yield consumer
    # Cleanup
    if consumer.client:
        consumer.client.close()


@pytest.fixture
def mock_exclusion_data():
    """
    Mock activity exclusion data matching the Activity Service schema
    """
    return {
        "id": 2001,
        "patient_id": 1,  
        "centre_activity_id": 101,
        "is_deleted": False,
        "created_by_id": "test-user-1",
        "modified_by_id": "test-user-1",
        "created_date": datetime.now().isoformat(),
        "modified_date": datetime.now().isoformat()
    }


@pytest.fixture
def mock_exclusion_data_for_idempotency_check():
    """
    Mock activity exclusion data for idempotency tests
    """
    return {
        "id": 2002,
        "patient_id": 2,
        "centre_activity_id": 102,
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
        
        # Delete all ref activity exclusions
        integration_db.query(RefActivityExclusion).delete()
        integration_db.commit()
        
        print("\n[CLEANUP] Test data cleared successfully")
    except Exception as e:
        integration_db.rollback()
        print(f"\n[CLEANUP] Warning: Failed to cleanup test data: {str(e)}")


# ===== Helper Functions =====

def create_exclusion_created_message(exclusion_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_EXCLUSION_CREATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "ACTIVITY_EXCLUSION_CREATED",
            "exclusion_id": exclusion_data["id"],
            "exclusion_data": exclusion_data,
            "created_by": exclusion_data.get("created_by_id", "test-user"),
            "created_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_exclusion_updated_message(exclusion_id: int, old_data: Dict[str, Any], 
                                     new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_EXCLUSION_UPDATED message"""
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
            "event_type": "ACTIVITY_EXCLUSION_UPDATED",
            "exclusion_id": exclusion_id,
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("modified_by_id", "test-user"),
            "modified_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_exclusion_deleted_message(exclusion_id: int, exclusion_data: Dict[str, Any], 
                                     correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_EXCLUSION_DELETED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "ACTIVITY_EXCLUSION_DELETED",
            "exclusion_id": exclusion_id,
            "exclusion_data": exclusion_data,
            "deleted_by": "test-user",
            "deleted_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


# ===== Create Activity Exclusion Tests =====

class TestConsumerActivityExclusionCreate:
    """Test consumer processing of ACTIVITY_EXCLUSION_CREATED events"""
    
    def test_create_exclusion_processes_message_successfully(self, integration_db, exclusion_consumer, mock_exclusion_data, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_EXCLUSION record is created and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_EXCLUSION_CREATED message creates the exclusion in REF_ACTIVITY_EXCLUSION table
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_exclusion_created_message(mock_exclusion_data, correlation_id)
        
        print(f"\nProcessing ACTIVITY_EXCLUSION_CREATED message with correlation_id: {correlation_id}")
        
        # Process the message
        result = exclusion_consumer._process_activity_exclusion_message(message)
        
        print(f"Processing result: {result}")
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_EXCLUSION record created
        ref_exclusion = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        
        assert ref_exclusion is not None
        assert ref_exclusion.PatientID == mock_exclusion_data["patient_id"]
        assert ref_exclusion.ActivityID == mock_exclusion_data["centre_activity_id"]
        assert ref_exclusion.IsDeleted == "0"
        
        print(f"DONE: Created REF_ACTIVITY_EXCLUSION ID: {ref_exclusion.ActivityExclusionID}")
        print(f"  PatientID: {ref_exclusion.PatientID}")
        print(f"  ActivityID: {ref_exclusion.ActivityID}")
        print(f"  IsDeleted: {ref_exclusion.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        processed_event_status = json.loads(processed_event.operation_result)["status"]
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_EXCLUSION_CREATED"
        assert processed_event.aggregate_id == str(mock_exclusion_data["id"])
        assert processed_event_status == "success"
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
        print(f"  Event Type: {processed_event.event_type}")
        print(f"  Status: {processed_event_status}")
    
    def test_duplicate_create_message_is_idempotent(self, integration_db, exclusion_consumer, mock_exclusion_data_for_idempotency_check, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_CREATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and no additional records created
        
        Goal: Verify idempotency - duplicate messages don't create duplicate records
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_exclusion_created_message(mock_exclusion_data_for_idempotency_check, correlation_id)
        
        print(f"\nProcessing initial ACTIVITY_EXCLUSION_CREATED message: {correlation_id}")
        
        # Process first time
        result1 = exclusion_consumer._process_activity_exclusion_message(message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        initial_exclusion_count = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data_for_idempotency_check["id"]
        ).count()
        initial_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        print(f"Initial counts - Exclusions: {initial_exclusion_count}, Processed Events: {initial_processed_count}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_EXCLUSION_CREATED message: {correlation_id}")
        result2 = exclusion_consumer._process_activity_exclusion_message(message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify no additional records created
        final_exclusion_count = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data_for_idempotency_check["id"]
        ).count()
        final_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        assert final_exclusion_count == initial_exclusion_count
        assert final_processed_count == initial_processed_count
        
        print(f"DONE: Duplicate message handled correctly - no new records created")
        print(f"Final counts - Exclusions: {final_exclusion_count}, Processed Events: {final_processed_count}")
    
    def test_create_with_invalid_data_fails_permanently(self, integration_db, exclusion_consumer, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_CREATED message with invalid/missing data
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
                "event_type": "ACTIVITY_EXCLUSION_CREATED",
                # Missing exclusion_id and exclusion_data
            }
        }
        
        print(f"\nProcessing invalid ACTIVITY_EXCLUSION_CREATED message: {correlation_id}")
        
        # Process the message
        result = exclusion_consumer._process_activity_exclusion_message(invalid_message)
        
        # Should fail permanently
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        # Verify no records created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Invalid message rejected permanently - no records created")
    
    def test_create_with_mapping_failure_fails_permanently(self, integration_db, exclusion_consumer, mock_exclusion_data, monkeypatch, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_CREATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)
        
        Goal: Verify that mapping errors are treated as permanent failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_exclusion_created_message(mock_exclusion_data, correlation_id)
        
        print(f"\nProcessing CREATE message with mapping error: {correlation_id}")
        
        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(exclusion_consumer, "map_activity_exclusion_create", lambda x: None)
        
        # Process the message
        result = exclusion_consumer._process_activity_exclusion_message(message)
        
        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")
    
    def test_create_with_database_error_returns_retryable(self, integration_db, exclusion_consumer, mock_exclusion_data, monkeypatch, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_CREATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_exclusion_created_message(mock_exclusion_data, correlation_id)
        
        print(f"\nSimulating database error for CREATE: {correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_create_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(exclusion_consumer, "create_ref_activity_exclusion", mock_create_failure)
        
        # Process the message
        result = exclusion_consumer._process_activity_exclusion_message(message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Update Activity Exclusion Tests =====

class TestConsumerActivityExclusionUpdate:
    """Test consumer processing of ACTIVITY_EXCLUSION_UPDATED events"""
    
    def test_update_exclusion_processes_message_successfully(self, integration_db, exclusion_consumer, mock_exclusion_data, setup_test_activities):
        """
        GIVEN: Existing REF_ACTIVITY_EXCLUSION record and ACTIVITY_EXCLUSION_UPDATED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_EXCLUSION record is updated and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_EXCLUSION_UPDATED message updates the exclusion in REF_ACTIVITY_EXCLUSION table
        """
        # First create the exclusion
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_exclusion_created_message(mock_exclusion_data, create_correlation_id)
        exclusion_consumer._process_activity_exclusion_message(create_message)
        
        print(f"\nCreated initial exclusion ID: {mock_exclusion_data['id']}")
        
        # Clear processed events for clean test
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == create_correlation_id
        ).delete()
        integration_db.commit()
        
        # Update the exclusion
        updated_data = mock_exclusion_data.copy()
        updated_data["centre_activity_id"] = 999
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_exclusion_updated_message(
            mock_exclusion_data["id"],
            mock_exclusion_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing ACTIVITY_EXCLUSION_UPDATED message: {update_correlation_id}")
        
        # Process update message
        result = exclusion_consumer._process_activity_exclusion_message(update_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_EXCLUSION record updated
        ref_exclusion = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        
        assert ref_exclusion is not None
        assert ref_exclusion.ActivityID == 999
        assert ref_exclusion.IsDeleted == "0"
        
        print(f"DONE: Updated REF_ACTIVITY_EXCLUSION ID: {ref_exclusion.ActivityExclusionID}")
        print(f"  New ActivityID: {ref_exclusion.ActivityID}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_EXCLUSION_UPDATED"
        assert processed_event.aggregate_id == str(mock_exclusion_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_update_nonexistent_exclusion_succeeds_gracefully(self, integration_db, exclusion_consumer, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_UPDATED message for non-existent exclusion
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that updates for non-existent exclusions don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "patient_id": 99999,
            "centre_activity_id": 999,
            "is_deleted": False,
            "modified_by_id": "test-user",
            "modified_date": datetime.now().isoformat()
        }
        
        update_message = create_exclusion_updated_message(
            99999,
            non_existent_data,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing UPDATE for non-existent exclusion 99999")
        
        # Process the message
        result = exclusion_consumer._process_activity_exclusion_message(update_message)
        
        # Should succeed gracefully (no crash/retry)
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created (for idempotency tracking)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent exclusion update handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_update_message_is_idempotent(self, integration_db, exclusion_consumer, mock_exclusion_data, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_UPDATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and exclusion not updated again
        
        Goal: Verify idempotency for update messages
        """
        # Create initial exclusion
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_exclusion_created_message(mock_exclusion_data, create_correlation_id)
        exclusion_consumer._process_activity_exclusion_message(create_message)
        
        print(f"\nCreated initial exclusion ID: {mock_exclusion_data['id']}")
        
        # Update the exclusion
        updated_data = mock_exclusion_data.copy()
        updated_data["centre_activity_id"] = 999
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_exclusion_updated_message(
            mock_exclusion_data["id"],
            mock_exclusion_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing initial ACTIVITY_EXCLUSION_UPDATED message: {update_correlation_id}")
        
        # Process first time
        result1 = exclusion_consumer._process_activity_exclusion_message(update_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Get the updated timestamp
        first_update = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        first_updated_datetime = first_update.UpdatedDateTime
        
        print(f"First update completed at: {first_updated_datetime}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_EXCLUSION_UPDATED message: {update_correlation_id}")
        result2 = exclusion_consumer._process_activity_exclusion_message(update_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify UpdatedDateTime hasn't changed
        second_check = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        
        assert second_check.UpdatedDateTime == first_updated_datetime
        
        print(f"DONE: Duplicate update message handled correctly")
        print(f"Timestamp unchanged: {second_check.UpdatedDateTime}")
    
    def test_update_with_database_error_returns_retryable(self, integration_db, exclusion_consumer, mock_exclusion_data, monkeypatch, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_UPDATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial exclusion
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_exclusion_created_message(mock_exclusion_data, create_correlation_id)
        exclusion_consumer._process_activity_exclusion_message(create_message)
        
        print(f"\nCreated initial exclusion ID: {mock_exclusion_data['id']}")
        
        # Update message
        updated_data = mock_exclusion_data.copy()
        updated_data["centre_activity_id"] = 999
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_exclusion_updated_message(
            mock_exclusion_data["id"],
            mock_exclusion_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Simulating database error for UPDATE: {update_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_update_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(exclusion_consumer, "update_ref_activity_exclusion", mock_update_failure)
        
        # Process the message
        result = exclusion_consumer._process_activity_exclusion_message(update_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Delete Activity Exclusion Tests =====

class TestConsumerActivityExclusionDelete:
    """Test consumer processing of ACTIVITY_EXCLUSION_DELETED events"""
    
    def test_delete_exclusion_processes_message_successfully(self, integration_db, exclusion_consumer, mock_exclusion_data, setup_test_activities):
        """
        GIVEN: Existing REF_ACTIVITY_EXCLUSION record and ACTIVITY_EXCLUSION_DELETED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_EXCLUSION record is soft-deleted and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_EXCLUSION_DELETED message soft-deletes the exclusion
        """
        # First create the exclusion
        create_correlation_id = str(uuid.uuid4()).upper()
        mock_exclusion_data["id"] = 2003
        mock_exclusion_data["is_deleted"] = False
        create_message = create_exclusion_created_message(mock_exclusion_data, create_correlation_id)
        exclusion_consumer._process_activity_exclusion_message(create_message)
        
        print(f"\nCreated initial exclusion ID: {mock_exclusion_data['id']}")
        
        # Verify exclusion exists and is not deleted
        exclusion_before = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        assert exclusion_before.IsDeleted == "0"
        print(f"Exclusion before delete - IsDeleted: {exclusion_before.IsDeleted}")
        
        # Delete the exclusion
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_exclusion_deleted_message(
            mock_exclusion_data["id"],
            mock_exclusion_data,
            delete_correlation_id
        )
        
        print(f"Processing ACTIVITY_EXCLUSION_DELETED message: {delete_correlation_id}")
        
        # Process delete message
        result = exclusion_consumer._process_activity_exclusion_message(delete_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_EXCLUSION record soft-deleted
        ref_exclusion = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        
        integration_db.refresh(ref_exclusion)
        
        assert ref_exclusion is not None
        assert ref_exclusion.IsDeleted == "1"
        
        print(f"DONE: Soft-deleted REF_ACTIVITY_EXCLUSION ID: {ref_exclusion.ActivityExclusionID}")
        print(f"  IsDeleted: {ref_exclusion.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_EXCLUSION_DELETED"
        assert processed_event.aggregate_id == str(mock_exclusion_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_delete_nonexistent_exclusion_succeeds_gracefully(self, integration_db, exclusion_consumer, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_DELETED message for non-existent exclusion
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that deletes for non-existent exclusions don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "patient_id": 99999,
            "centre_activity_id": 999,
            "is_deleted": False
        }
        
        delete_message = create_exclusion_deleted_message(
            99999,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing DELETE for non-existent exclusion 99999")
        
        # Process the message
        result = exclusion_consumer._process_activity_exclusion_message(delete_message)
        
        # Should succeed gracefully
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent exclusion deletion handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_delete_message_is_idempotent(self, integration_db, exclusion_consumer, mock_exclusion_data, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_DELETED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and exclusion stays deleted
        
        Goal: Verify idempotency for delete messages
        """
        # Create initial exclusion
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_exclusion_created_message(mock_exclusion_data, create_correlation_id)
        exclusion_consumer._process_activity_exclusion_message(create_message)
        
        print(f"\nCreated initial exclusion ID: {mock_exclusion_data['id']}")
        
        # Delete the exclusion
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_exclusion_deleted_message(
            mock_exclusion_data["id"],
            mock_exclusion_data,
            delete_correlation_id
        )
        
        print(f"Processing initial ACTIVITY_EXCLUSION_DELETED message: {delete_correlation_id}")
        
        # Process first time
        result1 = exclusion_consumer._process_activity_exclusion_message(delete_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Verify deleted
        deleted_exclusion = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        assert deleted_exclusion.IsDeleted == "1"
        
        print(f"Exclusion soft-deleted: IsDeleted = {deleted_exclusion.IsDeleted}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_EXCLUSION_DELETED message: {delete_correlation_id}")
        result2 = exclusion_consumer._process_activity_exclusion_message(delete_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify still deleted
        still_deleted = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        assert still_deleted.IsDeleted == "1"
        
        print(f"DONE: Duplicate delete message handled correctly")
        print(f"Exclusion remains deleted: IsDeleted = {still_deleted.IsDeleted}")
    
    def test_delete_with_database_error_returns_retryable(self, integration_db, exclusion_consumer, mock_exclusion_data, monkeypatch, setup_test_activities):
        """
        GIVEN: ACTIVITY_EXCLUSION_DELETED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial exclusion
        mock_exclusion_data["id"] = 2005
        mock_exclusion_data["is_deleted"] = False
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_exclusion_created_message(mock_exclusion_data, create_correlation_id)
        exclusion_consumer._process_activity_exclusion_message(create_message)
        
        print(f"\nCreated initial exclusion ID: {mock_exclusion_data['id']}")
        
        # Delete message
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_exclusion_deleted_message(
            mock_exclusion_data["id"],
            mock_exclusion_data,
            delete_correlation_id
        )
        
        print(f"Simulating database error for DELETE: {delete_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_delete_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(exclusion_consumer, "delete_ref_activity_exclusion", mock_delete_failure)
        
        # Process the message
        result = exclusion_consumer._process_activity_exclusion_message(delete_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is None
        
        # Verify exclusion was NOT deleted (operation failed before completion)
        exclusion_check = integration_db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == mock_exclusion_data["id"]
        ).first()
        assert exclusion_check.IsDeleted == "0"
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")
        print(f"Exclusion remains active (IsDeleted=0) - will be deleted on retry")