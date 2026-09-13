import pytest
from unittest import mock
from datetime import datetime

from pear_schedule.crud.ref_patient_allocation_crud import (
    create_ref_patient_allocation,
    update_ref_patient_allocation,
    delete_ref_patient_allocation,
    get_ref_patient_allocation_by_id,
    get_ref_patient_allocation_by_patient_id,
    check_patient_allocation_exists,
    is_event_already_processed,
)
from pear_schedule.schemas.ref_patient_allocation import (
    RefPatientAllocationCreate,
    RefPatientAllocationUpdate,
    RefPatientAllocationDelete,
)
from pear_schedule.services.idempotency_service import IdempotencyService


@pytest.fixture
def sample_create_data():
    return RefPatientAllocationCreate(
        id=1,
        patient_id=1,
        doctor_id="doctor_1",
        game_therapist_id="therapist_1",
        supervisor_id="supervisor_1",
        caregiver_id="caregiver_1",
        active="Y",
        is_deleted="0",
        created_date=datetime(2024, 1, 1),
        modified_date=datetime(2024, 1, 1),
        created_by_id="test_user",
        modified_by_id="test_user",
    )


@pytest.fixture
def sample_updated_data():
    return RefPatientAllocationUpdate(
        supervisor_id="supervisor_2",
        modified_date=datetime(2024, 2, 1),
        modified_by_id="test_user",
    )


@pytest.fixture
def sample_deleted_data():
    return RefPatientAllocationDelete(
        modified_date=datetime(2024, 3, 1),
        modified_by_id="test_user",
    )


def _passthrough_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
    """Run the wrapped operation as if it were the first time this event was seen."""
    return operation(), False


