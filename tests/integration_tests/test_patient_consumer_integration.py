"""
Integration tests for Scheduler Service Patient Consumer
Tests the flow: RabbitMQ Message → Patient Consumer → REF_PATIENT table update → PROCESSED_EVENTS tracking

SQL Commands to clear DB:
DELETE FROM [PROCESSED_EVENTS];
DELETE FROM [REF_PATIENT];
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict

import pytest

from messaging.patient_consumer import PatientConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
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

@pytest.fixture
def patient_consumer():
    """
    Fixture for PatientConsumer instance.
    """
    consumer = PatientConsumer()
    yield consumer
    # Cleanup
    if consumer.client:
        consumer.client.close()

@pytest.fixture
def mock_patient_data():
    """
    Mock patient data matching the Patient Service model
    """
    return {
        'id': 123,
        'name': 'John Doe',
        'nric': 'S1234567A',
        'address': "Test Address",
        'tempAddress': "Test Temp Address",
        'homeNo': 'Test Home No',
        'handphoneNo': 'Test Hand Phone No',
        'gender': 'M',
        'dateOfBirth': datetime(1920, 1, 1),
        'isApproved': '1',
        'preferredName': 'Test Preferred Name',
        'preferredLanguageId': 2,
        'updateBit': '1',
        'autoGame': '0',
        'startDate': '2024-01-01T00:00:00',
        'endDate': '2024-12-31T00:00:00',
        'isActive': '1',
        'isRespiteCare': '0',
        'privacyLevel': '0',
        'terminationReason': 'Test Termination Reason',
        'inActiveReason': 'Test Inactive Reason',
        'inActiveDate': datetime(2020, 1, 1),
        'profilePicture': 'Test Profile Picture',
        'createdDate': datetime(2020, 1, 1),
        'modifiedDate': datetime(2020, 1, 1),
        'CreatedById': 'test-user-1',
        'ModifiedById': 'test-user-1',
        'isDeleted': '0'
    }

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

        # Delete all ref patients
        integration_db.query(RefPatient).filter(
            RefPatient.CreatedById == 'test-user-1'
        ).delete()
        integration_db.commit()

        print("\n[CLEANUP] Test data cleared successfully")
    except Exception as e:
        integration_db.rollback()
        print(f"\n[CLEANUP] Warning: Failed to cleanup test data: {str(e)}")


# ===== Helper Functions =====

def create_patient_created_message(patient_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_CREATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()

    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "patient-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "PATIENT_CREATED",
            "patient_id": patient_data["id"],
            "patient_data": patient_data,
            "created_by": patient_data.get("CreatedById", "test-user-1"),
            "created_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_patient_updated_message(patient_id: int, old_data: Dict[str, Any],
                                    new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_UPDATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()

    changes = {}
    for key in new_data:
        if key in old_data and old_data[key] != new_data[key]:
            changes[key] = {"old": old_data[key], "new": new_data[key]}

    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "patient-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "PATIENT_UPDATED",
            "patient_id": patient_id,
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("ModifiedById", "test-user-1"),
            "modified_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_patient_deleted_message(patient_id: int, patient_data: Dict[str, Any],
                                    correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_DELETED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()

    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "patient-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "PATIENT_DELETED",
            "patient_id": patient_id,
            "patient_data": patient_data,
            "deleted_by": "test-user",
            "deleted_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }

# ===== Create Patient Tests =====

class TestConsumerPatientCreate:
    """Test consumer processing of PATIENT_CREATED events"""

    def test_create_patient_processes_message_successfully(self, integration_db, patient_consumer,
                                                            mock_patient_data):
        """
        GIVEN: PATIENT_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT record is created and PROCESSED_EVENTS record exists

        Goal: Verify that consuming an PATIENT_CREATED message creates the patient in REF_PATIENT table
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_patient_created_message(mock_patient_data, correlation_id)

        print(f"\nProcessing PATIENT_CREATED message with correlation_id: {correlation_id}")

        # Process the message
        result = patient_consumer._process_patient_message(message)

        print(f"Processing result: {result}")

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT record created
        ref_patient = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()

        assert ref_patient is not None
        assert ref_patient.Name == mock_patient_data["name"]
        assert ref_patient.PreferredName == mock_patient_data["preferredName"]
        assert ref_patient.IsDeleted == "0"

        print(f"DONE: Created REF_PATIENT ID: {ref_patient.PatientID}")
        print(f"  Name: {ref_patient.Name}")
        print(f"  IsDeleted: {ref_patient.IsDeleted}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_CREATED"
        assert processed_event.aggregate_id == str(mock_patient_data["id"])
        assert json.loads(processed_event.operation_result)["status"] == "success"

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
        print(f"  Event Type: {processed_event.event_type}")
        print(f"  Status: {json.loads(processed_event.operation_result)["status"]}")

    def test_duplicate_create_message_is_idempotent(self, integration_db, patient_consumer, mock_patient_data):
        """
        GIVEN: PATIENT_CREATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and no additional records created

        Goal: Verify idempotency - duplicate messages don't create duplicate records (Checks for MessageProcessingResult.DUPLICATE)
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_patient_created_message(mock_patient_data, correlation_id)

        print(f"\nProcessing initial PATIENT_CREATED message: {correlation_id}")

        # Process first time
        result1 = patient_consumer._process_patient_message(message)
        assert result1 == MessageProcessingResult.SUCCESS

        initial_patient_count = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).count()
        initial_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()

        print(f"Initial counts - Patients: {initial_patient_count}, Processed Events: {initial_processed_count}")

        # Process duplicate message
        print(f"Processing duplicate PATIENT_CREATED message: {correlation_id}")
        result2 = patient_consumer._process_patient_message(message)

        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE

        # Verify no additional records created
        final_patient_count = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).count()
        final_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()

        assert final_patient_count == initial_patient_count
        assert final_processed_count == initial_processed_count

        print(f"DONE: Duplicate message handled correctly - no new records created")
        print(f"Final counts - Patients: {final_patient_count}, Processed Events: {final_processed_count}")

    def test_create_with_invalid_data_fails_permanently(self, integration_db, patient_consumer):
        """
        GIVEN: PATIENT_CREATED message with invalid/missing data
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT and no records created

        Goal: Verify that invalid messages are rejected permanently (Checks for MessageProcessingResult.FAILED_PERMANENT)
        """
        correlation_id = str(uuid.uuid4()).upper()

        # Create message with missing required fields
        invalid_message = {
            "timestamp": datetime.now().isoformat(),
            "source_service": "patient-service",
            "data": {
                "correlation_id": correlation_id,
                "event_type": "PATIENT_CREATED",
                # Missing patient_id and patient_data
            }
        }

        print(f"\nProcessing invalid PATIENT_CREATED message: {correlation_id}")

        # Process the message
        result = patient_consumer._process_patient_message(invalid_message)

        # Should fail permanently
        assert result == MessageProcessingResult.FAILED_PERMANENT

        # Verify no records created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is None

        print(f"DONE: Invalid message rejected permanently - no records created")

    def test_create_with_mapping_failure_fails_permanently(self, integration_db, patient_consumer, mock_patient_data,
                                                           monkeypatch):
        """
        GIVEN: PATIENT_CREATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)

        Goal: Verify that mapping errors are treated as permanent failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_patient_created_message(mock_patient_data, correlation_id)

        print(f"\nProcessing CREATE message with mapping error: {correlation_id}")

        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(patient_consumer, "map_patient_create", lambda x: None)

        # Process the message
        result = patient_consumer._process_patient_message(message)

        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT

        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")

    def test_create_with_database_error_returns_retryable(self, integration_db, patient_consumer, mock_patient_data,
                                                          monkeypatch):
        """
        GIVEN: PATIENT_CREATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued

        Goal: Verify that temporary database errors trigger retry behavior
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_patient_created_message(mock_patient_data, correlation_id)

        print(f"\nSimulating database error for CREATE: {correlation_id}")

        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError

        def mock_create_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)

        monkeypatch.setattr(patient_consumer, "create_ref_patient", mock_create_failure)

        # Process the message
        result = patient_consumer._process_patient_message(message)

        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE

        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is None

        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Update Patient Tests =====

class TestConsumerPatientUpdate:
    """Test consumer processing of PATIENT_UPDATED events"""

    def test_update_patient_processes_message_successfully(self, integration_db, patient_consumer,
                                                            mock_patient_data):
        """
        GIVEN: Existing REF_PATIENT record and PATIENT_UPDATED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT record is updated and PROCESSED_EVENTS record exists

        Goal: Verify that consuming an PATIENT_UPDATED message updates the patient in REF_PATIENT table
        """
        # First create the patient
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_created_message(mock_patient_data, create_correlation_id)
        patient_consumer._process_patient_message(create_message)

        print(f"\nCreated initial patient ID: {mock_patient_data['id']}")

        # Clear processed events for clean test
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == create_correlation_id
        ).delete()
        integration_db.commit()

        # Update the patient
        updated_data = mock_patient_data.copy()
        updated_data["name"] = "Howard"
        updated_data["isActive"] = "0"
        updated_data["modifiedDate"] = datetime.now().isoformat()

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_patient_updated_message(
            mock_patient_data["id"],
            mock_patient_data,
            updated_data,
            update_correlation_id
        )

        print(f"Processing PATIENT_UPDATED message: {update_correlation_id}")

        # Process update message
        result = patient_consumer._process_patient_message(update_message)

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT record updated
        ref_patient = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()

        assert ref_patient is not None
        assert ref_patient.Name == "Howard"
        assert ref_patient.IsActive == "0"
        assert ref_patient.IsDeleted == "0"

        print(f"DONE: Updated REF_PATIENT ID: {ref_patient.PatientID}")
        print(f"  New Name: {ref_patient.Name}")
        print(f"  New Active Status: {ref_patient.IsActive}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_UPDATED"
        assert processed_event.aggregate_id == str(mock_patient_data["id"])

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")

    def test_update_nonexistent_patient_succeeds_gracefully(self, integration_db, patient_consumer, mock_patient_data):
        """
        GIVEN: PATIENT_UPDATED message for non-existent patient
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)

        Goal: Verify that updates for non-existent patients don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()

        non_existent_data = {**mock_patient_data, "id": 99999, "name": "Non-existent"}

        update_message = create_patient_updated_message(
            99999,
            non_existent_data,
            non_existent_data,
            correlation_id
        )

        print(f"\nProcessing UPDATE for non-existent patient 99999")

        # Process the message
        result = patient_consumer._process_patient_message(update_message)

        # Should succeed gracefully (no crash/retry)
        assert result == MessageProcessingResult.SUCCESS

        # Verify PROCESSED_EVENTS record created (for idempotency tracking)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None

        print(f"DONE: Non-existent patient update handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")

    def test_duplicate_update_message_is_idempotent(self, integration_db, patient_consumer, mock_patient_data):
        """
        GIVEN: PATIENT_UPDATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and patient not updated again

        Goal: Verify idempotency for update messages
        """
        # Create initial patient
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_created_message(mock_patient_data, create_correlation_id)
        patient_consumer._process_patient_message(create_message)

        print(f"\nCreated initial patient ID: {mock_patient_data['id']}")

        # Update the patient
        updated_data = mock_patient_data.copy()
        updated_data["name"] = "New Name"
        updated_data["modifiedDate"] = datetime.now().isoformat()

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_patient_updated_message(
            mock_patient_data["id"],
            mock_patient_data,
            updated_data,
            update_correlation_id
        )

        print(f"Processing initial PATIENT_UPDATED message: {update_correlation_id}")

        # Process first time
        result1 = patient_consumer._process_patient_message(update_message)
        assert result1 == MessageProcessingResult.SUCCESS

        # Get the updated timestamp
        first_update = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()
        first_updated_datetime = first_update.UpdatedDateTime

        print(f"First update completed at: {first_updated_datetime}")

        # Process duplicate message
        print(f"Processing duplicate PATIENT_UPDATED message: {update_correlation_id}")
        result2 = patient_consumer._process_patient_message(update_message)

        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE

        # Verify UpdatedDateTime hasn't changed
        second_check = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()

        assert second_check.UpdatedDateTime == first_updated_datetime

        print(f"DONE: Duplicate update message handled correctly")
        print(f"Timestamp unchanged: {second_check.UpdatedDateTime}")

    def test_update_with_mapping_failure_fails_permanently(self, integration_db, patient_consumer, mock_patient_data,
                                                           monkeypatch):
        """
        GIVEN: PATIENT_UPDATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)

        Goal: Verify that mapping errors are treated as permanent failures
        """
        # Create initial patient
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_created_message(mock_patient_data, create_correlation_id)
        patient_consumer._process_patient_message(create_message)

        print(f"\nCreated initial patient ID: {mock_patient_data['id']}")

        # Update message
        updated_data = mock_patient_data.copy()
        updated_data["title"] = "Should Fail Mapping"

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_patient_updated_message(
            mock_patient_data["id"],
            mock_patient_data,
            updated_data,
            update_correlation_id
        )

        print(f"Processing UPDATE message with mapping error: {update_correlation_id}")

        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(patient_consumer, "map_patient_update", lambda x: None)

        # Process the message
        result = patient_consumer._process_patient_message(update_message)

        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT

        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")

    def test_update_with_database_error_returns_retryable(self, integration_db, patient_consumer, mock_patient_data,
                                                          monkeypatch):
        """
        GIVEN: PATIENT_UPDATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued

        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial patient
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_created_message(mock_patient_data, create_correlation_id)
        patient_consumer._process_patient_message(create_message)

        print(f"\nCreated initial patient ID: {mock_patient_data['id']}")

        # Update message
        updated_data = mock_patient_data.copy()
        updated_data["title"] = "Should Trigger DB Error"
        updated_data["modified_date"] = datetime.now().isoformat()

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_patient_updated_message(
            mock_patient_data["id"],
            mock_patient_data,
            updated_data,
            update_correlation_id
        )

        print(f"Simulating database error for UPDATE: {update_correlation_id}")

        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError

        def mock_update_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)

        monkeypatch.setattr(patient_consumer, "update_ref_patient", mock_update_failure)

        # Process the message
        result = patient_consumer._process_patient_message(update_message)

        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE

        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()

        assert processed_event is None

        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")


# ===== Delete Patient Tests =====

class TestConsumerPatientDelete:
    """Test consumer processing of PATIENT_DELETED events"""

    def test_delete_patient_processes_message_successfully(self, integration_db, patient_consumer,
                                                            mock_patient_data):
        """
        GIVEN: Existing REF_PATIENT record and PATIENT_DELETED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT record is soft-deleted and PROCESSED_EVENTS record exists

        Goal: Verify that consuming an PATIENT_DELETED message soft-deletes the patient
        """
        # First create the patient
        create_correlation_id = str(uuid.uuid4()).upper()
        mock_patient_data["id"] = 1003  # Ensure unique ID for this test"
        mock_patient_data["isDeleted"] = False
        mock_patient_data["name"] = "Patient to be Deleted"
        mock_patient_data["PrescriptionRemarks"] = "This patient will be deleted in the test"
        create_message = create_patient_created_message(mock_patient_data, create_correlation_id)
        patient_consumer._process_patient_message(create_message)

        print(f"\nCreated initial patient ID: {mock_patient_data['id']}")

        # Verify patient exists and is not deleted
        patient_before = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()
        assert patient_before.IsDeleted == "0"
        print(f"Patient before delete - IsDeleted: {patient_before.IsDeleted}")

        # Delete the patient
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_patient_deleted_message(
            mock_patient_data["id"],
            mock_patient_data,
            delete_correlation_id
        )

        print(f"Processing PATIENT_DELETED message: {delete_correlation_id}")

        # Process delete message
        result = patient_consumer._process_patient_message(delete_message)

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT record soft-deleted
        ref_patient = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()

        integration_db.refresh(ref_patient)

        assert ref_patient is not None
        assert ref_patient.IsDeleted == "1"

        print(f"DONE: Soft-deleted REF_PATIENT ID: {ref_patient.PatientID}")
        print(f"  IsDeleted: {ref_patient.IsDeleted}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_DELETED"
        assert processed_event.aggregate_id == str(mock_patient_data["id"])

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")

    def test_delete_nonexistent_patient_succeeds_gracefully(self, integration_db, patient_consumer, mock_patient_data):
        """
        GIVEN: PATIENT_DELETED message for non-existent patient
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)

        Goal: Verify that deletes for non-existent patients don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()

        non_existent_data = {**mock_patient_data, "id": 99999, "name": "Non-existent"}

        delete_message = create_patient_deleted_message(
            99999,
            non_existent_data,
            correlation_id
        )

        print(f"\nProcessing DELETE for non-existent patient 99999")

        # Process the message
        result = patient_consumer._process_patient_message(delete_message)

        # Should succeed gracefully
        assert result == MessageProcessingResult.SUCCESS

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None

        print(f"DONE: Non-existent patient deletion handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")

    def test_duplicate_delete_message_is_idempotent(self, integration_db, patient_consumer, mock_patient_data):
        """
        GIVEN: PATIENT_DELETED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and patient stays deleted

        Goal: Verify idempotency for delete messages
        """
        # Create initial patient
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_created_message(mock_patient_data, create_correlation_id)
        patient_consumer._process_patient_message(create_message)

        print(f"\nCreated initial patient ID: {mock_patient_data['id']}")

        # Delete the patient
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_patient_deleted_message(
            mock_patient_data["id"],
            mock_patient_data,
            delete_correlation_id
        )

        print(f"Processing initial PATIENT_DELETED message: {delete_correlation_id}")

        # Process first time
        result1 = patient_consumer._process_patient_message(delete_message)
        assert result1 == MessageProcessingResult.SUCCESS

        # Verify deleted
        deleted_patient = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()
        assert deleted_patient.IsDeleted == "1"

        print(f"Patient soft-deleted: IsDeleted = {deleted_patient.IsDeleted}")

        # Process duplicate message
        print(f"Processing duplicate PATIENT_DELETED message: {delete_correlation_id}")
        result2 = patient_consumer._process_patient_message(delete_message)

        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE

        # Verify still deleted
        still_deleted = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()
        assert still_deleted.IsDeleted == "1"

        print(f"DONE: Duplicate delete message handled correctly")
        print(f"Patient remains deleted: IsDeleted = {still_deleted.IsDeleted}")

    def test_delete_with_database_error_returns_retryable(self, integration_db, patient_consumer, mock_patient_data,
                                                          monkeypatch):
        """
        GIVEN: PATIENT_DELETED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be requeued

        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial patient
        mock_patient_data["id"] = 1005  # Ensure unique ID for this test"
        mock_patient_data["isDeleted"] = "0"
        mock_patient_data["name"] = "Patient to be Deleted"
        mock_patient_data["PrescriptionRemarks"] = "This Patient will be deleted in the test"
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_created_message(mock_patient_data, create_correlation_id)
        patient_consumer._process_patient_message(create_message)

        print(f"\nCreated initial patient ID: {mock_patient_data['id']}")

        # Delete message
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_patient_deleted_message(
            mock_patient_data["id"],
            mock_patient_data,
            delete_correlation_id
        )

        print(f"Simulating database error for DELETE: {delete_correlation_id}")

        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError

        def mock_delete_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)

        monkeypatch.setattr(patient_consumer, "delete_ref_patient", mock_delete_failure)

        # Process the message
        result = patient_consumer._process_patient_message(delete_message)

        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE

        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()

        assert processed_event is None

        # Verify patient was NOT deleted (operation failed before completion)
        patient_check = integration_db.query(RefPatient).filter(
            RefPatient.PatientID == mock_patient_data["id"]
        ).first()
        assert patient_check.IsDeleted == "0"

        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be requeued for retry")
        print(f"Patient remains active (IsDeleted=0) - will be deleted on retry")