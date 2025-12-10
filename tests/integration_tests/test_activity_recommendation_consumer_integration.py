"""
Integration tests for Scheduler Service Activity Recommendation Consumer
Tests the flow: RabbitMQ Message → Activity Recommendation Consumer → REF_ACTIVITY_RECOMMENDATION table update → PROCESSED_EVENTS tracking

Run Pytest with command: pytest tests/integration_tests/test_activity_recommendation_consumer_integration.py -v -s
SQL Commands to clear DB:
DELETE FROM [fyp_dev_bryan_activity_test].[dbo].[REF_ACTIVITY_RECOMMENDATION];
DELETE FROM [fyp_dev_bryan_activity_test].[dbo].[PROCESSED_EVENTS];
DELETE FROM [fyp_dev_bryan_activity_test].[dbo].[REF_CENTRE_ACTIVITY] WHERE CentreActivityID IN (101, 102, 999);
DELETE FROM [fyp_dev_bryan_activity_test].[dbo].[REF_ACTIVITY] WHERE ActivityID IN (1, 2, 3);
DELETE FROM [fyp_dev_bryan_activity_test].[dbo].[REF_PATIENT] WHERE PatientID IN (1, 2);
"""

import json
import uuid
from datetime import date, datetime
from typing import Any, Dict

import pytest
from sqlalchemy.orm import Session

from messaging.activity_recommendation_consumer import ActivityRecommendationConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
from pear_schedule.models.ref_activity_model import RefActivity
from pear_schedule.models.ref_activity_recommendation_model import (
    RefActivityRecommendation,
)
from pear_schedule.models.ref_centre_activity_model import RefCentreActivity
from pear_schedule.models.ref_patient_model import RefPatient

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
            FirstName="Test",
            LastName="Patient 1",
            IsDeleted="0",
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
            FirstName="Test",
            LastName="Patient 2",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test-user",
            ModifiedById="test-user"
        )
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
            ActivityDesc="Test activity for recommendations",
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
            ActivityDesc="Test activity for recommendations",
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
            ActivityDesc="Test activity for recommendations",
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
def recommendation_consumer():
    """
    Fixture for ActivityRecommendationConsumer instance.
    """
    consumer = ActivityRecommendationConsumer()
    yield consumer
    # Cleanup
    if consumer.client:
        consumer.client.close()


@pytest.fixture
def mock_recommendation_data():
    """
    Mock activity recommendation data matching the Activity Service schema
    """
    return {
        "id": 4001,
        "patient_id": 1,
        "centre_activity_id": 101,
        "doctor_id": "DOC-001",
        "doctor_recommendation": "1",
        "doctor_remarks": "Highly recommended for patient recovery",
        "is_deleted": False,
        "created_by_id": "test-user-1",
        "modified_by_id": "test-user-1",
        "created_date": datetime.now().isoformat(),
        "modified_date": datetime.now().isoformat()
    }


