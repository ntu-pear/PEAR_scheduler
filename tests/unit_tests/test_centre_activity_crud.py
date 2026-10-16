import pytest
from unittest import mock
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from pear_schedule.crud.ref_centre_activity_crud import (
    ActivityNotSyncedError,
    create_ref_centre_activity,
    update_ref_centre_activity,
    delete_ref_centre_activity,
    get_idempotency_stats,
    cleanup_old_processed_events,
    is_event_already_processed
)
from pear_schedule.schemas.ref_centre_activity import RefCentreActivityCreate, RefCentreActivityDelete, RefCentreActivityUpdate
from pear_schedule.services.idempotency_service import IdempotencyService

@pytest.fixture
def sample_created_ref_centre_activity_data():
    return RefCentreActivityCreate(
        CentreActivityID=1,
        ActivityID=1,
        IsCompulsory="0",
        IsFixed="0",
        IsGroup="0",
        StartDate="2025-10-10",
        EndDate="2025-10-13",
        MinDuration=30,
        MaxDuration=60,
        MinPeopleReq=1,
        FixedTimeSlots=None,
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )
@pytest.fixture
def sample_updated_ref_centre_activity_data():
    return RefCentreActivityUpdate(
        ActivityID=10,
        IsDeleted="0",
        IsCompulsory="1",
        IsFixed="1",
        IsGroup="1",
        StartDate="2025-10-10",
        EndDate="2025-11-01",
        MinDuration=45,
        MaxDuration=90,
        MinPeopleReq=5,
        FixedTimeSlots="09:00-10:00,14:00-15:00",
        UpdatedDateTime=datetime.now(),
        ModifiedById="test_user"
    )

@pytest.fixture
def sample_deleted_ref_centre_activity_data():
    return RefCentreActivityDelete(
        UpdatedDateTime=datetime.now(),
        ModifiedById="test_user"
    )

# ==== create_ref_centre_activity tests ====
@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_create_ref_centre_activity_success(mock_idempotent_process, db_session_mock, sample_created_ref_centre_activity_data, sample_centre_activity):
    """Should create a new centre activity successfully"""

    # Mock no existing centre activity found
    db_session_mock.query().filter().first.side_effect = [None, (1,), sample_centre_activity]  # existing, parent activity, created

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation() # executes create_operation
        return result, False
    
    mock_idempotent_process.side_effect = fake_process_idempotent

    with mock.patch('pear_schedule.crud.ref_centre_activity_crud.RefCentreActivity', return_value=sample_centre_activity):
        result, was_duplicate = create_ref_centre_activity(
            db=db_session_mock,
            centre_activity=sample_created_ref_centre_activity_data,
            correlation_id="corr_id_123",
            created_by="test_user"
        )

        assert result == sample_centre_activity
        assert was_duplicate is False
        db_session_mock.flush.assert_called_once()
        db_session_mock.commit.assert_called_once()
        mock_idempotent_process.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_create_ref_centre_activity_skip_duplicate_check(mock_records_processed_event, db_session_mock, sample_created_ref_centre_activity_data, sample_centre_activity):
    """Should create a new centre activity without duplicate check"""

    # Mock no existing centre activity found
    db_session_mock.query().filter().first.side_effect = [None, (1,), sample_centre_activity]  # existing, parent activity, created

    mock_records_processed_event.return_value = None

    with mock.patch('pear_schedule.crud.ref_centre_activity_crud.RefCentreActivity', return_value=sample_centre_activity):
        result, was_duplicate = create_ref_centre_activity(
            db=db_session_mock,
            centre_activity=sample_created_ref_centre_activity_data,
            correlation_id="222", 
            created_by="test_user",
            skip_duplicate_check=True
        )

        assert result == sample_centre_activity
        assert was_duplicate is False
        db_session_mock.commit.assert_called_once()
        mock_records_processed_event.assert_called_once()
    