# ==== create_ref_patient_allocation tests ====
@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_create_success(mock_idempotency_process, db_session_mock, sample_ref_patient_allocation, sample_create_data):
    """Test successful creation of a patient allocation."""
    db_session_mock.query().filter().first.side_effect = [None, sample_ref_patient_allocation]
    mock_idempotency_process.side_effect = _passthrough_idempotent

    result, was_duplicate = create_ref_patient_allocation(
        db=db_session_mock,
        allocation=sample_create_data,
        correlation_id="corr-123",
        created_by="test_user",
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is False
    # inserts go through raw SQL with IDENTITY_INSERT, not db.add()
    db_session_mock.execute.assert_called_once()
    db_session_mock.flush.assert_called_once()
    db_session_mock.commit.assert_called_once()
    mock_idempotency_process.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_create_uses_allocation_id_as_key(mock_idempotency_process, db_session_mock, sample_ref_patient_allocation, sample_create_data):
    """Test allocation id is passed as the aggregate_id to the idempotency service."""
    db_session_mock.query().filter().first.side_effect = [None, sample_ref_patient_allocation]
    mock_idempotency_process.side_effect = _passthrough_idempotent

    create_ref_patient_allocation(
        db=db_session_mock,
        allocation=sample_create_data,
        correlation_id="corr-123",
        created_by="test_user",
    )

    kwargs = mock_idempotency_process.call_args.kwargs
    assert kwargs["event_type"] == "PATIENT_ALLOCATION_CREATED"
    assert kwargs["aggregate_id"] == "1"


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_create_insert_params_match_source_event(mock_idempotency_process, db_session_mock, sample_ref_patient_allocation, sample_create_data):
    """Test every mapped field from the event carries into the INSERT parameters."""
    db_session_mock.query().filter().first.side_effect = [None, sample_ref_patient_allocation]
    mock_idempotency_process.side_effect = _passthrough_idempotent

    create_ref_patient_allocation(
        db=db_session_mock,
        allocation=sample_create_data,
        correlation_id="corr-123",
        created_by="test_user",
    )

    params = db_session_mock.execute.call_args.args[1]
    assert params["id"] == 1
    assert params["patientId"] == 1
    assert params["doctorId"] == "doctor_1"
    assert params["supervisorId"] == "supervisor_1"
    assert params["isDeleted"] == "0"
    # created_by wins over whatever the payload carried
    assert params["created_by_id"] == "test_user"
    assert params["modified_by_id"] == "test_user"


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_create_existing_raises_valueerror(mock_process_idempotent, db_session_mock, sample_ref_patient_allocation, sample_create_data):
    """Test ValueError when an allocation with the same id already exists."""
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_process_idempotent.side_effect = _passthrough_idempotent

    with pytest.raises(ValueError, match="already exists"):
        create_ref_patient_allocation(
            db=db_session_mock,
            allocation=sample_create_data,
            correlation_id="corr-123",
            created_by="test_user",
        )

    db_session_mock.rollback.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_create_fails_to_fetch_created(mock_process_idempotent, db_session_mock, sample_create_data):
    """Test Exception when the created allocation is not found after insert."""
    db_session_mock.query().filter().first.side_effect = [None, None]
    mock_process_idempotent.side_effect = _passthrough_idempotent

    with pytest.raises(Exception, match="Failed to create patient allocation"):
        create_ref_patient_allocation(
            db=db_session_mock,
            allocation=sample_create_data,
            correlation_id="corr-999",
            created_by="test_user",
        )


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_create_duplicate_returns_existing(mock_process_idempotent, db_session_mock, sample_ref_patient_allocation, sample_create_data):
    """Test duplicate idempotent event returns the existing allocation."""
    mock_process_idempotent.return_value = (sample_ref_patient_allocation, True)
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation

    result, was_duplicate = create_ref_patient_allocation(
        db=db_session_mock,
        allocation=sample_create_data,
        correlation_id="corr-dup",
        created_by="test_user",
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is True
    # a replay must not re-commit
    db_session_mock.commit.assert_not_called()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_create_process_raises(mock_process_idempotent, db_session_mock, sample_create_data):
    """Test that exceptions in process_idempotent trigger rollback."""
    mock_process_idempotent.side_effect = Exception("critical failure")

    with pytest.raises(Exception, match="critical failure"):
        create_ref_patient_allocation(
            db=db_session_mock,
            allocation=sample_create_data,
            correlation_id="corr-create-error",
            created_by="test_user",
        )

    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_create_foreign_key_error_rolls_back(mock_process_idempotent, db_session_mock, sample_create_data):
    """Test rollback and re-raise on an invalid patient FK."""
    db_session_mock.query().filter().first.return_value = None
    db_session_mock.execute.side_effect = Exception("FOREIGN KEY constraint failed: REF_PATIENT")
    mock_process_idempotent.side_effect = _passthrough_idempotent

    with pytest.raises(Exception, match="(?i)foreign key"):
        create_ref_patient_allocation(
            db=db_session_mock,
            allocation=sample_create_data,
            correlation_id="corr-fk-error",
            created_by="test_user",
        )

    db_session_mock.rollback.assert_called_once()


# ==== update_ref_patient_allocation tests ====
@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_update_success(mock_idempotency_process, db_session_mock, sample_ref_patient_allocation, sample_updated_data):
    """Test successful update of a patient allocation."""
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_idempotency_process.side_effect = _passthrough_idempotent

    result, was_duplicate = update_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_update=sample_updated_data,
        correlation_id="corr-update-123",
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is False
    assert result.supervisorId == "supervisor_2"
    assert result.modified_by_id == "test_user"
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_update_maps_every_field_to_its_model_column(mock_idempotency_process, db_session_mock, sample_ref_patient_allocation):
    """Test each schema field name maps to the right ORM column, including the generic fallback."""
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_idempotency_process.side_effect = _passthrough_idempotent
    full_update = RefPatientAllocationUpdate(
        patient_id=2,
        doctor_id="doctor_2",
        game_therapist_id="therapist_2",
        caregiver_id="caregiver_2",
        temp_doctor_id="temp_doctor_2",
        temp_caregiver_id="temp_caregiver_2",
        is_deleted="1",
        active="N",
        modified_date=datetime(2024, 2, 1),
        modified_by_id="test_user",
    )

    result, _ = update_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_update=full_update,
        correlation_id="corr-update-full",
    )

    assert result.patientId == 2
    assert result.doctorId == "doctor_2"
    assert result.gameTherapistId == "therapist_2"
    assert result.caregiverId == "caregiver_2"
    assert result.tempDoctorId == "temp_doctor_2"
    assert result.tempCaregiverId == "temp_caregiver_2"
    assert result.isDeleted == "1"
    assert result.active == "N"


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_update_never_overwrites_primary_key(mock_idempotency_process, db_session_mock, sample_ref_patient_allocation, sample_updated_data):
    """Test the allocation id stays untouched while applying an update."""
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_idempotency_process.side_effect = _passthrough_idempotent

    result, _ = update_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_update=sample_updated_data,
        correlation_id="corr-update-pk",
    )

    assert result.id == 1


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_update_not_found(mock_process_idempotent, db_session_mock, sample_updated_data):
    """Test when the allocation to update is not found."""
    db_session_mock.query().filter().first.return_value = None
    mock_process_idempotent.side_effect = _passthrough_idempotent

    result, was_duplicate = update_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="999",
        allocation_update=sample_updated_data,
        correlation_id="corr-update-999",
    )

    assert result is None
    assert was_duplicate is False
    # commits so the consumer does not requeue a message for a row that is not there
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_update_duplicate_event(mock_process_idempotent, db_session_mock, sample_ref_patient_allocation, sample_updated_data):
    """Test duplicate idempotent event returns the existing allocation."""
    mock_process_idempotent.return_value = (sample_ref_patient_allocation, True)
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation

    result, was_duplicate = update_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_update=sample_updated_data,
        correlation_id="corr-update-dup",
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is True
    db_session_mock.commit.assert_not_called()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.record_processed_event')
