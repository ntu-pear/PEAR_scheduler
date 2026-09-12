import pytest
from unittest import mock
from datetime import datetime

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
from pear_schedule.schemas.ref_adhoc import RefAdhocCreate, RefAdhocUpdate, RefAdhocDelete
from pear_schedule.services.idempotency_service import IdempotencyService


@pytest.fixture
def sample_create_data():
    return RefAdhocCreate(
        AdhocID=1,
        PatientID=1,
        OldCentreActivityID=1,
        NewCentreActivityID=2,
        StartDate=datetime(2024, 1, 1).date(),
        EndDate=datetime(2024, 1, 7).date(),
        Status="Active",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user",
    )


@pytest.fixture
def sample_updated_data():
    return RefAdhocUpdate(
        Status="Completed",
        UpdatedDateTime=datetime.now(),
        ModifiedById="test_user",
    )


@pytest.fixture
def sample_deleted_data():
    return RefAdhocDelete(
        UpdatedDateTime=datetime.now(),
        ModifiedById="test_user",
    )


# ==== create_ref_adhoc tests ====
@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_success(mock_idempotency_process, db_session_mock, sample_ref_adhoc, sample_create_data):
    """Test successful creation of an adhoc record."""
    db_session_mock.query().filter().first.side_effect = [None, sample_ref_adhoc]

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False

    mock_idempotency_process.side_effect = fake_process_idempotent

    result, was_duplicate = create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_create_data,
        correlation_id="corr-123",
        created_by="test_user",
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    db_session_mock.execute.assert_called_once()
    db_session_mock.flush.assert_called_once()
    db_session_mock.commit.assert_called_once()
    mock_idempotency_process.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_existing_raises_valueerror(mock_process_idempotent, db_session_mock, sample_ref_adhoc, sample_create_data):
    """Test ValueError when adhoc already exists."""
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    with pytest.raises(ValueError, match="already exists"):
        create_ref_adhoc(
            db=db_session_mock,
            adhoc=sample_create_data,
            correlation_id="corr-123",
            created_by="test_user",
        )


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_fails_to_fetch_created(mock_process_idempotent, db_session_mock, sample_create_data):
    """Test Exception when created adhoc not found after insert."""
    db_session_mock.query().filter().first.side_effect = [None, None]

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    with pytest.raises(Exception, match="Failed to create adhoc"):
        create_ref_adhoc(
            db=db_session_mock,
            adhoc=sample_create_data,
            correlation_id="corr-999",
            created_by="test_user",
        )


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_duplicate_returns_existing(mock_process_idempotent, db_session_mock, sample_ref_adhoc, sample_create_data):
    """Test duplicate idempotent event returns existing adhoc."""
    mock_process_idempotent.return_value = (sample_ref_adhoc, True)
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc

    result, was_duplicate = create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_create_data,
        correlation_id="corr-dup",
        created_by="test_user",
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is True


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
def test_create_ref_adhoc_skip_duplicate_check(mock_record_processed_event, db_session_mock, sample_ref_adhoc, sample_create_data):
    """Test create when skipping duplicate idempotency check."""
    db_session_mock.query().filter().first.side_effect = [None, sample_ref_adhoc]
    mock_record_processed_event.return_value = None

    result, was_duplicate = create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_create_data,
        correlation_id="corr-skip",
        created_by="test_user",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