def test_create_ref_centre_activity_duplicate_raises(db_session_mock, sample_created_ref_centre_activity_data, sample_centre_activity):
    """Should raise error when trying to create a duplicate centre activity"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    with pytest.raises(ValueError):
        create_ref_centre_activity(
            db=db_session_mock,
            centre_activity=sample_created_ref_centre_activity_data,
            correlation_id="corr_id_789",
            created_by="test_user"
        )

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_create_ref_centre_activity_duplicate_detected(mock_idempotent_process, db_session_mock, sample_created_ref_centre_activity_data, sample_centre_activity):
    """Should return existing record if duplicate detected by idempotency service"""

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    result, was_duplicate = create_ref_centre_activity(
        db=db_session_mock,
        centre_activity=sample_created_ref_centre_activity_data,
        correlation_id="corr_id_101",
        created_by="test_user"
    )

    assert was_duplicate is True
    assert result == sample_centre_activity

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_create_ref_centre_activity_skip_duplicate_check_record_fail(mock_record_processed_event, db_session_mock, sample_created_ref_centre_activity_data, sample_centre_activity):
    """Skip duplicate check but record_processed_event fails (non-critical)"""

    db_session_mock.query().filter().first.side_effect = [None, (1,), sample_centre_activity]  # existing, parent activity, created

    mock_record_processed_event.side_effect = Exception("DB not reachable")

    with mock.patch('pear_schedule.crud.ref_centre_activity_crud.RefCentreActivity', return_value=sample_centre_activity):
        result, was_duplicate = create_ref_centre_activity(
            db=db_session_mock,
            centre_activity=sample_created_ref_centre_activity_data,
            correlation_id="corr_skip_fail",
            created_by="test_user",
            skip_duplicate_check=True
        )

    assert result == sample_centre_activity
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

def test_create_ref_centre_activity_creation_fails(db_session_mock, sample_created_ref_centre_activity_data):
    """Should raise Exception if centre activity creation verification fails"""

    # Both queries return None → simulate failed insert
    db_session_mock.query().filter().first.side_effect = [None, (1,), None]

    with pytest.raises(Exception, match="Failed to create centre activity"):
        create_ref_centre_activity(
            db=db_session_mock,
            centre_activity=sample_created_ref_centre_activity_data,
            correlation_id="corr_fail_1",
            created_by="test_user",
            skip_duplicate_check=True
        )

# ==== activity not synced yet ====
def test_activity_not_synced_error_is_retryable_kind():
    # ValueError is marked processed as permanent, IntegrityError is read as a duplicate
    assert not issubclass(ActivityNotSyncedError, ValueError)
    assert not issubclass(ActivityNotSyncedError, IntegrityError)


@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.mark_as_processed')
@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.is_already_processed', return_value=False)
def test_create_before_activity_synced_raises(mock_processed, mock_mark, db_session_mock, sample_created_ref_centre_activity_data):
    """Used to hit the FK, which process_idempotent took as a duplicate, so the event was dropped"""
    db_session_mock.query().filter().first.side_effect = [None, None]  # not there yet, activity missing

    with pytest.raises(ActivityNotSyncedError):
        create_ref_centre_activity(
            db=db_session_mock,
            centre_activity=sample_created_ref_centre_activity_data,
            correlation_id="corr_parent_missing",
            created_by="test_user"
        )

    db_session_mock.execute.assert_not_called()
    db_session_mock.commit.assert_not_called()
    db_session_mock.rollback.assert_called_once()
    mock_mark.assert_not_called()


@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_create_sync_without_recording(mock_record, db_session_mock, sample_created_ref_centre_activity_data, sample_centre_activity):
    """The sync update already recorded the event, so its fallback create doesn't record it again"""
    db_session_mock.query().filter().first.side_effect = [None, (1,), sample_centre_activity]

    result, was_duplicate = create_ref_centre_activity(
        db=db_session_mock,
        centre_activity=sample_created_ref_centre_activity_data,
        correlation_id="corr_sync",
        created_by="test_user",
        skip_duplicate_check=True,
        record_event=False
    )

    assert result == sample_centre_activity and was_duplicate is False
    db_session_mock.execute.assert_called_once()
    mock_record.assert_not_called()


