import pytest
from unittest import mock
from datetime import datetime

from pear_schedule.crud.ref_patient_medication_crud import (
    create_ref_patient_medication,
    update_ref_patient_medication,
    delete_ref_patient_medication,
    get_ref_patient_medication_by_id,
    get_idempotency_stats,
    cleanup_old_processed_events,
    is_event_already_processed
)
from pear_schedule.schemas.ref_patient_medication import RefPatientMedicationCreate, RefPatientMedicationUpdate, RefPatientMedicationDelete
from pear_schedule.services.idempotency_service import IdempotencyService

@pytest.fixture
def sample_created_ref_patient_medication_data():
    return RefPatientMedicationCreate(
        MedicationID=1,
        PatientID=1,
        PrescriptionName="Prescription Name",
        Dosage="Dosage",
        AdministerTime="AdministerTime",
        Instruction="Instruction",
        PrescriptionRemarks="PrescriptionRemarks",
        StartDateTime=datetime(2025, 10, 10),
        EndDateTime=datetime(2025, 10, 10),
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )

@pytest.fixture
def sample_updated_ref_patient_medication_data():
    return RefPatientMedicationUpdate(
        PatientID=1,
        PrescriptionName="Prescription Name",
        Dosage="Dosage",
        AdministerTime="AdministerTime",
        Instruction="Instruction",
        PrescriptionRemarks="PrescriptionRemarks",
        StartDate=datetime(2025, 10, 10),
        EndDate=datetime(2025, 10, 10),
        IsDeleted=False,
        UpdatedDateTime=datetime.now(),
        ModifiedById="test_user",
    )

@pytest.fixture
def sample_deleted_ref_patient_medication_data():
    return RefPatientMedicationDelete(
        UpdatedDateTime=datetime.now(),
        ModifiedById="test_user",
    )

# ==== create_ref_patient_medication tests ====
@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_create_ref_patient_medication_success(mock_idempotent_process, db_session_mock, sample_created_ref_patient_medication_data, sample_patient_medication):
    """Should create a new patient medication successfully"""

    # Mock no existing ref patient medication found
    db_session_mock.query().filter().first.side_effect = [None, sample_patient_medication]

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()  # executes create_operation
        return result, False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with mock.patch('pear_schedule.crud.ref_patient_medication_crud.RefPatientMedication', return_value=sample_patient_medication):
        result, was_duplicate = create_ref_patient_medication(
            db=db_session_mock,
            medication=sample_created_ref_patient_medication_data,
            correlation_id="corr_id_123",
            created_by="test_user"
        )

    assert result == sample_patient_medication
    assert was_duplicate is False
    db_session_mock.flush.assert_called_once()
    db_session_mock.commit.assert_called_once()
    mock_idempotent_process.assert_called_once()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.record_processed_event')
def test_create_ref_patient_medication_skip_duplicate_raises(db_session_mock, sample_created_ref_patient_medication_data, sample_patient_medication):
    """Should raise error when trying to create a duplicate ref patient medication"""

    # Mock no existing ref patient found
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    with pytest.raises(ValueError):
        create_ref_patient_medication(
            db=db_session_mock,
            medication=sample_created_ref_patient_medication_data,
            correlation_id="corr_id_789",
            created_by="test_user"
        )

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_create_ref_patient_medication_duplicate_detected(mock_idempotent_process, db_session_mock, sample_created_ref_patient_medication_data, sample_patient_medication):
    """Should return existing record if duplicate detected by idempotency service"""

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    result, was_duplicate = create_ref_patient_medication(
        db=db_session_mock,
        medication=sample_created_ref_patient_medication_data,
        correlation_id="corr_id_101",
        created_by="test_user"
    )

    assert was_duplicate is True
    assert result == sample_patient_medication


def test_create_ref_patient_medication_creation_fails(db_session_mock, sample_created_ref_patient_medication_data):
    """Should raise Exception if ref patient medication creation verification fails"""

    # Both queries return None → simulate failed insert
    db_session_mock.query().filter().first.side_effect = lambda: None

    with pytest.raises(Exception, match="Failed to create patient medication"):
        create_ref_patient_medication(
            db=db_session_mock,
            medication=sample_created_ref_patient_medication_data,
            correlation_id="corr_fail_1",
            created_by="test_user",
        )

