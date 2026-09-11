import pytest
from unittest import mock
from datetime import date, datetime

from pear_schedule.crud.ref_adhoc_crud import (
    create_ref_adhoc,
    update_ref_adhoc,
    delete_ref_adhoc,
    get_ref_adhoc_by_id,
    get_ref_adhoc_by_patient,
    get_idempotency_stats,
    cleanup_old_processed_events,
    is_event_already_processed,
)

from pear_schedule.models.ref_adhoc_model import RefAdhoc
from pear_schedule.schemas.ref_adhoc import (
    RefAdhocCreate,
    RefAdhocUpdate,
    RefAdhocDelete,
)


@pytest.fixture
def sample_adhoc():
    """Create a sample RefAdhoc instance"""
    return RefAdhoc(
        AdhocID=1,
        PatientID=4,
        OldCentreActivityID=2,
        NewCentreActivityID=3,
        StartDate=date(2025, 1, 6),
        EndDate=date(2025, 1, 10),
        Status="PENDING",
        IsDeleted="0",
        CreatedDateTime=datetime(2025, 1, 1, 10, 0, 0),
        UpdatedDateTime=datetime(2025, 1, 1, 10, 0, 0),
        CreatedById="test_user",
        ModifiedById="test_user",
    )


@pytest.fixture
def sample_created_ref_adhoc_data():
    return RefAdhocCreate(
        AdhocID=1,
        PatientID=4,
        OldCentreActivityID=2,
        NewCentreActivityID=3,
        StartDate=date(2025, 1, 6),
        EndDate=date(2025, 1, 10),
        Status="PENDING",
        IsDeleted="0",
        CreatedDateTime=datetime(2025, 1, 1, 10, 0, 0),
        UpdatedDateTime=datetime(2025, 1, 1, 10, 0, 0),
        CreatedById="test_user",
        ModifiedById="test_user",
    )


@pytest.fixture
def sample_updated_ref_adhoc_data():
    return RefAdhocUpdate(
        PatientID=4,
        OldCentreActivityID=2,
        NewCentreActivityID=3,
        StartDate=date(2025, 1, 6),
        EndDate=date(2025, 1, 10),
        Status="APPROVED",
        IsDeleted="0",
        UpdatedDateTime=datetime(2025, 1, 2, 10, 0, 0),
        ModifiedById="test_user",
    )


@pytest.fixture
def sample_deleted_ref_adhoc_data():
    return RefAdhocDelete(
        UpdatedDateTime=datetime(2025, 1, 3, 10, 0, 0),
        ModifiedById="test_user",
    )


def _passthrough_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
    """Run the wrapped operation as if it were the first time this event was seen."""
    return operation(), False


# ===== create_ref_adhoc tests =====