@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_update_to_activity_not_synced_raises(mock_record, db_session_mock, sample_updated_ref_centre_activity_data, sample_centre_activity):
    db_session_mock.query().filter().first.side_effect = [sample_centre_activity, None]  # row, new activity 10 missing

    with pytest.raises(ActivityNotSyncedError):
        update_ref_centre_activity(
            db=db_session_mock,
            centre_activity_id=1,
            centre_activity_update=sample_updated_ref_centre_activity_data,
            correlation_id="corr_upd_parent",
            skip_duplicate_check=True
        )

    assert sample_centre_activity.ActivityID == 1
    db_session_mock.commit.assert_not_called()


# ==== update_ref_centre_activity tests ====
@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_centre_activity_success(mock_idempotent_process, db_session_mock, sample_updated_ref_centre_activity_data, sample_centre_activity):
    """Should update an existing centre activity successfully"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False
    mock_idempotent_process.side_effect = fake_process_idempotent
    result, was_duplicate = update_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_update=sample_updated_ref_centre_activity_data,
        correlation_id="corr_update_123",
    )
    assert result == sample_centre_activity
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_centre_activity_not_found(mock_idempotent_process, db_session_mock, sample_updated_ref_centre_activity_data):
    """Should raise error when trying to update a non-existent centre activity"""

    # Mock no existing centre_activity found
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent
    result, was_duplicate = update_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=999,
        centre_activity_update=sample_updated_ref_centre_activity_data,
        correlation_id="corr_update_999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_centre_activity_duplicate_event(mock_idempotent_process, db_session_mock, sample_updated_ref_centre_activity_data, sample_centre_activity):
    """Should return existing record if duplicate detected by idempotency service during update"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_update=sample_updated_ref_centre_activity_data,
        correlation_id="corr_update_dup",
    )

    assert was_duplicate is True
    assert result == sample_centre_activity
    db_session_mock.commit.assert_not_called()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.is_already_processed', return_value=False)
@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_update_ref_centre_activity_skip_duplicate_check(mock_record_processed_event, mock_processed, db_session_mock, sample_updated_ref_centre_activity_data, sample_centre_activity):
    """Should update an existing centre activity without duplicate check"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    mock_record_processed_event.return_value = None

    result, was_duplicate = update_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_update=sample_updated_ref_centre_activity_data,
        correlation_id="corr_update_no_dup_check",
        skip_duplicate_check=True
    )

    assert result == sample_centre_activity
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.is_already_processed', return_value=True)
@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_update_sync_redelivery_is_not_recorded_twice(mock_record, mock_processed, db_session_mock, sample_updated_ref_centre_activity_data):
    """A second insert of the same event used to fail the flush, so the commit and every retry failed"""
    db_session_mock.query().filter().first.return_value = None  # still missing, the fallback create will retry

    result, was_duplicate = update_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=40,
        centre_activity_update=sample_updated_ref_centre_activity_data,
        correlation_id="corr_sync_again",
        skip_duplicate_check=True
    )

    assert result is None and was_duplicate is False
    mock_record.assert_not_called()
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.is_already_processed', return_value=False)
@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_update_ref_centre_activity_skip_duplicate_check_record_fail(mock_record_processed_event, mock_processed, db_session_mock, sample_updated_ref_centre_activity_data, sample_centre_activity):
    """Skip duplicate check but record_processed_event fails (non-critical)"""

    db_session_mock.query().filter().first.return_value = sample_centre_activity
    mock_record_processed_event.side_effect = Exception("DB not reachable")

    result, was_duplicate = update_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_update=sample_updated_ref_centre_activity_data,
        correlation_id="corr_update_skip_fail",
        skip_duplicate_check=True
    )

    assert result == sample_centre_activity
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_centre_activity_error(mock_idempotent_process, db_session_mock, sample_updated_ref_centre_activity_data, sample_centre_activity):
    """Should handle error during update operation"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity
    db_session_mock.commit.side_effect = Exception("DB not reachable")

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        update_ref_centre_activity(
            db=db_session_mock,
            centre_activity_id=1,
            centre_activity_update=sample_updated_ref_centre_activity_data,
            correlation_id="corr_update_error",
        )
    assert "DB not reachable" in str(exc_info.value)
    db_session_mock.rollback.assert_called_once()