def test_update_skip_duplicate_check(mock_record_processed_event, mock_process_idempotent, db_session_mock, sample_ref_patient_allocation, sample_updated_data):
    """Test update when skipping duplicate idempotency check."""
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_record_processed_event.return_value = None

    result, was_duplicate = update_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_update=sample_updated_data,
        correlation_id="corr-update-skip",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is False
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.record_processed_event')
@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_update_skip_duplicate_record_fails(mock_process_idempotent, mock_record_processed_event, db_session_mock, sample_ref_patient_allocation, sample_updated_data):
    """Test that update still succeeds if record_processed_event fails while skipping duplicate check."""
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_record_processed_event.side_effect = Exception("non-critical failure")

    result, was_duplicate = update_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_update=sample_updated_data,
        correlation_id="corr-update-warning",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is False
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_update_process_raises(mock_process_idempotent, db_session_mock, sample_updated_data):
    """Test that exceptions in process_idempotent trigger rollback."""
    mock_process_idempotent.side_effect = Exception("critical failure")

    with pytest.raises(Exception, match="critical failure"):
        update_ref_patient_allocation(
            db=db_session_mock,
            allocation_id="1",
            allocation_update=sample_updated_data,
            correlation_id="corr-update-error",
        )

    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_update_error_rolls_back(mock_process_idempotent, db_session_mock, sample_ref_patient_allocation, sample_updated_data):
    """Test rollback and re-raise when the flush fails."""
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    db_session_mock.flush.side_effect = Exception("database connection lost")
    mock_process_idempotent.side_effect = _passthrough_idempotent

    with pytest.raises(Exception, match="database connection lost"):
        update_ref_patient_allocation(
            db=db_session_mock,
            allocation_id="1",
            allocation_update=sample_updated_data,
            correlation_id="corr-update-flush-error",
        )

    db_session_mock.rollback.assert_called_once()