@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_success(mock_idempotent_process, db_session_mock, sample_created_ref_adhoc_data, sample_adhoc):
    """Should create a new adhoc successfully"""

    # First lookup is the existence check, second fetches the inserted row
    db_session_mock.query().filter().first.side_effect = [None, sample_adhoc]
    mock_idempotent_process.side_effect = _passthrough_idempotent

    result, was_duplicate = create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_created_ref_adhoc_data,
        correlation_id="corr_id_123",
        created_by="test_user",
    )

    assert result == sample_adhoc
    assert was_duplicate is False
    # Adhoc inserts go through raw SQL with IDENTITY_INSERT, not db.add()
    db_session_mock.execute.assert_called_once()
    db_session_mock.flush.assert_called_once()
    db_session_mock.commit.assert_called_once()
    mock_idempotent_process.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_uses_adhoc_id_as_key(mock_idempotent_process, db_session_mock, sample_created_ref_adhoc_data, sample_adhoc):
    """Should pass AdhocID as the aggregate_id to the idempotency service"""

    db_session_mock.query().filter().first.side_effect = [None, sample_adhoc]
    mock_idempotent_process.side_effect = _passthrough_idempotent

    create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_created_ref_adhoc_data,
        correlation_id="corr_id_123",
        created_by="test_user",
    )

    kwargs = mock_idempotent_process.call_args.kwargs
    assert kwargs["event_type"] == "ADHOC_CREATED"
    assert kwargs["aggregate_id"] == "1"  # AdhocID from the source event


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_insert_params_match_source_event(mock_idempotent_process, db_session_mock, sample_created_ref_adhoc_data, sample_adhoc):
    """Should carry every mapped field from the event into the INSERT parameters"""

    db_session_mock.query().filter().first.side_effect = [None, sample_adhoc]
    mock_idempotent_process.side_effect = _passthrough_idempotent

    create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_created_ref_adhoc_data,
        correlation_id="corr_id_123",
        created_by="test_user",
    )

    params = db_session_mock.execute.call_args.args[1]
    assert params["AdhocID"] == 1
    assert params["PatientID"] == 4
    assert params["OldCentreActivityID"] == 2
    assert params["NewCentreActivityID"] == 3
    assert params["Status"] == "PENDING"
    assert params["IsDeleted"] == "0"
    # created_by wins over whatever the payload carried
    assert params["CreatedById"] == "test_user"


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
def test_create_ref_adhoc_skip_duplicate_check(mock_record_processed_event, db_session_mock, sample_created_ref_adhoc_data, sample_adhoc):
    """Should create an adhoc without the duplicate check (sync event)"""

    db_session_mock.query().filter().first.side_effect = [None, sample_adhoc]
    mock_record_processed_event.return_value = None

    result, was_duplicate = create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_created_ref_adhoc_data,
        correlation_id="222",
        created_by="test_user",
        skip_duplicate_check=True,
    )

    assert result == sample_adhoc
    assert was_duplicate is False
    db_session_mock.execute.assert_called_once()
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_existing_raises(mock_idempotent_process, db_session_mock, sample_created_ref_adhoc_data, sample_adhoc):
    """Should raise ValueError when the adhoc already exists"""

    db_session_mock.query().filter().first.return_value = sample_adhoc
    mock_idempotent_process.side_effect = _passthrough_idempotent

    with pytest.raises(ValueError) as exc_info:
        create_ref_adhoc(
            db=db_session_mock,
            adhoc=sample_created_ref_adhoc_data,
            correlation_id="corr_id_789",
            created_by="test_user",
        )

    assert "already exists" in str(exc_info.value)
    db_session_mock.rollback.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_duplicate_detected(mock_idempotent_process, db_session_mock, sample_created_ref_adhoc_data, sample_adhoc):
    """Should return the existing record when the idempotency service detects a replay"""

    mock_idempotent_process.side_effect = lambda **kwargs: (None, True)
    db_session_mock.query().filter().first.return_value = sample_adhoc

    result, was_duplicate = create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_created_ref_adhoc_data,
        correlation_id="corr_id_101",
        created_by="test_user",
    )

    assert was_duplicate is True
    assert result == sample_adhoc
    # A replay must not re-commit
    db_session_mock.commit.assert_not_called()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_foreign_key_error_rolls_back(mock_idempotent_process, db_session_mock, sample_created_ref_adhoc_data):
    """Should roll back and re-raise on an invalid centre activity FK"""

    db_session_mock.query().filter().first.return_value = None
    db_session_mock.execute.side_effect = Exception("FOREIGN KEY constraint failed: REF_CENTRE_ACTIVITY")
    mock_idempotent_process.side_effect = _passthrough_idempotent

    with pytest.raises(Exception) as exc_info:
        create_ref_adhoc(
            db=db_session_mock,
            adhoc=sample_created_ref_adhoc_data,
            correlation_id="corr_id_102",
            created_by="test_user",
        )

    assert "foreign key" in str(exc_info.value).lower()
    db_session_mock.rollback.assert_called_once()


# ===== update_ref_adhoc tests =====

