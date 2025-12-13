"""
Integration tests for Scheduler Service Patient Medication Consumer
Tests the flow: RabbitMQ Message → Patient Medication Consumer → REF_PATIENT_MEDICATION table update → PROCESSED_EVENTS tracking

SQL Commands to clear DB:
DELETE FROM [PROCESSED_EVENTS];
DELETE FROM [REF_PATIENT_MEDICATION];
DELETE FROM [REF_PATIENT];
"""
import json
import uuid
from datetime import datetime
from typing import Any, Dict

import pytest

from messaging.patient_medication_consumer import PatientMedicationConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
from pear_schedule.models.ref_patient_medication_model import RefPatientMedication
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
def patient_medication_consumer():
    """
    Fixture for PatientMedicationConsumer instance.
    """
    consumer = PatientMedicationConsumer()
    yield consumer
    # Cleanup
    if consumer.client:
        consumer.client.close()

@pytest.fixture
def mock_patient_data():
    """
    Mock patient data matching the Patient Service model
    Added here as PatientMedication requires a Patient
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

@pytest.fixture
def mock_patient_medication_data():
    """
    Mock patient medication data matching the PatientMedication Service model
    Taken from PatientMedication schema
    """
    return {
        'Id': 12345,
        'IsDeleted': '0',
        'PatientId': 123,
        'PrescriptionListId': 1234,
        'AdministerTime': '1030, 1430',
        'Dosage': '2 tabs',
        'Instruction': 'Always leave at least 4 hours between doses',
        'StartDate': datetime(2020, 1, 1),
        'PrescriptionRemarks': 'Prescription Remarks',
        'CreatedDateTime': datetime(2020, 1, 1),
        'UpdatedDateTime': datetime(2020, 1, 2),
        'CreatedById': 'test-user-1',
        'ModifiedById': 'test-user-1'
    }

# Create a patient with the patient id of the medication
@pytest.fixture(autouse=True)
def existing_patient(integration_db, mock_patient_data):
    """
    Fixture that creates a patient in the database before the test runs.
    Returns the created patient object.
    """
    try:
        ref_patient = RefPatient(
            PatientID=mock_patient_data['id'],
            Name=mock_patient_data['name'],
            PreferredName=mock_patient_data['preferredName'],
            IsDeleted=mock_patient_data['isDeleted'],
            UpdateBit=mock_patient_data['updateBit'],
            StartDate=mock_patient_data['startDate'],
            EndDate=mock_patient_data['endDate'],
            IsActive=mock_patient_data['isActive'],
            CreatedDateTime=mock_patient_data['createdDate'],
            UpdatedDateTime=mock_patient_data['modifiedDate'],
            CreatedById=mock_patient_data['CreatedById'],
            ModifiedById=mock_patient_data['ModifiedById'],
        )
        integration_db.add(ref_patient)
        integration_db.commit()
        print(f"Successfully created patient {ref_patient.PatientID}")
        return ref_patient
    except Exception as e:
        print(f"[FIXTURE] ERROR creating patient: {str(e)}")
        integration_db.rollback()
        raise

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

        # Delete all ref patient medication
        integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.CreatedById == 'test-user-1'
        ).delete()
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

def create_patient_medication_created_message(medication_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_MEDICATION_CREATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()

    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "patient-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "PATIENT_MEDICATION_CREATED",
            "medication_id": medication_data["Id"],
            "patient_id": medication_data["PatientId"],
            "medication_data": medication_data,
            "created_by": medication_data.get("CreatedById", "test-user-1"),
            "timestamp": datetime.now().isoformat()
        }
    }

def create_patient_medication_updated_message(medication_id: int, old_data: Dict[str, Any],
                                    new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_MEDICATION_UPDATED message"""
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
            "event_type": "PATIENT_MEDICATION_UPDATED",
            "medication_id": medication_id,
            "patient_id": old_data["PatientId"],
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("ModifiedById", "test-user-1"),
            "timestamp": datetime.now().isoformat()
        }
    }