def test_create_ref_adhoc_skip_duplicate_record_fails(mock_record_processed_event, db_session_mock, sample_ref_adhoc, sample_create_data):
    """Test that create still succeeds if record_processed_event fails while skipping duplicate check."""
    db_session_mock.query().filter().first.side_effect = [None, sample_ref_adhoc]
    mock_record_processed_event.side_effect = Exception("non-critical failure")

    result, was_duplicate = create_ref_adhoc(
        db=db_session_mock,
        adhoc=sample_create_data,
        correlation_id="corr-skip-warning",
        created_by="test_user",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_create_ref_adhoc_process_raises(mock_process_idempotent, db_session_mock, sample_create_data):
    """Test that exceptions in process_idempotent trigger rollback."""
    mock_process_idempotent.side_effect = Exception("critical failure")

    with pytest.raises(Exception, match="critical failure"):
        create_ref_adhoc(
            db=db_session_mock,
            adhoc=sample_create_data,
            correlation_id="corr-create-error",
            created_by="test_user",
        )

    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()


# ==== update_ref_adhoc tests ====
@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_success(mock_idempotency_process, db_session_mock, sample_ref_adhoc, sample_updated_data):
    """Test successful update of an adhoc record."""
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False

    mock_idempotency_process.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_update=sample_updated_data,
        correlation_id="corr-update-123",
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_not_found(mock_process_idempotent, db_session_mock, sample_updated_data):
    """Test when adhoc to update not found."""
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=999,
        adhoc_update=sample_updated_data,
        correlation_id="corr-update-999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_duplicate_event(mock_process_idempotent, db_session_mock, sample_ref_adhoc, sample_updated_data):
    """Test duplicate idempotent event returns existing adhoc."""
    mock_process_idempotent.return_value = (sample_ref_adhoc, True)
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_update=sample_updated_data,
        correlation_id="corr-update-dup",
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is True


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
def test_update_ref_adhoc_skip_duplicate_check(mock_record_processed_event, mock_process_idempotent, db_session_mock, sample_ref_adhoc, sample_updated_data):
    """Test update when skipping duplicate idempotency check."""
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc
    mock_record_processed_event.return_value = None

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_update=sample_updated_data,
        correlation_id="corr-update-skip",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_skip_duplicate_record_fails(mock_process_idempotent, mock_record_processed_event, db_session_mock, sample_ref_adhoc, sample_updated_data):
    """Test that update still succeeds if record_processed_event fails while skipping duplicate check."""
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc
    mock_record_processed_event.side_effect = Exception("non-critical failure")

    result, was_duplicate = update_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_update=sample_updated_data,
        correlation_id="corr-update-warning",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_update_ref_adhoc_process_raises(mock_process_idempotent, db_session_mock, sample_updated_data):
    """Test that exceptions in process_idempotent trigger rollback."""
    mock_process_idempotent.side_effect = Exception("critical failure")

    with pytest.raises(Exception, match="critical failure"):
        update_ref_adhoc(
            db=db_session_mock,
            adhoc_id=1,
            adhoc_update=sample_updated_data,
            correlation_id="corr-update-error",
        )

    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()


# ==== delete_ref_adhoc tests ====
@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_success(mock_idempotency_process, db_session_mock, sample_ref_adhoc, sample_deleted_data):
    """Test soft deletion of an adhoc record."""
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False

    mock_idempotency_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_data,
        correlation_id="corr-delete-123",
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    assert sample_ref_adhoc.IsDeleted == "1"
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_not_exists(mock_process_idempotent, db_session_mock, sample_deleted_data):
    """Test deletion when adhoc not found."""
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=999,
        adhoc_delete=sample_deleted_data,
        correlation_id="corr-delete-999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_already_deleted(mock_process_idempotent, db_session_mock, sample_ref_adhoc, sample_deleted_data):
    """Test deletion when adhoc is already marked deleted."""
    sample_ref_adhoc.IsDeleted = "1"
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_data,
        correlation_id="corr-delete-already",
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_duplicate_event(mock_process_idempotent, db_session_mock, sample_ref_adhoc, sample_deleted_data):
    """Test duplicate idempotent event returns existing adhoc."""
    mock_process_idempotent.return_value = (sample_ref_adhoc, True)
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_data,
        correlation_id="corr-delete-dup",
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is True


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
def test_delete_ref_adhoc_skip_duplicate_check(mock_record_processed_event, mock_process_idempotent, db_session_mock, sample_ref_adhoc, sample_deleted_data):
    """Test delete when skipping duplicate idempotency check."""
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc
    mock_record_processed_event.return_value = None

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_data,
        correlation_id="corr-delete-skip",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    assert sample_ref_adhoc.IsDeleted == "1"
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.record_processed_event')
@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_skip_duplicate_record_fails(mock_process_idempotent, mock_record_processed_event, db_session_mock, sample_ref_adhoc, sample_deleted_data):
    """Test that delete still succeeds if record_processed_event fails while skipping duplicate check."""
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc
    mock_record_processed_event.side_effect = Exception("non-critical failure")

    result, was_duplicate = delete_ref_adhoc(
        db=db_session_mock,
        adhoc_id=1,
        adhoc_delete=sample_deleted_data,
        correlation_id="corr-delete-warning",
        skip_duplicate_check=True,
    )

    assert result == sample_ref_adhoc
    assert was_duplicate is False
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_adhoc_crud.IdempotencyService.process_idempotent')
def test_delete_ref_adhoc_process_raises(mock_process_idempotent, db_session_mock, sample_deleted_data):
    """Test that exceptions in process_idempotent trigger rollback."""
    mock_process_idempotent.side_effect = Exception("critical failure")

    with pytest.raises(Exception, match="critical failure"):
        delete_ref_adhoc(
            db=db_session_mock,
            adhoc_id=1,
            adhoc_delete=sample_deleted_data,
            correlation_id="corr-delete-error",
        )

    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()


# ==== get_ref_adhoc_by_id tests ====
def test_get_ref_adhoc_by_id_found(db_session_mock, sample_ref_adhoc):
    db_session_mock.query().filter().first.return_value = sample_ref_adhoc

    result = get_ref_adhoc_by_id(db=db_session_mock, adhoc_id=1)

    assert result == sample_ref_adhoc


def test_get_ref_adhoc_by_id_not_found(db_session_mock):
    db_session_mock.query().filter().first.return_value = None

    result = get_ref_adhoc_by_id(db=db_session_mock, adhoc_id=999)

    assert result is None


# ==== get_ref_adhoc_by_patient tests ====
def test_get_ref_adhoc_by_patient_found(db_session_mock, sample_ref_adhoc):
    db_session_mock.query().filter().all.return_value = [sample_ref_adhoc]

    result = get_ref_adhoc_by_patient(db=db_session_mock, patient_id=1)

    assert result == [sample_ref_adhoc]


def test_get_ref_adhoc_by_patient_empty(db_session_mock):
    db_session_mock.query().filter().all.return_value = []

    result = get_ref_adhoc_by_patient(db=db_session_mock, patient_id=999)

    assert result == []


# ==== get_idempotency_stats tests ====
def test_get_idempotency_stats(db_session_mock):
    expected_stats = {
        "total_processed_events": 10,
        "events_last_24h": 2,
        "events_with_errors": 1,
        "events_by_type": [{"event_type": "ADHOC_CREATED", "count": 5}],
        "latest_events": [],
        "stats_generated_at": "2025-10-12T00:00:00",
    }

    with mock.patch.object(IdempotencyService, "get_processing_stats", return_value=expected_stats) as mock_get_stats:
        result = get_idempotency_stats(db=db_session_mock)

        assert result == expected_stats
        mock_get_stats.assert_called_once_with(db_session_mock)


# ==== cleanup_old_processed_events tests ====
def test_cleanup_old_processed_events(db_session_mock):
    expected_deleted = 5
    older_than_days = 60

    with mock.patch.object(IdempotencyService, "cleanup_old_events", return_value=expected_deleted) as mock_cleanup:
        result = cleanup_old_processed_events(db=db_session_mock, older_than_days=older_than_days)

        assert result == expected_deleted
        mock_cleanup.assert_called_once_with(db_session_mock, older_than_days)


# ==== is_event_already_processed tests ====
def test_is_event_already_processed(db_session_mock):
    with mock.patch.object(IdempotencyService, "is_already_processed", return_value=True) as mock_is_processed:
        result = is_event_already_processed(db=db_session_mock, correlation_id="corr-123")

        assert result is True
        mock_is_processed.assert_called_once_with(db_session_mock, "corr-123")
