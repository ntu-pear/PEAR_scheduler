"""
Integration tests for Scheduler Service Activity Preference Consumer
Tests the flow: RabbitMQ Message → Activity Preference Consumer → REF_ACTIVITY_PREFERENCE table update → PROCESSED_EVENTS tracking
"""

import json
import uuid
from datetime import date, datetime
from typing import Any, Dict

import pytest
from sqlalchemy.orm import Session

from messaging.activity_preference_consumer import ActivityPreferenceConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
from pear_schedule.models.ref_activity_model import RefActivity
from pear_schedule.models.ref_activity_preference_model import RefActivityPreference
from pear_schedule.models.ref_centre_activity_model import RefCentreActivity
from pear_schedule.models.ref_patient_model import RefPatient
from pear_schedule.schemas.ref_activity_preference import (
    RefActivityPreferenceCreate,
    RefActivityPreferenceDelete,
    RefActivityPreferenceUpdate,
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
    Create test patients, activities, and centre activities required for foreign key constraints.
    """
    # ===== CREATE TEST PATIENTS =====
    existing_patient_1 = integration_db.query(RefPatient).filter(RefPatient.PatientID == 1).first()
    existing_patient_2 = integration_db.query(RefPatient).filter(RefPatient.PatientID == 2).first()
    
    patients_created = []
    
    if not existing_patient_1:
        patient_1 = RefPatient(
            PatientID=1,
            IsDeleted="0",
            Name="Test",
            PreferredName="Patient 1",
            UpdateBit="1",
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
            IsDeleted="0",
            Name="Test",
            PreferredName="Patient 2",
            UpdateBit="1",
            StartDate=datetime.now(),
            EndDate=datetime.now(),
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        
    #         PatientID = Column(Integer, primary_key=True, index=True)
    # IsDeleted = Column(String(1), default='0', nullable=False)
    # Name = Column(String(255), nullable=False)
    # PreferredName = Column(String(255))
    # UpdateBit = Column(String(1), default="1", nullable=False)
    # StartDate = Column(DateTime, nullable=False)
    # EndDate = Column(DateTime)
    # IsActive = Column(String(1), default="1", nullable=False)
        
        integration_db.add(patient_2)
        patients_created.append(2)
    
    # ===== CREATE TEST ACTIVITIES =====
    existing_act_1 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 1).first()
    existing_act_2 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 2).first()
    existing_act_3 = integration_db.query(RefActivity).filter(RefActivity.ActivityID == 3).first()
    
    activities_created = []
    
    if not existing_act_1:
        activity_1 = RefActivity(
            ActivityID=1,
            ActivityTitle="Test Activity 1",
            ActivityDesc="Test activity for preferences",
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
            ActivityDesc="Test activity for preferences",
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
            ActivityDesc="Test activity for preferences",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(activity_3)
        activities_created.append(3)
    
    # ===== CREATE TEST CENTRE ACTIVITIES =====
    existing_ca_101 = integration_db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == 101).first()
    existing_ca_102 = integration_db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == 102).first()
    existing_ca_999 = integration_db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == 999).first()
    
    centre_activities_created = []
    
    if not existing_ca_101:
        centre_activity_101 = RefCentreActivity(
            CentreActivityID=101,
            ActivityID=1,
            IsDeleted="0",
            IsCompulsory="0",
            IsFixed="0",
            IsGroup="0",
            StartDate=date.today(),
            EndDate=date.today(),
            MinDuration=30,
            MaxDuration=60,
            MinPeopleReq=1,
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(centre_activity_101)
        centre_activities_created.append(101)
    
    if not existing_ca_102:
        centre_activity_102 = RefCentreActivity(
            CentreActivityID=102,
            ActivityID=2,
            IsDeleted="0",
            IsCompulsory="0",
            IsFixed="0",
            IsGroup="0",
            StartDate=date.today(),
            EndDate=date.today(),
            MinDuration=30,
            MaxDuration=60,
            MinPeopleReq=1,
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(centre_activity_102)
        centre_activities_created.append(102)
    
    if not existing_ca_999:
        centre_activity_999 = RefCentreActivity(
            CentreActivityID=999,
            ActivityID=3,
            IsDeleted="0",
            IsCompulsory="0",
            IsFixed="0",
            IsGroup="0",
            StartDate=date.today(),
            EndDate=date.today(),
            MinDuration=30,
            MaxDuration=60,
            MinPeopleReq=1,
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
        integration_db.add(centre_activity_999)
        centre_activities_created.append(999)
    
    integration_db.commit()
    
    if patients_created:
        print(f"\n[SETUP] Created test patients: {patients_created}")
    if activities_created:
        print(f"\n[SETUP] Created test activities: {activities_created}")
    if centre_activities_created:
        print(f"\n[SETUP] Created test centre activities: {centre_activities_created}")
    if not patients_created and not activities_created and not centre_activities_created:
        print(f"\n[SETUP] All test data already exists")
    
    yield


@pytest.fixture
def preference_consumer():
    """
    Fixture for ActivityPreferenceConsumer instance.
    """
    consumer = ActivityPreferenceConsumer()
    yield consumer
    # Cleanup
    if consumer.client:
        consumer.client.close()


@pytest.fixture
def mock_preference_data():
    """
    Mock activity preference data matching the Activity Service schema
    """
    return {
        "id": 3001,
        "patient_id": 1,
        "centre_activity_id": 101,
        "is_like": 5,
        "is_deleted": False,
        "created_by_id": "test-user-1",
        "modified_by_id": "test-user-1",
        "created_date": datetime.now().isoformat(),
        "modified_date": datetime.now().isoformat()
    }


@pytest.fixture
def mock_preference_data_for_idempotency_check():
    """
    Mock activity preference data for idempotency tests
    """
    return {
        "id": 3002,
        "patient_id": 2,
        "centre_activity_id": 102,
        "is_like": 3,
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
        
        # Delete all ref activity preferences
        integration_db.query(RefActivityPreference).delete()
        integration_db.commit()
        
        print("\n[CLEANUP] Test data cleared successfully")
    except Exception as e:
        integration_db.rollback()
        print(f"\n[CLEANUP] Warning: Failed to cleanup test data: {str(e)}")


# ===== Helper Functions =====

def create_preference_created_message(preference_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_PREFERENCE_CREATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "ACTIVITY_PREFERENCE_CREATED",
            "preference_id": preference_data["id"],
            "preference_data": preference_data,
            "created_by": preference_data.get("created_by_id", "test-user"),
            "created_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_preference_updated_message(preference_id: int, old_data: Dict[str, Any], 
                                     new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_PREFERENCE_UPDATED message"""
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
            "event_type": "ACTIVITY_PREFERENCE_UPDATED",
            "preference_id": preference_id,
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("modified_by_id", "test-user"),
            "modified_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_preference_deleted_message(preference_id: int, preference_data: Dict[str, Any], 
                                     correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_PREFERENCE_DELETED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "ACTIVITY_PREFERENCE_DELETED",
            "preference_id": preference_id,
            "preference_data": preference_data,
            "deleted_by": "test-user",
            "deleted_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


# ===== Create Activity Preference Tests =====

class TestConsumerActivityPreferenceCreate:
    """Test consumer processing of ACTIVITY_PREFERENCE_CREATED events"""
    
    def test_create_preference_processes_message_successfully(self, integration_db, preference_consumer, mock_preference_data, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_PREFERENCE record is created and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_PREFERENCE_CREATED message creates the preference in REF_ACTIVITY_PREFERENCE table
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_preference_created_message(mock_preference_data, correlation_id)
        
        print(f"\nProcessing ACTIVITY_PREFERENCE_CREATED message with correlation_id: {correlation_id}")
        
        # Process the message
        result = preference_consumer._process_activity_preference_message(message)
        
        print(f"Processing result: {result}")
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_PREFERENCE record created
        ref_preference = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        
        assert ref_preference is not None
        assert ref_preference.PatientID == mock_preference_data["patient_id"]
        assert ref_preference.CentreActivityID == mock_preference_data["centre_activity_id"]
        assert ref_preference.IsDeleted == "0"
        
        print(f"DONE: Created REF_ACTIVITY_PREFERENCE ID: {ref_preference.CentreActivityPreferenceID}")
        print(f"  PatientID: {ref_preference.PatientID}")
        print(f"  CentreActivityID: {ref_preference.CentreActivityID}")
        print(f"  IsDeleted: {ref_preference.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        processed_event_status = json.loads(processed_event.operation_result)["status"]
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_PREFERENCE_CREATED"
        assert processed_event.aggregate_id == str(mock_preference_data["id"])
        assert processed_event_status == "success"
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
        print(f"  Event Type: {processed_event.event_type}")
        print(f"  Status: {processed_event_status}")
    
    def test_duplicate_create_message_is_idempotent(self, integration_db, preference_consumer, mock_preference_data_for_idempotency_check, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_CREATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and no additional records created
        
        Goal: Verify idempotency - duplicate messages don't create duplicate records
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_preference_created_message(mock_preference_data_for_idempotency_check, correlation_id)
        
        print(f"\nProcessing initial ACTIVITY_PREFERENCE_CREATED message: {correlation_id}")
        
        # Process first time
        result1 = preference_consumer._process_activity_preference_message(message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        initial_preference_count = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data_for_idempotency_check["id"]
        ).count()
        initial_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        print(f"Initial counts - Preferences: {initial_preference_count}, Processed Events: {initial_processed_count}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_PREFERENCE_CREATED message: {correlation_id}")
        result2 = preference_consumer._process_activity_preference_message(message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify no additional records created
        final_preference_count = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data_for_idempotency_check["id"]
        ).count()
        final_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        assert final_preference_count == initial_preference_count
        assert final_processed_count == initial_processed_count
        
        print(f"DONE: Duplicate message handled correctly - no new records created")
        print(f"Final counts - Preferences: {final_preference_count}, Processed Events: {final_processed_count}")
    
    def test_create_with_invalid_data_fails_permanently(self, integration_db, preference_consumer, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_CREATED message with invalid/missing data
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
                "event_type": "ACTIVITY_PREFERENCE_CREATED",
                # Missing preference_id and preference_data
            }
        }
        
        print(f"\nProcessing invalid ACTIVITY_PREFERENCE_CREATED message: {correlation_id}")
        
        # Process the message
        result = preference_consumer._process_activity_preference_message(invalid_message)
        
        # Should fail permanently
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        # Verify no records created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Invalid message rejected permanently - no records created")
    
    def test_create_with_mapping_failure_fails_permanently(self, integration_db, preference_consumer, mock_preference_data, monkeypatch, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_CREATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)
        
        Goal: Verify that mapping errors are treated as permanent failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_preference_created_message(mock_preference_data, correlation_id)
        
        print(f"\nProcessing CREATE message with mapping error: {correlation_id}")
        
        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(preference_consumer, "map_activity_preference_create", lambda x: None)
        
        # Process the message
        result = preference_consumer._process_activity_preference_message(message)
        
        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")
    
    def test_create_with_database_error_returns_retryable(self, integration_db, preference_consumer, mock_preference_data, monkeypatch, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_CREATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_preference_created_message(mock_preference_data, correlation_id)
        
        print(f"\nSimulating database error for CREATE: {correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_create_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(preference_consumer, "create_ref_activity_preference", mock_create_failure)
        
        # Process the message
        result = preference_consumer._process_activity_preference_message(message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Update Activity Preference Tests =====

class TestConsumerActivityPreferenceUpdate:
    """Test consumer processing of ACTIVITY_PREFERENCE_UPDATED events"""
    
    def test_update_preference_processes_message_successfully(self, integration_db, preference_consumer, mock_preference_data, setup_test_data):
        """
        GIVEN: Existing REF_ACTIVITY_PREFERENCE record and ACTIVITY_PREFERENCE_UPDATED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_PREFERENCE record is updated and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_PREFERENCE_UPDATED message updates the preference in REF_ACTIVITY_PREFERENCE table
        """
        # First create the preference
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_preference_created_message(mock_preference_data, create_correlation_id)
        preference_consumer._process_activity_preference_message(create_message)
        
        print(f"\nCreated initial preference ID: {mock_preference_data['id']}")
        
        # Clear processed events for clean test
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == create_correlation_id
        ).delete()
        integration_db.commit()
        
        # Update the preference
        updated_data = mock_preference_data.copy()
        # updated_data["id"] = 3005 # Modify this ID to 3005, which is not deleted yet
        updated_data["centre_activity_id"] = 999  # ✅ Change to CentreActivityID 999
        updated_data["is_like"] = 1
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_preference_updated_message(
            mock_preference_data["id"],
            mock_preference_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing ACTIVITY_PREFERENCE_UPDATED message: {update_correlation_id}")
        
        # Process update message
        result = preference_consumer._process_activity_preference_message(update_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_PREFERENCE record updated
        ref_preference = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        
        integration_db.refresh(ref_preference)  # Force refresh from DB
        print(f"DEBUG: CentreActivityID after update: {ref_preference.CentreActivityID}")
        print(f"DEBUG: Expected: 999")
        print(f"DEBUG: Updated data sent: {updated_data['centre_activity_id']}")
        
        
        assert ref_preference is not None
        assert ref_preference.CentreActivityID == 999
        assert ref_preference.IsDeleted == "0"
        
        print(f"DONE: Updated REF_ACTIVITY_PREFERENCE ID: {ref_preference.CentreActivityPreferenceID}")
        print(f"  New CentreActivityID: {ref_preference.CentreActivityID}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_PREFERENCE_UPDATED"
        assert processed_event.aggregate_id == str(mock_preference_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_update_nonexistent_preference_succeeds_gracefully(self, integration_db, preference_consumer, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_UPDATED message for non-existent preference
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that updates for non-existent preferences don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "patient_id": 99999,
            "centre_activity_id": 999,
            "is_like": 3,
            "is_deleted": False,
            "modified_by_id": "test-user",
            "modified_date": datetime.now().isoformat()
        }
        
        update_message = create_preference_updated_message(
            99999,
            non_existent_data,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing UPDATE for non-existent preference 99999")
        
        # Process the message
        result = preference_consumer._process_activity_preference_message(update_message)
        
        # Should succeed gracefully (no crash/retry)
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created (for idempotency tracking)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent preference update handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_update_message_is_idempotent(self, integration_db, preference_consumer, mock_preference_data, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_UPDATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and preference not updated again
        
        Goal: Verify idempotency for update messages
        """
        # Create initial preference
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_preference_created_message(mock_preference_data, create_correlation_id)
        preference_consumer._process_activity_preference_message(create_message)
        
        print(f"\nCreated initial preference ID: {mock_preference_data['id']}")
        
        # Update the preference
        updated_data = mock_preference_data.copy()
        updated_data["centre_activity_id"] = 999
        updated_data["is_like"] = 1
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_preference_updated_message(
            mock_preference_data["id"],
            mock_preference_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing initial ACTIVITY_PREFERENCE_UPDATED message: {update_correlation_id}")
        
        # Process first time
        result1 = preference_consumer._process_activity_preference_message(update_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Get the updated timestamp
        first_update = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        first_updated_datetime = first_update.UpdatedDateTime
        
        print(f"First update completed at: {first_updated_datetime}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_PREFERENCE_UPDATED message: {update_correlation_id}")
        result2 = preference_consumer._process_activity_preference_message(update_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify UpdatedDateTime hasn't changed
        second_check = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        
        assert second_check.UpdatedDateTime == first_updated_datetime
        
        print(f"DONE: Duplicate update message handled correctly")
        print(f"Timestamp unchanged: {second_check.UpdatedDateTime}")
    
    def test_update_with_database_error_returns_retryable(self, integration_db, preference_consumer, mock_preference_data, monkeypatch, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_UPDATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial preference
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_preference_created_message(mock_preference_data, create_correlation_id)
        preference_consumer._process_activity_preference_message(create_message)
        
        print(f"\nCreated initial preference ID: {mock_preference_data['id']}")
        
        # Update message
        updated_data = mock_preference_data.copy()
        updated_data["centre_activity_id"] = 999
        updated_data["is_like"] = 1
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_preference_updated_message(
            mock_preference_data["id"],
            mock_preference_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Simulating database error for UPDATE: {update_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_update_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(preference_consumer, "update_ref_activity_preference", mock_update_failure)
        
        # Process the message
        result = preference_consumer._process_activity_preference_message(update_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Delete Activity Preference Tests =====

class TestConsumerActivityPreferenceDelete:
    """Test consumer processing of ACTIVITY_PREFERENCE_DELETED events"""
    
    def test_delete_preference_processes_message_successfully(self, integration_db, preference_consumer, mock_preference_data, setup_test_data):
        """
        GIVEN: Existing REF_ACTIVITY_PREFERENCE record and ACTIVITY_PREFERENCE_DELETED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_PREFERENCE record is soft-deleted and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_PREFERENCE_DELETED message soft-deletes the preference
        """
        # First create the preference
        create_correlation_id = str(uuid.uuid4()).upper()
        mock_preference_data["id"] = 3003
        mock_preference_data["is_deleted"] = False
        create_message = create_preference_created_message(mock_preference_data, create_correlation_id)
        preference_consumer._process_activity_preference_message(create_message)
        
        print(f"\nCreated initial preference ID: {mock_preference_data['id']}")
        
        # Verify preference exists and is not deleted
        preference_before = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        assert preference_before.IsDeleted == "0"
        print(f"Preference before delete - IsDeleted: {preference_before.IsDeleted}")
        
        # Delete the preference
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_preference_deleted_message(
            mock_preference_data["id"],
            mock_preference_data,
            delete_correlation_id
        )
        
        print(f"Processing ACTIVITY_PREFERENCE_DELETED message: {delete_correlation_id}")
        
        # Process delete message
        result = preference_consumer._process_activity_preference_message(delete_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_PREFERENCE record soft-deleted
        ref_preference = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        
        integration_db.refresh(ref_preference)
        
        assert ref_preference is not None
        assert ref_preference.IsDeleted == "1"
        
        print(f"DONE: Soft-deleted REF_ACTIVITY_PREFERENCE ID: {ref_preference.CentreActivityPreferenceID}")
        print(f"  IsDeleted: {ref_preference.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_PREFERENCE_DELETED"
        assert processed_event.aggregate_id == str(mock_preference_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_delete_nonexistent_preference_succeeds_gracefully(self, integration_db, preference_consumer, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_DELETED message for non-existent preference
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that deletes for non-existent preferences don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "patient_id": 99999,
            "centre_activity_id": 999,
            "is_like": 3,
            "is_deleted": False
        }
        
        delete_message = create_preference_deleted_message(
            99999,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing DELETE for non-existent preference 99999")
        
        # Process the message
        result = preference_consumer._process_activity_preference_message(delete_message)
        
        # Should succeed gracefully
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent preference deletion handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_delete_message_is_idempotent(self, integration_db, preference_consumer, mock_preference_data, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_DELETED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and preference stays deleted
        
        Goal: Verify idempotency for delete messages
        """
        # Create initial preference
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_preference_created_message(mock_preference_data, create_correlation_id)
        preference_consumer._process_activity_preference_message(create_message)
        
        print(f"\nCreated initial preference ID: {mock_preference_data['id']}")
        
        # Delete the preference
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_preference_deleted_message(
            mock_preference_data["id"],
            mock_preference_data,
            delete_correlation_id
        )
        
        print(f"Processing initial ACTIVITY_PREFERENCE_DELETED message: {delete_correlation_id}")
        
        # Process first time
        result1 = preference_consumer._process_activity_preference_message(delete_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Verify deleted
        deleted_preference = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        assert deleted_preference.IsDeleted == "1"
        
        print(f"Preference soft-deleted: IsDeleted = {deleted_preference.IsDeleted}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_PREFERENCE_DELETED message: {delete_correlation_id}")
        result2 = preference_consumer._process_activity_preference_message(delete_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify still deleted
        still_deleted = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        assert still_deleted.IsDeleted == "1"
        
        print(f"DONE: Duplicate delete message handled correctly")
        print(f"Preference remains deleted: IsDeleted = {still_deleted.IsDeleted}")
    
    def test_delete_with_database_error_returns_retryable(self, integration_db, preference_consumer, mock_preference_data, monkeypatch, setup_test_data):
        """
        GIVEN: ACTIVITY_PREFERENCE_DELETED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial preference
        mock_preference_data["id"] = 3005
        mock_preference_data["is_deleted"] = False
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_preference_created_message(mock_preference_data, create_correlation_id)
        preference_consumer._process_activity_preference_message(create_message)
        
        print(f"\nCreated initial preference ID: {mock_preference_data['id']}")
        
        # Delete message
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_preference_deleted_message(
            mock_preference_data["id"],
            mock_preference_data,
            delete_correlation_id
        )
        
        print(f"Simulating database error for DELETE: {delete_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_delete_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(preference_consumer, "delete_ref_activity_preference", mock_delete_failure)
        
        # Process the message
        result = preference_consumer._process_activity_preference_message(delete_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is None
        
        # Verify preference was NOT deleted (operation failed before completion)
        preference_check = integration_db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == mock_preference_data["id"]
        ).first()
        assert preference_check.IsDeleted == "0"
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")
        print(f"Preference remains active (IsDeleted=0) - will be deleted on retry")