def create_patient_medication_deleted_message(medication_id: int, medication_data: Dict[str, Any],
                                    correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_MEDICATION_DELETED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()

    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "patient-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "PATIENT_MEDICATION_DELETED",
            "medication_id": medication_id,
            "patient_id": medication_data["PatientId"],
            "medication_data": medication_data,
            "deleted_by": "test-user",
            "timestamp": datetime.now().isoformat()
        }
    }

# ===== Create PatientMedication Tests =====

class TestConsumerPatientMedicationCreate:
    """Test consumer processing of PATIENT_MEDICATION_CREATED events"""

    def test_create_patient_medication_processes_message_successfully(
            self,
            integration_db,
            patient_medication_consumer,
            mock_patient_medication_data
    ):
        """
        GIVEN: PATIENT_MEDICATION_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT_MEDICATION record is created and PROCESSED_EVENTS record exists

        Goal: Verify that consuming an PATIENT_MEDICATION_CREATED message creates the medication in REF_PATIENT_MEDICATION table
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_patient_medication_created_message(mock_patient_medication_data, correlation_id)

        print(f"\nProcessing PATIENT_MEDICATION_CREATED message with correlation_id: {correlation_id}")

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(message)

        print(f"Processing result: {result}")

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT_MEDICATION record created
        ref_patient_medication = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()

        assert ref_patient_medication is not None
        assert ref_patient_medication.Instruction == mock_patient_medication_data["Instruction"]
        assert ref_patient_medication.PrescriptionRemarks == mock_patient_medication_data["PrescriptionRemarks"]
        assert ref_patient_medication.IsDeleted == "0"

        print(f"DONE: Created REF_PATIENT_MEDICATION ID: {ref_patient_medication.MedicationID}")
        print(f"  Instruction: {ref_patient_medication.Instruction}")
        print(f"  IsDeleted: {ref_patient_medication.IsDeleted}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_MEDICATION_CREATED"
        assert processed_event.aggregate_id == str(mock_patient_medication_data["Id"])
        assert json.loads(processed_event.operation_result)['status'] == "success"

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
        print(f"  Event Type: {processed_event.event_type}")
        print(f"  Status: {json.loads(processed_event.operation_result)['status']}")

    def test_duplicate_create_message_is_idempotent(self, integration_db, patient_medication_consumer, mock_patient_medication_data):
        """
        GIVEN: PATIENT_MEDICATION_CREATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and no additional records created

        Goal: Verify idempotency - duplicate messages don't create duplicate records (Checks for MessageProcessingResult.DUPLICATE)
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_patient_medication_created_message(mock_patient_medication_data, correlation_id)

        print(f"\nProcessing initial PATIENT_MEDICATION_CREATED message: {correlation_id}")

        # Process first time
        result1 = patient_medication_consumer._process_patient_medication_message(message)
        assert result1 == MessageProcessingResult.SUCCESS

        initial_patient_medication_count = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).count()
        initial_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()

        print(f"Initial counts - Patient Medications: {initial_patient_medication_count}, Processed Events: {initial_processed_count}")

        # Process duplicate message
        print(f"Processing duplicate PATIENT_MEDICATION_CREATED message: {correlation_id}")
        result2 = patient_medication_consumer._process_patient_medication_message(message)

        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE

        # Verify no additional records created
        final_patient_medication_count = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).count()
        final_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()

        assert final_patient_medication_count == initial_patient_medication_count
        assert final_processed_count == initial_processed_count

        print(f"DONE: Duplicate message handled correctly - no new records created")
        print(f"Final counts - Patients: {final_patient_medication_count}, Processed Events: {final_processed_count}")

    def test_create_with_invalid_data_fails_permanently(self, integration_db, patient_medication_consumer):
        """
        GIVEN: PATIENT_MEDICATION_CREATED message with invalid/missing data
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
                "event_type": "PATIENT_MEDICATION_CREATED",
                # Missing medication_id and medication_data
            }
        }

        print(f"\nProcessing invalid PATIENT_MEDICATION_CREATED message: {correlation_id}")

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(invalid_message)

        # Should fail permanently
        assert result == MessageProcessingResult.FAILED_PERMANENT

        # Verify no records created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is None

        print(f"DONE: Invalid message rejected permanently - no records created")

    def test_create_with_mapping_failure_fails_permanently(self, integration_db, patient_medication_consumer, mock_patient_medication_data,
                                                           monkeypatch):
        """
        GIVEN: PATIENT_MEDICATION_CREATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)

        Goal: Verify that mapping errors are treated as permanent failures
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_patient_medication_created_message(mock_patient_medication_data, correlation_id)

        print(f"\nProcessing CREATE message with mapping error: {correlation_id}")

        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(patient_medication_consumer, "map_patient_medication_create", lambda x: None)

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(message)

        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT

        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")

    def test_create_with_database_error_returns_retryable(self, integration_db, patient_medication_consumer, mock_patient_medication_data,
                                                          monkeypatch):
        """
        GIVEN: PATIENT_MEDICATION_CREATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be re-queued

        Goal: Verify that temporary database errors trigger retry behavior
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_patient_medication_created_message(mock_patient_medication_data, correlation_id)

        print(f"\nSimulating database error for CREATE: {correlation_id}")

        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError

        def mock_create_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)

        monkeypatch.setattr(patient_medication_consumer, "create_ref_patient_medication", mock_create_failure)

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(message)

        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE

        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is None

        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be re-queued for retry")

# ===== Update PatientMedication Tests =====

class TestConsumerPatientMedicationUpdate:
    """Test consumer processing of PATIENT_MEDICATION_UPDATED events"""

    def test_update_patient_medication_processes_message_successfully(self, integration_db, patient_medication_consumer,
                                                            mock_patient_medication_data):
        """
        GIVEN: Existing REF_PATIENT_MEDICATION record and PATIENT_MEDICATION_UPDATED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT_MEDICATION record is updated and PROCESSED_EVENTS record exists

        Goal: Verify that consuming an PATIENT_MEDICATION_UPDATED message updates the patient in REF_PATIENT_MEDICATION table
        """
        # First create the patient medication
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_medication_created_message(mock_patient_medication_data, create_correlation_id)
        patient_medication_consumer._process_patient_medication_message(create_message)

        print(f"\nCreated initial patient medication ID: {mock_patient_medication_data['Id']}")

        # Clear processed events for clean test
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == create_correlation_id
        ).delete()
        integration_db.commit()

        # Update the patient
        updated_data = mock_patient_medication_data.copy()
        updated_data["Instruction"] = "Take every 2 hours"
        updated_data["Dosage"] = "5 tabs"
        updated_data["UpdatedDateTime"] = datetime.now().isoformat()

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_patient_medication_updated_message(
            mock_patient_medication_data["Id"],
            mock_patient_medication_data,
            updated_data,
            update_correlation_id
        )

        print(f"Processing PATIENT_MEDICATION_UPDATED message: {update_correlation_id}")

        # Process update message
        result = patient_medication_consumer._process_patient_medication_message(update_message)

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT_MEDICATION record updated
        ref_patient_medication = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()

        assert ref_patient_medication is not None
        assert ref_patient_medication.Instruction == "Take every 2 hours"
        assert ref_patient_medication.Dosage == "5 tabs"
        assert ref_patient_medication.IsDeleted == "0"

        print(f"DONE: Updated REF_PATIENT_MEDICATION ID: {ref_patient_medication.MedicationID}")
        print(f"  New Instruction: {ref_patient_medication.Instruction}")
        print(f"  New Dosage: {ref_patient_medication.Dosage}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_MEDICATION_UPDATED"
        assert processed_event.aggregate_id == str(mock_patient_medication_data["Id"])

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")

    def test_update_nonexistent_patient_medication_succeeds_gracefully(self, integration_db, patient_medication_consumer, mock_patient_medication_data):
        """
        GIVEN: PATIENT_MEDICATION_UPDATED message for non-existent medication ID
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)

        Goal: Verify that updates for non-existent medications don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()

        non_existent_data = {**mock_patient_medication_data, "Id": 99999, "Dosage": "Non-existent"}

        update_message = create_patient_medication_updated_message(
            99999,
            non_existent_data,
            non_existent_data,
            correlation_id
        )

        print(f"\nProcessing UPDATE for non-existent medication ID 99999")

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(update_message)

        # Should succeed gracefully (no crash/retry)
        assert result == MessageProcessingResult.SUCCESS

        # Verify PROCESSED_EVENTS record created (for idempotency tracking)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None

        print(f"DONE: Non-existent medication update handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")

    def test_duplicate_update_message_is_idempotent(self, integration_db, patient_medication_consumer, mock_patient_medication_data):
        """
        GIVEN: PATIENT_MEDICATION_UPDATE message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and medication not updated again

        Goal: Verify idempotency for update messages
        """
        # Create initial patient
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_medication_created_message(mock_patient_medication_data, create_correlation_id)
        patient_medication_consumer._process_patient_medication_message(create_message)

        print(f"\nCreated initial medication ID: {mock_patient_medication_data['Id']}")

        # Update the medication
        updated_data = mock_patient_medication_data.copy()
        updated_data["Dosage"] = "New Dosage"
        updated_data["UpdatedDateTime"] = datetime.now().isoformat()

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_patient_medication_updated_message(
            mock_patient_medication_data["Id"],
            mock_patient_medication_data,
            updated_data,
            update_correlation_id
        )

        print(f"Processing initial PATIENT_MEDICATION_UPDATED message: {update_correlation_id}")

        # Process first time
        result1 = patient_medication_consumer._process_patient_medication_message(update_message)
        assert result1 == MessageProcessingResult.SUCCESS

        # Get the updated timestamp
        first_update = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()
        first_updated_datetime = first_update.UpdatedDateTime

        print(f"First update completed at: {first_updated_datetime}")

        # Process duplicate message
        print(f"Processing duplicate PATIENT_MEDICATION_UPDATED message: {update_correlation_id}")
        result2 = patient_medication_consumer._process_patient_medication_message(update_message)

        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE

        # Verify UpdatedDateTime hasn't changed
        second_check = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()

        assert second_check.UpdatedDateTime == first_updated_datetime

        print(f"DONE: Duplicate update message handled correctly")
        print(f"Timestamp unchanged: {second_check.UpdatedDateTime}")

    def test_update_with_mapping_failure_fails_permanently(self, integration_db, patient_medication_consumer, mock_patient_medication_data,
                                                           monkeypatch):
        """
        GIVEN: PATIENT_MEDICATION_UPDATED message where data mapping fails
        WHEN: Consumer processes the message
        THEN: Returns FAILED_PERMANENT (bad data shouldn't be retried)

        Goal: Verify that mapping errors are treated as permanent failures
        """
        # Create initial patient
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_medication_created_message(mock_patient_medication_data, create_correlation_id)
        patient_medication_consumer._process_patient_medication_message(create_message)

        print(f"\nCreated initial medication ID: {mock_patient_medication_data['Id']}")

        # Update message
        updated_data = mock_patient_medication_data.copy()
        updated_data["Dosage"] = "Failed Dosage"

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_patient_medication_updated_message(
            mock_patient_medication_data["Id"],
            mock_patient_medication_data,
            updated_data,
            update_correlation_id
        )

        print(f"Processing UPDATE message with mapping error: {update_correlation_id}")

        # Mock mapper to return None (mapping failure)
        monkeypatch.setattr(patient_medication_consumer, "map_patient_medication_update", lambda x: None)

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(update_message)

        # Should return FAILED_PERMANENT for mapping errors
        assert result == MessageProcessingResult.FAILED_PERMANENT

        print(f"DONE: Mapping error correctly returned FAILED_PERMANENT")

    def test_update_with_database_error_returns_retryable(self, integration_db, patient_medication_consumer, mock_patient_medication_data,
                                                          monkeypatch):
        """
        GIVEN: PATIENT_MEDICATION_UPDATED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be re-queued

        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial medication
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_medication_created_message(mock_patient_medication_data, create_correlation_id)
        patient_medication_consumer._process_patient_medication_message(create_message)

        print(f"\nCreated initial medication ID: {mock_patient_medication_data['Id']}")

        # Update message
        updated_data = mock_patient_medication_data.copy()
        updated_data["Dosage"] = "Should Trigger DB Dosage"
        updated_data["UpdatedDateTime"] = datetime.now().isoformat()

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_patient_medication_updated_message(
            mock_patient_medication_data["Id"],
            mock_patient_medication_data,
            updated_data,
            update_correlation_id
        )

        print(f"Simulating database error for UPDATE: {update_correlation_id}")

        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError

        def mock_update_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)

        monkeypatch.setattr(patient_medication_consumer, "update_ref_patient_medication", mock_update_failure)

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(update_message)

        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE

        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()

        assert processed_event is None

        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be re-queued for retry")

# ===== Delete Patient Medication Tests =====

class TestConsumerPatientMedicationDelete:
    """Test consumer processing of PATIENT_MEDICATION_DELETED events"""

    def test_delete_patient_medication_processes_message_successfully(self, integration_db, patient_medication_consumer,
                                                            mock_patient_medication_data):
        """
        GIVEN: Existing REF_PATIENT_MEDICATION record and PATIENT_MEDICATION_DELETED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT_MEDICATION record is soft-deleted and PROCESSED_EVENTS record exists

        Goal: Verify that consuming an PATIENT_MEDICATION_DELETED message soft-deletes the patient
        """
        # First create the medication
        create_correlation_id = str(uuid.uuid4()).upper()
        mock_patient_medication_data["Id"] = 1003  # Ensure unique ID for this test"
        mock_patient_medication_data["IsDeleted"] = "0"
        mock_patient_medication_data["Dosage"] = "Dosage to be Deleted"
        mock_patient_medication_data["Instruction"] = "This instruction is going to be deleted for this test"
        create_message = create_patient_medication_created_message(mock_patient_medication_data, create_correlation_id)
        patient_medication_consumer._process_patient_medication_message(create_message)

        print(f"\nCreated initial medication ID: {mock_patient_medication_data['Id']}")

        # Verify patient exists and is not deleted
        patient_before = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()
        assert patient_before.IsDeleted == "0"
        print(f"Patient before delete - IsDeleted: {patient_before.IsDeleted}")

        # Delete the patient
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_patient_medication_deleted_message(
            mock_patient_medication_data["Id"],
            mock_patient_medication_data,
            delete_correlation_id
        )

        print(f"Processing PATIENT_MEDICATION_DELETED message: {delete_correlation_id}")

        # Process delete message
        result = patient_medication_consumer._process_patient_medication_message(delete_message)

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT_MEDICATION record soft-deleted
        ref_patient_medication = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()

        integration_db.refresh(ref_patient_medication)

        assert ref_patient_medication is not None
        assert ref_patient_medication.IsDeleted == "1"

        print(f"DONE: Soft-deleted REF_PATIENT_MEDICATION ID: {ref_patient_medication.MedicationID}")
        print(f"  IsDeleted: {ref_patient_medication.IsDeleted}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_MEDICATION_DELETED"
        assert processed_event.aggregate_id == str(mock_patient_medication_data["Id"])

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")

    def test_delete_nonexistent_patient_succeeds_gracefully(self, integration_db, patient_medication_consumer, mock_patient_medication_data):
        """
        GIVEN: PATIENT_MEDICATION_DELETED message for non-existent medication
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)

        Goal: Verify that deletes for non-existent medication don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()

        non_existent_data = {**mock_patient_medication_data, "Id": 99999, "Dosage": "Non-existent"}

        delete_message = create_patient_medication_deleted_message(
            99999,
            non_existent_data,
            correlation_id
        )

        print(f"\nProcessing DELETE for non-existent medication ID 99999")

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(delete_message)

        # Should succeed gracefully
        assert result == MessageProcessingResult.SUCCESS

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None

        print(f"DONE: Non-existent medication deletion handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")

    def test_duplicate_delete_message_is_idempotent(self, integration_db, patient_medication_consumer, mock_patient_medication_data):
        """
        GIVEN: PATIENT_MEDICATION_DELETED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and patient stays deleted

        Goal: Verify idempotency for delete messages
        """
        # Create initial patient
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_medication_created_message(mock_patient_medication_data, create_correlation_id)
        patient_medication_consumer._process_patient_medication_message(create_message)

        print(f"\nCreated initial medication ID: {mock_patient_medication_data['Id']}")

        # Delete the patient
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_patient_medication_deleted_message(
            mock_patient_medication_data["Id"],
            mock_patient_medication_data,
            delete_correlation_id
        )

        print(f"Processing initial PATIENT_MEDICATION_DELETED message: {delete_correlation_id}")

        # Process first time
        result1 = patient_medication_consumer._process_patient_medication_message(delete_message)
        assert result1 == MessageProcessingResult.SUCCESS

        # Verify deleted
        deleted_patient = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()

        assert deleted_patient.IsDeleted == "1"

        print(f"Patient soft-deleted: IsDeleted = {deleted_patient.IsDeleted}")

        # Process duplicate message
        print(f"Processing duplicate PATIENT_MEDICATION_DELETED message: {delete_correlation_id}")
        result2 = patient_medication_consumer._process_patient_medication_message(delete_message)

        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE

        # Verify still deleted
        still_deleted = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()
        assert still_deleted.IsDeleted == "1"

        print(f"DONE: Duplicate delete message handled correctly")
        print(f"Patient remains deleted: IsDeleted = {still_deleted.IsDeleted}")

    def test_delete_with_database_error_returns_retryable(self, integration_db, patient_medication_consumer, mock_patient_medication_data,
                                                          monkeypatch):
        """
        GIVEN: PATIENT_MEDICATION_DELETED message and database error during processing
        WHEN: Consumer processes the message and database operation fails
        THEN: Returns FAILED_RETRYABLE and message can be re-queued

        Goal: Verify that temporary database errors trigger retry behavior
        """
        # Create initial patient
        mock_patient_medication_data["Id"] = 1005  # Ensure unique ID for this test"
        mock_patient_medication_data["IsDeleted"] = "0"
        mock_patient_medication_data["Dosage"] = "Dosage to be Deleted"
        mock_patient_medication_data["PrescriptionRemarks"] = "This Patient will be deleted in the test"
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_patient_medication_created_message(mock_patient_medication_data, create_correlation_id)
        patient_medication_consumer._process_patient_medication_message(create_message)

        print(f"\nCreated initial medication ID: {mock_patient_medication_data['Id']}")

        # Delete message
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_patient_medication_deleted_message(
            mock_patient_medication_data["Id"],
            mock_patient_medication_data,
            delete_correlation_id
        )

        print(f"Simulating database error for DELETE: {delete_correlation_id}")

        # Mock the CRUD operation to raise a database error
        from sqlalchemy.exc import OperationalError

        def mock_delete_failure(*args, **kwargs):
            raise OperationalError("Database connection lost", None, None)

        monkeypatch.setattr(patient_medication_consumer, "delete_ref_patient_medication", mock_delete_failure)

        # Process the message
        result = patient_medication_consumer._process_patient_medication_message(delete_message)

        # Should return FAILED_RETRYABLE for database errors
        assert result == MessageProcessingResult.FAILED_RETRYABLE

        # Verify no PROCESSED_EVENTS record created (so it can be retried)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()

        assert processed_event is None

        # Verify patient was NOT deleted (operation failed before completion)
        medication_check = integration_db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == mock_patient_medication_data["Id"]
        ).first()
        assert medication_check.IsDeleted == "0"

        print(f"DONE: Database error correctly returned FAILED_RETRYABLE")
        print(f"No PROCESSED_EVENT created - message can be re-queued for retry")
        print(f"Medication remains active (IsDeleted=0) - will be deleted on retry")