# ==== delete_ref_centre_activity tests ====
@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_centre_activity_success(mock_idempotent_process, db_session_mock, sample_deleted_ref_centre_activity_data, sample_centre_activity):
    """Should soft delete an existing centre activity successfully"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_delete=sample_deleted_ref_centre_activity_data,
        correlation_id="corr_delete_123",
    )

    assert result == sample_centre_activity
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_centre_activity_not_found(mock_idempotent_process, db_session_mock, sample_deleted_ref_centre_activity_data):
    """Should raise error when trying to delete a non-existent centre activity"""

    # Mock no existing centre_activity found
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=999,
        centre_activity_delete=sample_deleted_ref_centre_activity_data,
        correlation_id="corr_delete_999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_centre_activity_already_deleted(mock_idempotent_process, db_session_mock, sample_deleted_ref_centre_activity_data, sample_centre_activity):
    """Should handle already deleted centre activity gracefully"""

    # Mock existing centre_activity found and already deleted
    sample_centre_activity.IsDeleted = "1"
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_delete=sample_deleted_ref_centre_activity_data,
        correlation_id="corr_delete_already",
    )

    assert result == sample_centre_activity
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_centre_activity_duplicate_event(mock_idempotent_process, db_session_mock, sample_deleted_ref_centre_activity_data, sample_centre_activity):
    """Should return existing record if duplicate detected by idempotency service during delete"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_delete=sample_deleted_ref_centre_activity_data,
        correlation_id="corr_delete_dup",
    )

    assert was_duplicate is True
    assert result == sample_centre_activity
    db_session_mock.commit.assert_not_called()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_delete_ref_centre_activity_skip_duplicate_check(mock_record_processed_event, db_session_mock, sample_deleted_ref_centre_activity_data, sample_centre_activity):
    """Should soft delete an existing centre activity without duplicate check"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity

    mock_record_processed_event.return_value = None

    result, was_duplicate = delete_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_delete=sample_deleted_ref_centre_activity_data,
        correlation_id="corr_delete_no_dup_check",
        skip_duplicate_check=True
    )

    assert result == sample_centre_activity
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.record_processed_event')
def test_delete_ref_centre_activity_skip_duplicate_check_record_fail(mock_record_processed_event, db_session_mock, sample_deleted_ref_centre_activity_data, sample_centre_activity):
    """Skip duplicate check but record_processed_event fails (non-critical)"""

    db_session_mock.query().filter().first.return_value = sample_centre_activity
    mock_record_processed_event.side_effect = Exception("DB not reachable")

    result, was_duplicate = delete_ref_centre_activity(
        db=db_session_mock,
        centre_activity_id=1,
        centre_activity_delete=sample_deleted_ref_centre_activity_data,
        correlation_id="corr_delete_skip_fail",
        skip_duplicate_check=True
    )

    assert result == sample_centre_activity
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_centre_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_centre_activity_error(mock_idempotent_process, db_session_mock, sample_deleted_ref_centre_activity_data, sample_centre_activity):
    """Should handle error during delete operation"""

    # Mock existing centre_activity found
    db_session_mock.query().filter().first.return_value = sample_centre_activity
    db_session_mock.commit.side_effect = Exception("DB not reachable")

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        delete_ref_centre_activity(
            db=db_session_mock,
            centre_activity_id=1,
            centre_activity_delete=sample_deleted_ref_centre_activity_data,
            correlation_id="corr_delete_error",
        )
    assert "DB not reachable" in str(exc_info.value)
    db_session_mock.rollback.assert_called_once()
    
# ===== get_idempotency_stats tests ===
def test_get_idempotency_stats(db_session_mock):
    """Test fetching idempotency stats. Makes sure that get_idempotency_stats calls the service and returns its data."""
    expected_stats = {
        "total_processed_events": 10,
        "events_last_24h": 2,
        "events_with_errors": 1,
        "events_by_type": [{"event_type": "ACTIVITY_CREATED", "count": 5}],
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