# ==== delete_ref_patient_allocation tests ====
@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_delete_success(mock_idempotency_process, db_session_mock, sample_ref_patient_allocation, sample_deleted_data):
    """Test soft deletion of a patient allocation."""
    sample_ref_patient_allocation.isDeleted = "0"
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_idempotency_process.side_effect = _passthrough_idempotent

    result, was_duplicate = delete_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_delete=sample_deleted_data,
        correlation_id="corr-delete-123",
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is False
    assert result.isDeleted == "1"
    assert result.modified_by_id == "test_user"
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_delete_not_exists(mock_process_idempotent, db_session_mock, sample_deleted_data):
    """Test deletion when the allocation is not found."""
    db_session_mock.query().filter().first.return_value = None
    mock_process_idempotent.side_effect = _passthrough_idempotent

    result, was_duplicate = delete_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="999",
        allocation_delete=sample_deleted_data,
        correlation_id="corr-delete-999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_delete_already_deleted_is_noop(mock_process_idempotent, db_session_mock, sample_ref_patient_allocation, sample_deleted_data):
    """Test an already-deleted allocation is left untouched rather than restamped."""
    sample_ref_patient_allocation.isDeleted = "1"
    sample_ref_patient_allocation.modified_by_id = "someone_else"
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_process_idempotent.side_effect = _passthrough_idempotent

    result, was_duplicate = delete_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_delete=sample_deleted_data,
        correlation_id="corr-delete-already",
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is False
    assert result.isDeleted == "1"
    assert result.modified_by_id == "someone_else"
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_delete_duplicate_event(mock_process_idempotent, db_session_mock, sample_ref_patient_allocation, sample_deleted_data):
    """Test duplicate idempotent event returns the existing allocation."""
    mock_process_idempotent.return_value = (sample_ref_patient_allocation, True)
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation

    result, was_duplicate = delete_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_delete=sample_deleted_data,
        correlation_id="corr-delete-dup",
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is True
    db_session_mock.commit.assert_not_called()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_delete_skip_duplicate_check_has_no_effect(mock_process_idempotent, db_session_mock, sample_ref_patient_allocation, sample_deleted_data):
    """Unlike create/update, delete doesn't branch on skip_duplicate_check - always goes through process_idempotent."""
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation
    mock_process_idempotent.side_effect = _passthrough_idempotent

    result, was_duplicate = delete_ref_patient_allocation(
        db=db_session_mock,
        allocation_id="1",
        allocation_delete=sample_deleted_data,
        correlation_id="corr-delete-skip",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_patient_allocation
    assert was_duplicate is False
    mock_process_idempotent.assert_called_once()


@mock.patch('pear_schedule.crud.ref_patient_allocation_crud.IdempotencyService.process_idempotent')
def test_delete_process_raises(mock_process_idempotent, db_session_mock, sample_deleted_data):
    """Test that exceptions in process_idempotent trigger rollback."""
    mock_process_idempotent.side_effect = Exception("critical failure")

    with pytest.raises(Exception, match="critical failure"):
        delete_ref_patient_allocation(
            db=db_session_mock,
            allocation_id="1",
            allocation_delete=sample_deleted_data,
            correlation_id="corr-delete-error",
        )

    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()


# ==== get_ref_patient_allocation_by_id tests ====
def test_get_by_id_found(db_session_mock, sample_ref_patient_allocation):
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation

    result = get_ref_patient_allocation_by_id(db=db_session_mock, allocation_id="1")

    assert result == sample_ref_patient_allocation


def test_get_by_id_not_found(db_session_mock):
    db_session_mock.query().filter().first.return_value = None

    result = get_ref_patient_allocation_by_id(db=db_session_mock, allocation_id="999")

    assert result is None


# ==== get_ref_patient_allocation_by_patient_id tests ====
def test_get_by_patient_id_found(db_session_mock, sample_ref_patient_allocation):
    db_session_mock.query().filter().first.return_value = sample_ref_patient_allocation

    result = get_ref_patient_allocation_by_patient_id(db=db_session_mock, patient_id=1)

    assert result == sample_ref_patient_allocation


def test_get_by_patient_id_not_found(db_session_mock):
    db_session_mock.query().filter().first.return_value = None

    result = get_ref_patient_allocation_by_patient_id(db=db_session_mock, patient_id=999)

    assert result is None


# ==== check_patient_allocation_exists tests ====
def test_check_exists_true(db_session_mock):
    db_session_mock.query().filter().scalar.return_value = 1

    result = check_patient_allocation_exists(db=db_session_mock, allocation_id="1")

    assert result is True


def test_check_exists_false(db_session_mock):
    db_session_mock.query().filter().scalar.return_value = 0

    result = check_patient_allocation_exists(db=db_session_mock, allocation_id="999")

    assert result is False


# ==== is_event_already_processed tests ====
def test_is_event_already_processed(db_session_mock):
    with mock.patch.object(IdempotencyService, "is_already_processed", return_value=True) as mock_is_processed:
        result = is_event_already_processed(db=db_session_mock, correlation_id="corr-123")

        assert result is True
        mock_is_processed.assert_called_once_with(db_session_mock, "corr-123")
