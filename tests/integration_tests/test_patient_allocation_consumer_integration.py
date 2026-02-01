"""
Integration tests for Scheduler Service Patient Allocation Consumer
Tests the flow: Message → Patient Allocation Consumer → REF_PATIENT_ALLOCATION table update → PROCESSED_EVENTS tracking

SQL Commands to clear DB:
DELETE FROM [PROCESSED_EVENTS] WHERE event_type LIKE 'PATIENT_ALLOCATION%';
DELETE FROM [REF_PATIENT_ALLOCATION];
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict

import pytest

from messaging.patient_allocation_consumer import PatientAllocationConsumer
from pear_schedule.database import SessionLocal
from pear_schedule.models.processed_events_model import (
    MessageProcessingResult,
    ProcessedEvent,
)
from pear_schedule.models.ref_patient_allocation_model import RefPatientAllocation

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
def patient_allocation_consumer():
    """
    Fixture for PatientAllocationConsumer instance.
    """
    consumer = PatientAllocationConsumer()
    yield consumer
    # Cleanup
    if consumer.client:
        consumer.client.close()


@pytest.fixture
def mock_allocation_data():
    """
    Mock patient allocation data matching the Patient Service model
    """
    return {
        'id': 12345,
        'active': 'Y',
        'isDeleted': '0',
        'patientId': 100,
        'doctorId': 'DOC123',
        'gameTherapistId': 'GT456',
        'supervisorId': 'SUP789',
        'caregiverId': 'CG101',
        'tempDoctorId': None,
        'tempCaregiverId': None,
        'guardianId': 1,
        'guardian2Id': None,
        'createdDate': datetime(2024, 1, 1).isoformat(),
        'modifiedDate': datetime(2024, 1, 1).isoformat(),
        'CreatedById': 'test-user-1',
        'ModifiedById': 'test-user-1'
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
        # Delete all processed events for patient allocation
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.event_type.like('PATIENT_ALLOCATION%')
        ).delete(synchronize_session=False)
        integration_db.commit()

        # Delete all ref patient allocations created in tests
        integration_db.query(RefPatientAllocation).filter(
            RefPatientAllocation.created_by_id == 'test-user-1'
        ).delete(synchronize_session=False)
        integration_db.commit()

        print("\n[CLEANUP] Test data cleared successfully")
    except Exception as e:
        integration_db.rollback()
        print(f"\n[CLEANUP] Warning: Failed to cleanup test data: {str(e)}")


# ===== Helper Functions =====

def create_allocation_created_message(allocation_data: Dict[str, Any], 
                                     correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_ALLOCATION_CREATED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()

    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "patient-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "PATIENT_ALLOCATION_CREATED",
            "allocation_id": allocation_data["id"],
            "patient_id": allocation_data["patientId"],
            "allocation_data": allocation_data,
            "created_by": allocation_data.get("CreatedById", "test-user-1"),
            "created_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_allocation_updated_message(allocation_id: int, old_data: Dict[str, Any],
                                     new_data: Dict[str, Any], correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_ALLOCATION_UPDATED message"""
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
            "event_type": "PATIENT_ALLOCATION_UPDATED",
            "allocation_id": allocation_id,
            "patient_id": new_data["patientId"],
            "old_data": old_data,
            "new_data": new_data,
            "changes": changes,
            "modified_by": new_data.get("ModifiedById", "test-user-1"),
            "modified_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


def create_allocation_deleted_message(allocation_id: int, allocation_data: Dict[str, Any],
                                      correlation_id: str = None) -> Dict[str, Any]:
    """Helper to create PATIENT_ALLOCATION_DELETED message"""
    if not correlation_id:
        correlation_id = str(uuid.uuid4()).upper()

    return {
        "timestamp": datetime.now().isoformat(),
        "source_service": "patient-service",
        "data": {
            "correlation_id": correlation_id,
            "event_type": "PATIENT_ALLOCATION_DELETED",
            "allocation_id": allocation_id,
            "patient_id": allocation_data["patientId"],
            "allocation_data": allocation_data,
            "deleted_by": "test-user-1",
            "deleted_by_name": "Test User",
            "timestamp": datetime.now().isoformat()
        }
    }