@pytest.fixture
def mock_recommendation_data_for_idempotency_check():
    """
    Mock activity recommendation data for idempotency tests
    """
    return {
        "id": 4002,
        "patient_id": 2, 
        "centre_activity_id": 102,
        "doctor_id": "DOC-002",
        "doctor_recommendation": "1",
        "doctor_remarks": "Good for physical therapy",
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
        
        # Delete all ref activity recommendations
        integration_db.query(RefActivityRecommendation).delete()
        integration_db.commit()
        
        print("\n[CLEANUP] Test data cleared successfully")
    except Exception as e:
        integration_db.rollback()
        print(f"\n[CLEANUP] Warning: Failed to cleanup test data: {str(e)}")


# ===== Helper Functions =====

def create_recommendation_created_message(recommendation_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_RECOMMENDATION_CREATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "ACTIVITY_RECOMMENDATION_CREATED",
            "recommendation_id": recommendation_data["id"],
            "recommendation_data": recommendation_data,
            "created_by": recommendation_data.get("created_by_id", "test-user"),
            "created_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_recommendation_updated_message(recommendation_id: int, old_data: Dict[str, Any], 
                                         new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_RECOMMENDATION_UPDATED message"""
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
            "event_type": "ACTIVITY_RECOMMENDATION_UPDATED",
            "recommendation_id": recommendation_id,
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("modified_by_id", "test-user"),
            "modified_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_recommendation_deleted_message(recommendation_id: int, recommendation_data: Dict[str, Any], 
                                         correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create ACTIVITY_RECOMMENDATION_DELETED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "ACTIVITY_RECOMMENDATION_DELETED",
            "recommendation_id": recommendation_id,
            "recommendation_data": recommendation_data,
            "deleted_by": "test-user",
            "deleted_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


# ===== Create Activity Recommendation Tests =====

class TestConsumerActivityRecommendationCreate:
    """Test consumer processing of ACTIVITY_RECOMMENDATION_CREATED events"""
    
    def test_create_recommendation_processes_message_successfully(self, integration_db, recommendation_consumer, mock_recommendation_data, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_RECOMMENDATION record is created and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_RECOMMENDATION_CREATED message creates the recommendation in REF_ACTIVITY_RECOMMENDATION table
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_recommendation_created_message(mock_recommendation_data, correlation_id)
        
        print(f"\nProcessing ACTIVITY_RECOMMENDATION_CREATED message with correlation_id: {correlation_id}")
        
        # Process the message
        result = recommendation_consumer._process_activity_recommendation_message(message)
        
        print(f"Processing result: {result}")
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_RECOMMENDATION record created
        ref_recommendation = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        
        assert ref_recommendation is not None
        assert ref_recommendation.PatientID == mock_recommendation_data["patient_id"]
        assert ref_recommendation.CentreActivityID == mock_recommendation_data["centre_activity_id"]
        assert ref_recommendation.DoctorID == mock_recommendation_data["doctor_id"]
        assert ref_recommendation.IsDeleted == "0"
        
        print(f"DONE: Created REF_ACTIVITY_RECOMMENDATION ID: {ref_recommendation.CentreActivityRecommendationID}")
        print(f"  PatientID: {ref_recommendation.PatientID}")
        print(f"  CentreActivityID: {ref_recommendation.CentreActivityID}")
        print(f"  DoctorID: {ref_recommendation.DoctorID}")
        print(f"  IsDeleted: {ref_recommendation.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        processed_event_status = json.loads(processed_event.operation_result)["status"]
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_RECOMMENDATION_CREATED"
        assert processed_event.aggregate_id == str(mock_recommendation_data["id"])
        assert processed_event_status == "success"
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
        print(f"  Event Type: {processed_event.event_type}")
        print(f"  Status: {processed_event_status}")
    
    def test_duplicate_create_message_is_idempotent(self, integration_db, recommendation_consumer, mock_recommendation_data_for_idempotency_check, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_CREATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and no additional records created
        
        Goal: Verify idempotency - duplicate messages don't create duplicate records
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_recommendation_created_message(mock_recommendation_data_for_idempotency_check, correlation_id)
        
        print(f"\nProcessing initial ACTIVITY_RECOMMENDATION_CREATED message: {correlation_id}")
        
        # Process first time
        result1 = recommendation_consumer._process_activity_recommendation_message(message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        initial_recommendation_count = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data_for_idempotency_check["id"]
        ).count()
        initial_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        print(f"Initial counts - Recommendations: {initial_recommendation_count}, Processed Events: {initial_processed_count}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_RECOMMENDATION_CREATED message: {correlation_id}")
        result2 = recommendation_consumer._process_activity_recommendation_message(message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify no additional records created
        final_recommendation_count = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data_for_idempotency_check["id"]
        ).count()
        final_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()
        
        assert final_recommendation_count == initial_recommendation_count
        assert final_processed_count == initial_processed_count
        
        print(f"DONE: Duplicate message handled correctly - no new records created")
        print(f"Final counts - Recommendations: {final_recommendation_count}, Processed Events: {final_processed_count}")
    
    def test_create_with_invalid_data_fails_permanently(self, integration_db, recommendation_consumer, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_CREATED message with invalid/missing data
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
                "event_type": "ACTIVITY_RECOMMENDATION_CREATED",
                # Missing recommendation_id and recommendation_data
            }
        }
        
        print(f"\nProcessing invalid ACTIVITY_RECOMMENDATION_CREATED message: {correlation_id}")
        
        # Process the message
        result = recommendation_consumer._process_activity_recommendation_message(invalid_message)
        
        # Should fail permanently
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        # Verify no records created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Invalid message rejected permanently - no records created")
    
    def test_create_with_mapping_failure_fails_permanently(self, integration_db, recommendation_consumer, mock_recommendation_data, monkeypatch, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_CREATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)
        
        Goal: Verify that mapping errors are treated as permanent failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_recommendation_created_message(mock_recommendation_data, correlation_id)
        
        print(f"\nProcessing CREATE message with mapping error: {correlation_id}")
        
        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(recommendation_consumer, "map_activity_recommendation_create", lambda x: None)
        
        # Process the message
        result = recommendation_consumer._process_activity_recommendation_message(message)
        
        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT
        
        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")
    
    def test_create_with_database_error_returns_retryable(self, integration_db, recommendation_consumer, mock_recommendation_data, monkeypatch, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_CREATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_recommendation_created_message(mock_recommendation_data, correlation_id)
        
        print(f"\nSimulating database error for CREATE: {correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_create_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(recommendation_consumer, "create_ref_activity_recommendation", mock_create_failure)
        
        # Process the message
        result = recommendation_consumer._process_activity_recommendation_message(message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Update Activity Recommendation Tests =====

class TestConsumerActivityRecommendationUpdate:
    """Test consumer processing of ACTIVITY_RECOMMENDATION_UPDATED events"""
    
    def test_update_recommendation_processes_message_successfully(self, integration_db, recommendation_consumer, mock_recommendation_data, setup_test_data):
        """
        GIVEN: Existing REF_ACTIVITY_RECOMMENDATION record and ACTIVITY_RECOMMENDATION_UPDATED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_RECOMMENDATION record is updated and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_RECOMMENDATION_UPDATED message updates the recommendation in REF_ACTIVITY_RECOMMENDATION table
        """
        # First create the recommendation
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_recommendation_created_message(mock_recommendation_data, create_correlation_id)
        recommendation_consumer._process_activity_recommendation_message(create_message)
        
        print(f"\nCreated initial recommendation ID: {mock_recommendation_data['id']}")
        
        # Clear processed events for clean test
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == create_correlation_id
        ).delete()
        integration_db.commit()
        
        # Update the recommendation
        updated_data = mock_recommendation_data.copy()
        updated_data["centre_activity_id"] = 999
        updated_data["doctor_remarks"] = "Updated recommendation remarks"
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_recommendation_updated_message(
            mock_recommendation_data["id"],
            mock_recommendation_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing ACTIVITY_RECOMMENDATION_UPDATED message: {update_correlation_id}")
        
        # Process update message
        result = recommendation_consumer._process_activity_recommendation_message(update_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_RECOMMENDATION record updated
        ref_recommendation = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        
        assert ref_recommendation is not None
        assert ref_recommendation.CentreActivityID == 999
        assert ref_recommendation.DoctorRemarks == "Updated recommendation remarks"
        assert ref_recommendation.IsDeleted == "0"
        
        print(f"DONE: Updated REF_ACTIVITY_RECOMMENDATION ID: {ref_recommendation.CentreActivityRecommendationID}")
        print(f"  New CentreActivityID: {ref_recommendation.CentreActivityID}")
        print(f"  New DoctorRemarks: {ref_recommendation.DoctorRemarks}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_RECOMMENDATION_UPDATED"
        assert processed_event.aggregate_id == str(mock_recommendation_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_update_nonexistent_recommendation_succeeds_gracefully(self, integration_db, recommendation_consumer, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_UPDATED message for non-existent recommendation
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that updates for non-existent recommendations don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "patient_id": 99999,
            "centre_activity_id": 999,
            "doctor_id": "DOC-999",
            "doctor_recommendation": "1",
            "doctor_remarks": "Test",
            "is_deleted": False,
            "modified_by_id": "test-user",
            "modified_date": datetime.now().isoformat()
        }
        
        update_message = create_recommendation_updated_message(
            99999,
            non_existent_data,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing UPDATE for non-existent recommendation 99999")
        
        # Process the message
        result = recommendation_consumer._process_activity_recommendation_message(update_message)
        
        # Should succeed gracefully (no crash/retry)
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created (for idempotency tracking)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent recommendation update handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_update_message_is_idempotent(self, integration_db, recommendation_consumer, mock_recommendation_data, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_UPDATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and recommendation not updated again
        
        Goal: Verify idempotency for update messages
        """
        # Create initial recommendation
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_recommendation_created_message(mock_recommendation_data, create_correlation_id)
        recommendation_consumer._process_activity_recommendation_message(create_message)
        
        print(f"\nCreated initial recommendation ID: {mock_recommendation_data['id']}")
        
        # Update the recommendation
        updated_data = mock_recommendation_data.copy()
        updated_data["centre_activity_id"] = 999
        updated_data["doctor_remarks"] = "Updated remarks for idempotency test"
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_recommendation_updated_message(
            mock_recommendation_data["id"],
            mock_recommendation_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Processing initial ACTIVITY_RECOMMENDATION_UPDATED message: {update_correlation_id}")
        
        # Process first time
        result1 = recommendation_consumer._process_activity_recommendation_message(update_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Get the updated timestamp
        first_update = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        first_updated_datetime = first_update.UpdatedDateTime
        
        print(f"First update completed at: {first_updated_datetime}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_RECOMMENDATION_UPDATED message: {update_correlation_id}")
        result2 = recommendation_consumer._process_activity_recommendation_message(update_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify UpdatedDateTime hasn't changed
        second_check = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        
        assert second_check.UpdatedDateTime == first_updated_datetime
        
        print(f"DONE: Duplicate update message handled correctly")
        print(f"Timestamp unchanged: {second_check.UpdatedDateTime}")
    
    def test_update_with_database_error_returns_retryable(self, integration_db, recommendation_consumer, mock_recommendation_data, monkeypatch, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_UPDATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial recommendation
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_recommendation_created_message(mock_recommendation_data, create_correlation_id)
        recommendation_consumer._process_activity_recommendation_message(create_message)
        
        print(f"\nCreated initial recommendation ID: {mock_recommendation_data['id']}")
        
        # Update message
        updated_data = mock_recommendation_data.copy()
        updated_data["centre_activity_id"] = 999
        updated_data["doctor_remarks"] = "Test database error"
        updated_data["modified_date"] = datetime.now().isoformat()
        
        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_recommendation_updated_message(
            mock_recommendation_data["id"],
            mock_recommendation_data,
            updated_data,
            update_correlation_id
        )
        
        print(f"Simulating database error for UPDATE: {update_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_update_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(recommendation_consumer, "update_ref_activity_recommendation", mock_update_failure)
        
        # Process the message
        result = recommendation_consumer._process_activity_recommendation_message(update_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()
        
        assert processed_event is None
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Delete Activity Recommendation Tests =====

class TestConsumerActivityRecommendationDelete:
    """Test consumer processing of ACTIVITY_RECOMMENDATION_DELETED events"""
    
    def test_delete_recommendation_processes_message_successfully(self, integration_db, recommendation_consumer, mock_recommendation_data, setup_test_data):
        """
        GIVEN: Existing REF_ACTIVITY_RECOMMENDATION record and ACTIVITY_RECOMMENDATION_DELETED message
        WHEN: Consumer processes the message
        THEN: REF_ACTIVITY_RECOMMENDATION record is soft-deleted and PROCESSED_EVENTS record exists
        
        Goal: Verify that consuming an ACTIVITY_RECOMMENDATION_DELETED message soft-deletes the recommendation
        """
        # First create the recommendation
        create_correlation_id = str(uuid.uuid4()).upper()
        mock_recommendation_data["id"] = 4003
        mock_recommendation_data["is_deleted"] = False
        create_message = create_recommendation_created_message(mock_recommendation_data, create_correlation_id)
        recommendation_consumer._process_activity_recommendation_message(create_message)
        
        print(f"\nCreated initial recommendation ID: {mock_recommendation_data['id']}")
        
        # Verify recommendation exists and is not deleted
        recommendation_before = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        assert recommendation_before.IsDeleted == "0"
        print(f"Recommendation before delete - IsDeleted: {recommendation_before.IsDeleted}")
        
        # Delete the recommendation
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_recommendation_deleted_message(
            mock_recommendation_data["id"],
            mock_recommendation_data,
            delete_correlation_id
        )
        
        print(f"Processing ACTIVITY_RECOMMENDATION_DELETED message: {delete_correlation_id}")
        
        # Process delete message
        result = recommendation_consumer._process_activity_recommendation_message(delete_message)
        
        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify REF_ACTIVITY_RECOMMENDATION record soft-deleted
        ref_recommendation = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        
        integration_db.refresh(ref_recommendation)
        
        assert ref_recommendation is not None
        assert ref_recommendation.IsDeleted == "1"
        
        print(f"DONE: Soft-deleted REF_ACTIVITY_RECOMMENDATION ID: {ref_recommendation.CentreActivityRecommendationID}")
        print(f"  IsDeleted: {ref_recommendation.IsDeleted}")
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is not None
        assert processed_event.event_type == "ACTIVITY_RECOMMENDATION_DELETED"
        assert processed_event.aggregate_id == str(mock_recommendation_data["id"])
        
        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
    
    def test_delete_nonexistent_recommendation_succeeds_gracefully(self, integration_db, recommendation_consumer, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_DELETED message for non-existent recommendation
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)
        
        Goal: Verify that deletes for non-existent recommendations don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        
        non_existent_data = {
            "id": 99999,
            "patient_id": 99999,
            "centre_activity_id": 999,
            "doctor_id": "DOC-999",
            "doctor_recommendation": "1",
            "doctor_remarks": "Test",
            "is_deleted": False
        }
        
        delete_message = create_recommendation_deleted_message(
            99999,
            non_existent_data,
            correlation_id
        )
        
        print(f"\nProcessing DELETE for non-existent recommendation 99999")
        
        # Process the message
        result = recommendation_consumer._process_activity_recommendation_message(delete_message)
        
        # Should succeed gracefully
        assert result == MessageProcessingResult.SUCCESS
        
        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()
        
        assert processed_event is not None
        
        print(f"DONE: Non-existent recommendation deletion handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")
    
    def test_duplicate_delete_message_is_idempotent(self, integration_db, recommendation_consumer, mock_recommendation_data, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_DELETED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and recommendation stays deleted
        
        Goal: Verify idempotency for delete messages
        """
        # Create initial recommendation
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_recommendation_created_message(mock_recommendation_data, create_correlation_id)
        recommendation_consumer._process_activity_recommendation_message(create_message)
        
        print(f"\nCreated initial recommendation ID: {mock_recommendation_data['id']}")
        
        # Delete the recommendation
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_recommendation_deleted_message(
            mock_recommendation_data["id"],
            mock_recommendation_data,
            delete_correlation_id
        )
        
        print(f"Processing initial ACTIVITY_RECOMMENDATION_DELETED message: {delete_correlation_id}")
        
        # Process first time
        result1 = recommendation_consumer._process_activity_recommendation_message(delete_message)
        assert result1 == MessageProcessingResult.SUCCESS
        
        # Verify deleted
        deleted_recommendation = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        assert deleted_recommendation.IsDeleted == "1"
        
        print(f"Recommendation soft-deleted: IsDeleted = {deleted_recommendation.IsDeleted}")
        
        # Process duplicate message
        print(f"Processing duplicate ACTIVITY_RECOMMENDATION_DELETED message: {delete_correlation_id}")
        result2 = recommendation_consumer._process_activity_recommendation_message(delete_message)
        
        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE
        
        # Verify still deleted
        still_deleted = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        assert still_deleted.IsDeleted == "1"
        
        print(f"DONE: Duplicate delete message handled correctly")
        print(f"Recommendation remains deleted: IsDeleted = {still_deleted.IsDeleted}")
    
    def test_delete_with_database_error_returns_retryable(self, integration_db, recommendation_consumer, mock_recommendation_data, monkeypatch, setup_test_data):
        """
        GIVEN: ACTIVITY_RECOMMENDATION_DELETED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued
        
        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial recommendation
        mock_recommendation_data["id"] = 4005
        mock_recommendation_data["is_deleted"] = False
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_recommendation_created_message(mock_recommendation_data, create_correlation_id)
        recommendation_consumer._process_activity_recommendation_message(create_message)
        
        print(f"\nCreated initial recommendation ID: {mock_recommendation_data['id']}")
        
        # Delete message
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_recommendation_deleted_message(
            mock_recommendation_data["id"],
            mock_recommendation_data,
            delete_correlation_id
        )
        
        print(f"Simulating database error for DELETE: {delete_correlation_id}")
        
        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError
        
        def mock_delete_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)
        
        monkeypatch.setattr(recommendation_consumer, "delete_ref_activity_recommendation", mock_delete_failure)
        
        # Process the message
        result = recommendation_consumer._process_activity_recommendation_message(delete_message)
        
        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE
        
        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()
        
        assert processed_event is None
        
        # Verify recommendation was NOT deleted (operation failed before completion)
        recommendation_check = integration_db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == mock_recommendation_data["id"]
        ).first()
        assert recommendation_check.IsDeleted == "0"
        
        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")
        print(f"Recommendation remains active (IsDeleted=0) - will be deleted on retry")