@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_success(mock_idempotent_process, db_session_mock, sample_updated_ref_adhoc_data, sample_adhoc):
    """Should update an existing adhoc successfully"""

    db_session_mock.query().filter().first.return_value = sample_adhoc
    mock_idempotent_process.side_effect = _passthrough_idempotent

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_update=sample_updated_ref_adhoc_data,
        correlation_id="corr_id_201",
        skip_duplicate_check=False,
    )

    assert result == sample_adhoc
    assert was_duplicate is False
    assert result.Status == "APPROVED"
    assert result.UpdatedDateTime == datetime(2025, 1, 2, 10, 0, 0)
    assert result.ModifiedById == "test_user"
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_never_overwrites_primary_key(mock_idempotent_process, db_session_mock, sample_updated_ref_adhoc_data, sample_adhoc):
    """Should leave AdhocID untouched while applying the update"""

    db_session_mock.query().filter().first.return_value = sample_adhoc
    mock_idempotent_process.side_effect = _passthrough_idempotent

    result, _ = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_update=sample_updated_ref_adhoc_data,
        correlation_id="corr_id_202",
    )

    assert result.AdhocID == 1


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_not_found(mock_idempotent_process, db_session_mock, sample_updated_ref_adhoc_data):
    """Should return None when the adhoc does not exist"""

    db_session_mock.query().filter().first.return_value = None
    mock_idempotent_process.side_effect = _passthrough_idempotent

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=99999,
        adhoc_update=sample_updated_ref_adhoc_data,
        correlation_id="corr_id_203",
    )

    assert result is None
    assert was_duplicate is False
    # Commits so the consumer does not requeue a message for a row that is not there
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
def test_update_ref_adhoc_skip_duplicate_check(mock_record_processed_event, db_session_mock, sample_updated_ref_adhoc_data, sample_adhoc):
    """Should update without the duplicate check (sync event)"""

    db_session_mock.query().filter().first.return_value = sample_adhoc
    mock_record_processed_event.return_value = None

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_update=sample_updated_ref_adhoc_data,
        correlation_id="corr_id_204",
        skip_duplicate_check=True,
    )

    assert result == sample_adhoc
    assert was_duplicate is False
    mock_record_processed_event.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_duplicate_detected(mock_idempotent_process, db_session_mock, sample_updated_ref_adhoc_data, sample_adhoc):
    """Should return the current state when the idempotency service detects a replay"""

    mock_idempotent_process.side_effect = lambda **kwargs: (None, True)
    db_session_mock.query().filter().first.return_value = sample_adhoc

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_update=sample_updated_ref_adhoc_data,
        correlation_id="corr_id_205",
    )

    assert was_duplicate is True
    assert result == sample_adhoc
    db_session_mock.commit.assert_not_called()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_error_rolls_back(mock_idempotent_process, db_session_mock, sample_updated_ref_adhoc_data, sample_adhoc):
    """Should roll back and re-raise when the flush fails"""

    db_session_mock.query().filter().first.return_value = sample_adhoc
    db_session_mock.flush.side_effect = Exception("database connection lost")
    mock_idempotent_process.side_effect = _passthrough_idempotent

    with pytest.raises(Exception) as exc_info:
        update_ref_adhoc(
            db=db_session_mock,
            adhoc_id=1,
            adhoc_update=sample_updated_ref_adhoc_data,
            correlation_id="corr_id_206",
        )

    assert "database connection lost" in str(exc_info.value)
    db_session_mock.rollback.assert_called_once()


# ===== delete_ref_adhoc tests =====

@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_success(mock_idempotent_process, db_session_mock, sample_deleted_ref_adhoc_data, sample_adhoc):
    """Should soft delete an existing adhoc"""

    sample_adhoc.IsDeleted = "0"
    db_session_mock.query().filter().first.return_value = sample_adhoc
    mock_idempotent_process.side_effect = _passthrough_idempotent

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_ref_adhoc_data,
        correlation_id="corr_id_301",
    )

    assert result == sample_adhoc
    assert was_duplicate is False
    assert result.IsDeleted == "1"
    assert result.ModifiedById == "test_user"
    assert result.UpdatedDateTime == datetime(2025, 1, 3, 10, 0, 0)
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_already_deleted_is_noop(mock_idempotent_process, db_session_mock, sample_deleted_ref_adhoc_data, sample_adhoc):
    """Should leave an already-deleted adhoc untouched rather than restamping it"""

    sample_adhoc.IsDeleted = "1"
    sample_adhoc.ModifiedById = "someone_else"
    db_session_mock.query().filter().first.return_value = sample_adhoc
    mock_idempotent_process.side_effect = _passthrough_idempotent

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_ref_adhoc_data,
        correlation_id="corr_id_302",
    )

    assert result == sample_adhoc
    assert was_duplicate is False
    assert result.IsDeleted == "1"
    assert result.ModifiedById == "someone_else"


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_not_found(mock_idempotent_process, db_session_mock, sample_deleted_ref_adhoc_data):
    """Should return None when the adhoc does not exist"""

    db_session_mock.query().filter().first.return_value = None
    mock_idempotent_process.side_effect = _passthrough_idempotent

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=99999,
        adhoc_delete=sample_deleted_ref_adhoc_data,
        correlation_id="corr_id_303",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