# ===== Create Patient Allocation Tests =====

class TestConsumerPatientAllocationCreate:
    """Test consumer processing of PATIENT_ALLOCATION_CREATED events"""

    def test_create_allocation_processes_message_successfully(self, integration_db, 
                                                              patient_allocation_consumer,
                                                              mock_allocation_data):
        """
        GIVEN: PATIENT_ALLOCATION_CREATED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT_ALLOCATION record is created and PROCESSED_EVENTS record exists

        Goal: Verify that consuming a PATIENT_ALLOCATION_CREATED message creates the allocation
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_allocation_created_message(mock_allocation_data, correlation_id)

        print(f"\nProcessing PATIENT_ALLOCATION_CREATED message with correlation_id: {correlation_id}")

        # Process the message
        result = patient_allocation_consumer._process_patient_allocation_message(message)

        print(f"Processing result: {result}")

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT_ALLOCATION record created
        ref_allocation = integration_db.query(RefPatientAllocation).filter(
            RefPatientAllocation.id == mock_allocation_data["id"]
        ).first()

        assert ref_allocation is not None
        assert ref_allocation.patientId == mock_allocation_data["patientId"]
        assert ref_allocation.doctorId == mock_allocation_data["doctorId"]
        assert ref_allocation.gameTherapistId == mock_allocation_data["gameTherapistId"]
        assert ref_allocation.supervisorId == mock_allocation_data["supervisorId"]
        assert ref_allocation.caregiverId == mock_allocation_data["caregiverId"]
        assert ref_allocation.active == "Y"
        assert ref_allocation.isDeleted == "0"

        print(f"DONE: Created REF_PATIENT_ALLOCATION ID: {ref_allocation.id}")
        print(f"  Patient ID: {ref_allocation.patientId}")
        print(f"  Doctor ID: {ref_allocation.doctorId}")
        print(f"  IsDeleted: {ref_allocation.isDeleted}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_ALLOCATION_CREATED"
        assert processed_event.aggregate_id == str(mock_allocation_data["id"])
        assert json.loads(processed_event.operation_result)['status'] == "success"

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")
        print(f"  Event Type: {processed_event.event_type}")
        print(f"  Status: {json.loads(processed_event.operation_result)['status']}")

    def test_duplicate_create_message_is_idempotent(self, integration_db, 
                                                    patient_allocation_consumer, 
                                                    mock_allocation_data):
        """
        GIVEN: PATIENT_ALLOCATION_CREATED message processed twice with same correlation_id
        WHEN: Consumer processes duplicate message
        THEN: Returns DUPLICATE result and no additional records created

        Goal: Verify idempotency - duplicate messages don't create duplicate records
        """
        correlation_id = str(uuid.uuid4()).upper()
        message = create_allocation_created_message(mock_allocation_data, correlation_id)

        print(f"\nProcessing initial PATIENT_ALLOCATION_CREATED message: {correlation_id}")

        # Process first time
        result1 = patient_allocation_consumer._process_patient_allocation_message(message)
        assert result1 == MessageProcessingResult.SUCCESS

        initial_allocation_count = integration_db.query(RefPatientAllocation).filter(
            RefPatientAllocation.id == mock_allocation_data["id"]
        ).count()
        initial_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()

        print(f"Initial counts - Allocations: {initial_allocation_count}, Processed Events: {initial_processed_count}")

        # Process duplicate message
        print(f"Processing duplicate PATIENT_ALLOCATION_CREATED message: {correlation_id}")
        result2 = patient_allocation_consumer._process_patient_allocation_message(message)

        # Should return DUPLICATE
        assert result2 == MessageProcessingResult.DUPLICATE

        # Verify no additional records created
        final_allocation_count = integration_db.query(RefPatientAllocation).filter(
            RefPatientAllocation.id == mock_allocation_data["id"]
        ).count()
        final_processed_count = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).count()

        assert final_allocation_count == initial_allocation_count
        assert final_processed_count == initial_processed_count

        print(f"DONE: Duplicate message handled correctly - no new records created")
        print(f"Final counts - Allocations: {final_allocation_count}, Processed Events: {final_processed_count}")


# ===== Update Patient Allocation Tests =====

class TestConsumerPatientAllocationUpdate:
    """Test consumer processing of PATIENT_ALLOCATION_UPDATED events"""

    def test_update_allocation_processes_message_successfully(self, integration_db,
                                                              patient_allocation_consumer,
                                                              mock_allocation_data):
        """
        GIVEN: Existing REF_PATIENT_ALLOCATION record and PATIENT_ALLOCATION_UPDATED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT_ALLOCATION record is updated and PROCESSED_EVENTS record exists

        Goal: Verify that consuming a PATIENT_ALLOCATION_UPDATED message updates the allocation
        """
        # First create the allocation
        create_correlation_id = str(uuid.uuid4()).upper()
        create_message = create_allocation_created_message(mock_allocation_data, create_correlation_id)
        patient_allocation_consumer._process_patient_allocation_message(create_message)

        print(f"\nCreated initial allocation ID: {mock_allocation_data['id']}")

        # Clear processed events for clean test
        integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == create_correlation_id
        ).delete()
        integration_db.commit()

        # Update the allocation
        updated_data = mock_allocation_data.copy()
        updated_data["doctorId"] = "DOC999"
        updated_data["caregiverId"] = "CG999"
        updated_data["modifiedDate"] = datetime.now().isoformat()

        update_correlation_id = str(uuid.uuid4()).upper()
        update_message = create_allocation_updated_message(
            mock_allocation_data["id"],
            mock_allocation_data,
            updated_data,
            update_correlation_id
        )

        print(f"Processing PATIENT_ALLOCATION_UPDATED message: {update_correlation_id}")

        # Process update message
        result = patient_allocation_consumer._process_patient_allocation_message(update_message)

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT_ALLOCATION record updated
        ref_allocation = integration_db.query(RefPatientAllocation).filter(
            RefPatientAllocation.id == mock_allocation_data["id"]
        ).first()

        assert ref_allocation is not None
        assert ref_allocation.doctorId == "DOC999"
        assert ref_allocation.caregiverId == "CG999"
        assert ref_allocation.isDeleted == "0"

        print(f"DONE: Updated REF_PATIENT_ALLOCATION ID: {ref_allocation.id}")
        print(f"  New Doctor ID: {ref_allocation.doctorId}")
        print(f"  New Caregiver ID: {ref_allocation.caregiverId}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == update_correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_ALLOCATION_UPDATED"
        assert processed_event.aggregate_id == str(mock_allocation_data["id"])

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")

    def test_update_nonexistent_allocation_succeeds_gracefully(self, integration_db,
                                                               patient_allocation_consumer,
                                                               mock_allocation_data):
        """
        GIVEN: PATIENT_ALLOCATION_UPDATED message for non-existent allocation
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)

        Goal: Verify that updates for non-existent allocations don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()

        non_existent_data = {**mock_allocation_data, "id": 99999}

        update_message = create_allocation_updated_message(
            99999,
            non_existent_data,
            non_existent_data,
            correlation_id
        )

        print(f"\nProcessing UPDATE for non-existent allocation 99999")

        # Process the message
        result = patient_allocation_consumer._process_patient_allocation_message(update_message)

        # Should succeed gracefully (no crash/retry)
        assert result == MessageProcessingResult.SUCCESS

        # Verify PROCESSED_EVENTS record created (for idempotency tracking)
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None

        print(f"DONE: Non-existent allocation update handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")