# ==== update_ref_patient_medication tests ====
@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_update_ref_patient_medication_success(mock_idempotent_process, db_session_mock, sample_updated_ref_patient_medication_data, sample_patient_medication):
    """Should update an existing ref patient medication successfully"""

    # Mock existing ref_patient found
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False
    mock_idempotent_process.side_effect = fake_process_idempotent
    result, was_duplicate = update_ref_patient_medication(
        db=db_session_mock,
        medication_id=1,
        medication_update=sample_updated_ref_patient_medication_data,
        correlation_id="corr_update_123",
    )
    assert result == sample_patient_medication
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_update_ref_patient_medication_not_found(mock_idempotent_process, db_session_mock, sample_updated_ref_patient_medication_data):
    """Should raise error when trying to update a non-existent ref patient medication"""

    # Mock no existing ref_patient found
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent
    result, was_duplicate = update_ref_patient_medication(
        db=db_session_mock,
        medication_id=999,
        medication_update=sample_updated_ref_patient_medication_data,
        correlation_id="corr_update_999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_update_ref_patient_medication_duplicate_event(mock_idempotent_process, db_session_mock, sample_updated_ref_patient_medication_data, sample_patient_medication):
    """Should return existing record if duplicate detected by idempotency service during update"""

    # Mock existing ref_patient found
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_patient_medication(
        db=db_session_mock,
        medication_id=1,
        medication_update=sample_updated_ref_patient_medication_data,
        correlation_id="corr_update_dup",
    )

    assert was_duplicate is True
    assert result == sample_patient_medication
    db_session_mock.commit.assert_not_called()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.record_processed_event')
def test_update_ref_patient_medication_skip_duplicate_check(mock_record_processed_event, db_session_mock, sample_updated_ref_patient_medication_data, sample_patient_medication):
    """Should update an existing ref patient medication without duplicate check"""

    # Mock existing ref_patient_medication found
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    mock_record_processed_event.return_value = None

    result, was_duplicate = update_ref_patient_medication(
        db=db_session_mock,
        medication_id=1,
        medication_update=sample_updated_ref_patient_medication_data,
        correlation_id="corr_update_no_dup_check",
        skip_duplicate_check=True
    )

    assert result == sample_patient_medication
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.record_processed_event')
def test_update_ref_patient_medication_skip_duplicate_check_record_fail(mock_record_processed_event, db_session_mock, sample_updated_ref_patient_medication_data, sample_patient_medication):
    """Skip duplicate check but record_processed_event fails (non-critical)"""

    db_session_mock.query().filter().first.return_value = sample_patient_medication
    mock_record_processed_event.side_effect = Exception("DB not reachable")

    result, was_duplicate = update_ref_patient_medication(
        db=db_session_mock,
        medication_id=1,
        medication_update=sample_updated_ref_patient_medication_data,
        correlation_id="corr_update_skip_fail",
        skip_duplicate_check=True
    )

    assert result == sample_patient_medication
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_update_ref_patient_medication_error(mock_idempotent_process, db_session_mock, sample_updated_ref_patient_medication_data, sample_patient_medication):
    """Should handle error during update operation"""

    # Mock existing ref_patient found
    db_session_mock.query().filter().first.return_value = sample_patient_medication
    db_session_mock.commit.side_effect = Exception("DB not reachable")

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        update_ref_patient_medication(
            db=db_session_mock,
            medication_id=1,
            medication_update=sample_updated_ref_patient_medication_data,
            correlation_id="corr_update_error",
        )
    assert "DB not reachable" in str(exc_info.value)
    db_session_mock.rollback.assert_called_once()

# ==== delete_ref_patient_medication tests ====
@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_delete_ref_patient_medication_success(mock_idempotent_process, db_session_mock, sample_deleted_ref_patient_medication_data, sample_patient_medication):
    """Should soft delete an existing ref patient medication successfully"""

    # Mock existing ref_patient_medication found
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_patient_medication(
        db=db_session_mock,
        medication_id=1,
        medication_delete=sample_deleted_ref_patient_medication_data,
        correlation_id="corr_delete_123",
    )

    assert result == sample_patient_medication
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_delete_ref_patient_medication_not_found(mock_idempotent_process, db_session_mock, sample_deleted_ref_patient_medication_data):
    """Should raise error when trying to delete a non-existent ref patient medication"""

    # Mock no existing ref_patient found
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_patient_medication(
        db=db_session_mock,
        medication_id=999,
        medication_delete=sample_deleted_ref_patient_medication_data,
        correlation_id="corr_delete_999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_delete_ref_patient_medication_already_deleted(mock_idempotent_process, db_session_mock, sample_deleted_ref_patient_medication_data, sample_patient_medication):
    """Should handle already deleted ref patient gracefully"""

    # Mock existing ref_patient_medication found and already deleted
    sample_patient_medication.IsDeleted = "1"
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_patient_medication(
        db=db_session_mock,
        medication_id=1,
        medication_delete=sample_deleted_ref_patient_medication_data,
        correlation_id="corr_delete_already",
    )

    assert result == sample_patient_medication
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_delete_ref_patient_medication_duplicate_event(mock_idempotent_process, db_session_mock, sample_deleted_ref_patient_medication_data, sample_patient_medication):
    """Should return existing record if duplicate detected by idempotency service during delete"""

    # Mock existing ref_patient_medication found
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_patient_medication(
        db=db_session_mock,
        medication_id=1,
        medication_delete=sample_deleted_ref_patient_medication_data,
        correlation_id="corr_delete_dup",
    )

    assert was_duplicate is True
    assert result == sample_patient_medication
    db_session_mock.commit.assert_not_called()

@mock.patch('pear_schedule.crud.ref_patient_medication_crud.IdempotencyService.process_idempotent')
def test_delete_ref_patient_medication_error(mock_idempotent_process, db_session_mock, sample_deleted_ref_patient_medication_data, sample_patient_medication):
    """Should handle error during delete operation"""

    # Mock existing ref_patient found
    db_session_mock.query().filter().first.return_value = sample_patient_medication
    db_session_mock.commit.side_effect = Exception("DB not reachable")

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        delete_ref_patient_medication(
            db=db_session_mock,
            medication_id=1,
            medication_delete=sample_deleted_ref_patient_medication_data,
            correlation_id="corr_delete_error",
        )
    assert "DB not reachable" in str(exc_info.value)
    db_session_mock.rollback.assert_called_once()

# ==== get_ref_patient_medication_by_id tests ====
def test_get_ref_patient_medication_by_id_found(db_session_mock, sample_patient_medication):
    """Test fetching a patient medication by ID when it exists."""
    db_session_mock.query().filter().first.return_value = sample_patient_medication

    result = get_ref_patient_medication_by_id(db=db_session_mock, medication_id=1)

    assert result == sample_patient_medication
    db_session_mock.query().filter().first.assert_called_once()

def test_get_ref_patient_medication_by_id_not_found(db_session_mock):
    """Test fetching a patient by ID when it does not exist."""
    db_session_mock.query().filter().first.return_value = None

    result = get_ref_patient_medication_by_id(db=db_session_mock, medication_id=999)

    assert result is None
    db_session_mock.query().filter().first.assert_called_once()

# ===== get_idempotency_stats tests ===
def test_get_idempotency_stats(db_session_mock):
    """Test fetching idempotency stats. Makes sure that get_idempotency_stats calls the service and returns its data."""
    expected_stats = {
        "total_processed_events": 10,
        "events_last_24h": 2,
        "events_with_errors": 1,
        "events_by_type": [{"event_type": "PATIENT_MEDICATION_CREATED", "count": 5}],
        "latest_events": [],
        "stats_generated_at": "2025-10-12T00:00:00"
    }

    with mock.patch.object(IdempotencyService, "get_processing_stats", return_value=expected_stats) as mock_get_stats:
        results = get_idempotency_stats(db=db_session_mock)

        assert results == expected_stats
        mock_get_stats.assert_called_once_with(db_session_mock)

# ===== cleanup_old_processed_events tests ===
def test_cleanup_old_processed_events(db_session_mock):
    """Test cleanup of old processed events. Ensures that cleanup_old_processed_events calls the service method."""

    expected_deleted = 5
    older_than_days = 60
    with mock.patch.object(IdempotencyService, "cleanup_old_events", return_value=expected_deleted) as mock_cleanup:
        result = cleanup_old_processed_events(db=db_session_mock, older_than_days=older_than_days)

        assert result == expected_deleted

        mock_cleanup.assert_called_once_with(db_session_mock, older_than_days)

# ===== is_event_already_processed tests ===
def test_is_event_already_processed(db_session_mock):
    """Test checking if event is already processed. Ensures that is_event_already_processed calls the service method."""
    with mock.patch.object(IdempotencyService, "is_already_processed", return_value=True) as mock_is_processed:
        result = is_event_already_processed(
            db=db_session_mock,
            correlation_id="corr-123",
        )

        assert result is True
        mock_is_processed.assert_called_once_with(db_session_mock, "corr-123")