def test_delete_ref_adhoc_skip_duplicate_check(mock_record_processed_event, db_session_mock, sample_deleted_ref_adhoc_data, sample_adhoc):
    """Should delete without the duplicate check (sync event)"""

    sample_adhoc.IsDeleted = "0"
    db_session_mock.query().filter().first.return_value = sample_adhoc
    mock_record_processed_event.return_value = None

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_ref_adhoc_data,
        correlation_id="corr_id_304",
        skip_duplicate_check=True,
    )

    assert result == sample_adhoc
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    mock_record_processed_event.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_duplicate_detected(mock_idempotent_process, db_session_mock, sample_deleted_ref_adhoc_data, sample_adhoc):
    """Should return the current state when the idempotency service detects a replay"""

    mock_idempotent_process.side_effect = lambda **kwargs: (None, True)
    db_session_mock.query().filter().first.return_value = sample_adhoc

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_ref_adhoc_data,
        correlation_id="corr_id_305",
    )

    assert was_duplicate is True
    assert result == sample_adhoc
    db_session_mock.commit.assert_not_called()


# ===== read helper tests =====

def test_get_ref_adhoc_by_id(db_session_mock, sample_adhoc):
    """Should return the adhoc matching the given ID"""

    db_session_mock.query().filter().first.return_value = sample_adhoc

    result = get_ref_adhoc_by_id(db=db_session_mock, adhoc_id=1)

    assert result == sample_adhoc


def test_get_ref_adhoc_by_id_not_found(db_session_mock):
    """Should return None when no adhoc matches"""

    db_session_mock.query().filter().first.return_value = None

    result = get_ref_adhoc_by_id(db=db_session_mock, adhoc_id=99999)

    assert result is None


def test_get_ref_adhoc_by_patient(db_session_mock, sample_adhoc):
    """Should return every adhoc belonging to a patient"""

    db_session_mock.query().filter().all.return_value = [sample_adhoc]

    result = get_ref_adhoc_by_patient(db=db_session_mock, patient_id=4)

    assert result == [sample_adhoc]


def test_get_ref_adhoc_by_patient_empty(db_session_mock):
    """Should return an empty list when the patient has no adhocs"""

    db_session_mock.query().filter().all.return_value = []

    result = get_ref_adhoc_by_patient(db=db_session_mock, patient_id=999)

    assert result == []


# ===== idempotency helper tests =====

@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.get_processing_stats')
def test_get_idempotency_stats(mock_get_stats, db_session_mock):
    """Should delegate to the idempotency service"""

    mock_get_stats.return_value = {"total": 5}

    result = get_idempotency_stats(db=db_session_mock)

    assert result == {"total": 5}
    mock_get_stats.assert_called_once_with(db_session_mock)


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.cleanup_old_events')
def test_cleanup_old_processed_events(mock_cleanup, db_session_mock):
    """Should delegate to the idempotency service with the retention window"""

    mock_cleanup.return_value = 3

    result = cleanup_old_processed_events(db=db_session_mock, older_than_days=7)

    assert result == 3
    mock_cleanup.assert_called_once_with(db_session_mock, 7)


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.is_already_processed')
def test_is_event_already_processed(mock_is_processed, db_session_mock):
    """Should delegate the correlation ID check to the idempotency service"""

    mock_is_processed.return_value = True

    result = is_event_already_processed(db=db_session_mock, correlation_id="corr_id_401")

    assert result is True
    mock_is_processed.assert_called_once_with(db_session_mock, "corr_id_401")