# ===== Delete Patient Allocation Tests =====

class TestConsumerPatientAllocationDelete:
    """Test consumer processing of PATIENT_ALLOCATION_DELETED events"""

    def test_delete_allocation_processes_message_successfully(self, integration_db,
                                                              patient_allocation_consumer,
                                                              mock_allocation_data):
        """
        GIVEN: Existing REF_PATIENT_ALLOCATION record and PATIENT_ALLOCATION_DELETED message
        WHEN: Consumer processes the message
        THEN: REF_PATIENT_ALLOCATION record is soft-deleted and PROCESSED_EVENTS record exists

        Goal: Verify that consuming a PATIENT_ALLOCATION_DELETED message soft-deletes the allocation
        """
        # First create the allocation
        create_correlation_id = str(uuid.uuid4()).upper()
        mock_allocation_data["id"] = 12346  # Unique ID for this test
        create_message = create_allocation_created_message(mock_allocation_data, create_correlation_id)
        patient_allocation_consumer._process_patient_allocation_message(create_message)

        print(f"\nCreated initial allocation ID: {mock_allocation_data['id']}")

        # Verify allocation exists and is not deleted
        allocation_before = integration_db.query(RefPatientAllocation).filter(
            RefPatientAllocation.id == mock_allocation_data["id"]
        ).first()
        assert allocation_before.isDeleted == "0"
        print(f"Allocation before delete - IsDeleted: {allocation_before.isDeleted}")

        # Delete the allocation
        delete_correlation_id = str(uuid.uuid4()).upper()
        delete_message = create_allocation_deleted_message(
            mock_allocation_data["id"],
            mock_allocation_data,
            delete_correlation_id
        )

        print(f"Processing PATIENT_ALLOCATION_DELETED message: {delete_correlation_id}")

        # Process delete message
        result = patient_allocation_consumer._process_patient_allocation_message(delete_message)

        # Verify processing result
        assert result == MessageProcessingResult.SUCCESS

        # Verify REF_PATIENT_ALLOCATION record soft-deleted
        ref_allocation = integration_db.query(RefPatientAllocation).filter(
            RefPatientAllocation.id == mock_allocation_data["id"]
        ).first()

        integration_db.refresh(ref_allocation)

        assert ref_allocation is not None
        assert ref_allocation.isDeleted == "1"

        print(f"DONE: Soft-deleted REF_PATIENT_ALLOCATION ID: {ref_allocation.id}")
        print(f"  IsDeleted: {ref_allocation.isDeleted}")

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == delete_correlation_id
        ).first()

        assert processed_event is not None
        assert processed_event.event_type == "PATIENT_ALLOCATION_DELETED"
        assert processed_event.aggregate_id == str(mock_allocation_data["id"])

        print(f"DONE: Created PROCESSED_EVENT ID: {processed_event.aggregate_id}")

    def test_delete_nonexistent_allocation_succeeds_gracefully(self, integration_db,
                                                               patient_allocation_consumer,
                                                               mock_allocation_data):
        """
        GIVEN: PATIENT_ALLOCATION_DELETED message for non-existent allocation
        WHEN: Consumer processes the message
        THEN: Returns SUCCESS and PROCESSED_EVENTS record created (graceful handling)

        Goal: Verify that deletes for non-existent allocations don't cause failures
        """
        correlation_id = str(uuid.uuid4()).upper()

        non_existent_data = {**mock_allocation_data, "id": 99999}

        delete_message = create_allocation_deleted_message(
            99999,
            non_existent_data,
            correlation_id
        )

        print(f"\nProcessing DELETE for non-existent allocation 99999")

        # Process the message
        result = patient_allocation_consumer._process_patient_allocation_message(delete_message)

        # Should succeed gracefully
        assert result == MessageProcessingResult.SUCCESS

        # Verify PROCESSED_EVENTS record created
        processed_event = integration_db.query(ProcessedEvent).filter(
            ProcessedEvent.correlation_id == correlation_id
        ).first()

        assert processed_event is not None

        print(f"DONE: Non-existent allocation deletion handled gracefully")
        print(f"PROCESSED_EVENT created for tracking: {processed_event.aggregate_id}")