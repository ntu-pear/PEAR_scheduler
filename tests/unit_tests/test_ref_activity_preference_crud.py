import pytest
from unittest import mock
from datetime import datetime

from pear_schedule.crud.ref_activity_preference_crud import (
    create_ref_activity_preference,
    update_ref_activity_preference,
    delete_ref_activity_preference,
    get_idempotency_stats,
    cleanup_old_processed_events,
    is_event_already_processed
)

from pear_schedule.schemas.ref_activity_preference import RefActivityPreferenceCreate, RefActivityPreferenceUpdate, RefActivityPreferenceDelete
from pear_schedule.services.idempotency_service import IdempotencyService

@pytest.fixture
def sample_created_ref_activity_preference_data():
    return RefActivityPreferenceCreate(
        PatientID= 1,
        CentreActivityID=1,
        IsLike="0",
        IsDeleted="0",
        CentreActivityPreferenceID=1,
        CreatedDateTime=datetime(2025, 1, 1, 10, 0, 0),
        UpdatedDateTime=datetime(2025, 1, 1, 10, 0, 0),
        CreatedById="test_user",
        ModifiedById="test_user"
    )

@pytest.fixture
def sample_updated_ref_activity_preference_data():
    return RefActivityPreferenceUpdate(
        PatientId=1,
        ActivityId=1,
        IsDeleted=False,
        IsLike="1",
        UpdatedDateTime=datetime(2025, 1, 2, 10, 0, 0),
        ModifiedById="test_user"
    )

@pytest.fixture
def sample_deleted_ref_activity_preference_data():
    return RefActivityPreferenceDelete(
        UpdatedDateTime=datetime(2025, 1, 3, 10, 0, 0),
        ModifiedById="test_user"
    )

# ===== create_ref_activity_preference tests ===
@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_preference_success(mock_idempotent_process, db_session_mock, sample_created_ref_activity_preference_data, sample_activity_preference):
    """Should create a new activity preference successfully"""

    # Mock no existing preference found
    db_session_mock.query().filter().first.side_effect = [None, sample_activity_preference]

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation() # executes create_operation
        return result, False
    
    mock_idempotent_process.side_effect = fake_process_idempotent

    with mock.patch('pear_schedule.crud.ref_activity_preference_crud.RefActivityPreference', return_value=sample_activity_preference):
        result, was_duplicate = create_ref_activity_preference(
            db=db_session_mock,
            preference=sample_created_ref_activity_preference_data,
            correlation_id="corr_id_123",
            created_by="test_user"
        )

        assert result == sample_activity_preference
        assert was_duplicate is False
        db_session_mock.add.assert_called_once()
        db_session_mock.flush.assert_called_once()
        db_session_mock.commit.assert_called_once()
        mock_idempotent_process.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.record_processed_event')
def test_create_ref_activity_preference_skip_duplicate_check(mock_records_processed_event, db_session_mock, sample_created_ref_activity_preference_data, sample_activity_preference):
    """Should create a new activity preference without duplicate check"""

    # Mock no existing preference found
    db_session_mock.query().filter().first.return_value = None
    mock_records_processed_event.return_value = None

    with mock.patch('pear_schedule.crud.ref_activity_preference_crud.RefActivityPreference', return_value=sample_activity_preference):
        result, was_duplicate = create_ref_activity_preference(
            db=db_session_mock,
            preference=sample_created_ref_activity_preference_data,
            correlation_id="222", 
            created_by="test_user",
            skip_duplicate_check=True
        )

        assert result == sample_activity_preference
        assert was_duplicate is False
        db_session_mock.add.assert_called_once()
        db_session_mock.commit.assert_called_once()
        mock_records_processed_event.assert_called_once()
    
@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_preference_reactivate_soft_deleted(mock_idempotent_process, db_session_mock, sample_created_ref_activity_preference_data, sample_activity_preference):
    """Should reactivate a soft-deleted activity preference"""

    # Mock existing soft-deleted preference found
    soft_deleted_preference = sample_activity_preference
    soft_deleted_preference.IsDeleted = "1"
    db_session_mock.query().filter().first.side_effect = [soft_deleted_preference, soft_deleted_preference]

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False
    mock_idempotent_process.side_effect = fake_process_idempotent
    with mock.patch('pear_schedule.crud.ref_activity_preference_crud.RefActivityPreference', return_value=soft_deleted_preference):
        result, was_duplicate = create_ref_activity_preference(
            db=db_session_mock,
            preference=sample_created_ref_activity_preference_data,
            correlation_id="corr_id_456",
            created_by="test_user"
        )

        assert result == soft_deleted_preference
        assert result.IsDeleted == "0"
        assert was_duplicate is False
        db_session_mock.commit.assert_called_once()

def test_create_ref_activity_preference_duplicate_raises(db_session_mock, sample_created_ref_activity_preference_data, sample_activity_preference):
    """Should raise error when trying to create a duplicate activity preference"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    with pytest.raises(ValueError):
        create_ref_activity_preference(
            db=db_session_mock,
            preference=sample_created_ref_activity_preference_data,
            correlation_id="corr_id_789",
            created_by="test_user"
        )

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_preference_duplicate_detected(mock_idempotent_process, db_session_mock, sample_created_ref_activity_preference_data, sample_activity_preference):
    """Should return existing record if duplicate detected by idempotency service"""

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    result, was_duplicate = create_ref_activity_preference(
        db=db_session_mock,
        preference=sample_created_ref_activity_preference_data,
        correlation_id="corr_id_101",
        created_by="test_user"
    )

    assert was_duplicate is True
    assert result == sample_activity_preference

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_preference_foreign_key_patient_error(mock_idempotent_process, db_session_mock, sample_created_ref_activity_preference_data):
    """Should raise foreign key error for invalid PatientID"""

    # Mock no existing preference found
    db_session_mock.query().filter().first.return_value = None
    db_session_mock.add.side_effect = Exception("FOREIGN KEY constraint failed: REF_PATIENT")

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        create_ref_activity_preference(
            db=db_session_mock,
            preference=sample_created_ref_activity_preference_data,
            correlation_id="corr_id_102",
            created_by="test_user"
        )
    assert "foreign key" in str(exc_info.value).lower()
    db_session_mock.rollback.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_preference_foreign_key_activity_error(mock_idempotent_process, db_session_mock, sample_created_ref_activity_preference_data):
    """Should raise foreign key error for invalid ActivityID"""

    # Mock no existing preference found
    db_session_mock.query().filter().first.return_value = None
    db_session_mock.add.side_effect = Exception("FOREIGN KEY constraint failed: REF_ACTIVITY")

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        create_ref_activity_preference(
            db=db_session_mock,
            preference=sample_created_ref_activity_preference_data,
            correlation_id="corr_id_102",
            created_by="test_user"
        )
    assert "foreign key" in str(exc_info.value).lower()
    db_session_mock.rollback.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_preference_update_existing_active(mock_idempotent_process, db_session_mock, sample_created_ref_activity_preference_data, sample_activity_preference):
    """Should raise error when trying to create an preference that already exists as active"""

    # Mock existing active preference found
    sample_created_ref_activity_preference_data.CentreActivityPreferenceID = sample_activity_preference.CentreActivityPreferenceID
    sample_activity_preference.IsDeleted = "0"

    # Mock query to return existing active preference
    db_session_mock.query().filter().first.side_effect = [sample_activity_preference]

    def fake_process(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process

    with pytest.raises(ValueError, match="already exists"):
        create_ref_activity_preference(
            db=db_session_mock,
            preference=sample_created_ref_activity_preference_data,
            correlation_id="corr_id_update_active",
            created_by="test_user"
        )

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.record_processed_event')
def test_create_ref_activity_preference_skip_duplicate_check_record_fail(mock_record_processed_event, db_session_mock, sample_created_ref_activity_preference_data, sample_activity_preference):
    """Skip duplicate check but record_processed_event fails (non-critical)"""

    db_session_mock.query().filter().first.return_value = None
    mock_record_processed_event.side_effect = Exception("DB not reachable")

    with mock.patch('pear_schedule.crud.ref_activity_preference_crud.RefActivityPreference', return_value=sample_activity_preference):
        result, was_duplicate = create_ref_activity_preference(
            db=db_session_mock,
            preference=sample_created_ref_activity_preference_data,
            correlation_id="corr_skip_fail",
            created_by="test_user",
            skip_duplicate_check=True
        )

    assert result == sample_activity_preference
    assert was_duplicate is False
    db_session_mock.add.assert_called_once()
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_preference_duplicate_no_id(mock_idempotent_process, db_session_mock, sample_created_ref_activity_preference_data, sample_activity_preference):
    """Covers else branch of was_duplicate handling when CentreActivityPreferenceID is None"""

    # Remove CentreActivityPreferenceID to trigger else branch
    sample_created_ref_activity_preference_data.CentreActivityPreferenceID = None

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True  # was_duplicate=True

    mock_idempotent_process.side_effect = fake_process_idempotent

    # Mock existing record returned by else-branch query
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    result, was_duplicate = create_ref_activity_preference(
        db=db_session_mock,
        preference=sample_created_ref_activity_preference_data,
        correlation_id="corr_no_id_dup",
        created_by="test_user"
    )

    assert was_duplicate is True
    assert result == sample_activity_preference

# ==== update_ref_activity_preference tests ====
@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_preference_success(mock_idempotent_process, db_session_mock, sample_updated_ref_activitiy_preference_data, sample_activity_preference):
    """Should update an existing activity preference successfully"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False
    mock_idempotent_process.side_effect = fake_process_idempotent
    result, was_duplicate = update_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_update=sample_updated_ref_activitiy_preference_data,
        correlation_id="corr_update_123",
    )
    assert result == sample_activity_preference
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_preference_not_found(mock_idempotent_process, db_session_mock, sample_updated_ref_activitiy_preference_data):
    """Should raise error when trying to update a non-existent activity preference"""

    # Mock no existing preference found
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent
    result, was_duplicate = update_ref_activity_preference(
        db=db_session_mock,
        preference_id=999,
        preference_update=sample_updated_ref_activitiy_preference_data,
        correlation_id="corr_update_999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_preference_duplicate_event(mock_idempotent_process, db_session_mock, sample_updated_ref_activitiy_preference_data, sample_activity_preference):
    """Should return existing record if duplicate detected by idempotency service during update"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_update=sample_updated_ref_activitiy_preference_data,
        correlation_id="corr_update_dup",
    )

    assert was_duplicate is True
    assert result == sample_activity_preference
    db_session_mock.commit.assert_not_called()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.record_processed_event')
def test_update_ref_activity_preference_skip_duplicate_check(mock_record_processed_event, db_session_mock, sample_updated_ref_activitiy_preference_data, sample_activity_preference):
    """Should update an existing activity preference without duplicate check"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    mock_record_processed_event.return_value = None

    result, was_duplicate = update_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_update=sample_updated_ref_activitiy_preference_data,
        correlation_id="corr_update_no_dup_check",
        skip_duplicate_check=True
    )

    assert result == sample_activity_preference
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.record_processed_event')
def test_update_ref_activity_preference_skip_duplicate_check_record_fail(mock_record_processed_event, db_session_mock, sample_updated_ref_activitiy_preference_data, sample_activity_preference):
    """Skip duplicate check but record_processed_event fails (non-critical)"""

    db_session_mock.query().filter().first.return_value = sample_activity_preference
    mock_record_processed_event.side_effect = Exception("DB not reachable")

    result, was_duplicate = update_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_update=sample_updated_ref_activitiy_preference_data,
        correlation_id="corr_update_skip_fail",
        skip_duplicate_check=True
    )

    assert result == sample_activity_preference
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_preference_error(mock_idempotent_process, db_session_mock, sample_updated_ref_activitiy_preference_data, sample_activity_preference):
    """Should handle error during update operation"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference
    db_session_mock.commit.side_effect = Exception("DB not reachable")

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        update_ref_activity_preference(
            db=db_session_mock,
            preference_id=1,
            preference_update=sample_updated_ref_activitiy_preference_data,
            correlation_id="corr_update_error",
        )
    assert "DB not reachable" in str(exc_info.value)
    db_session_mock.rollback.assert_called_once()

# ==== delete_ref_activity_preference tests ====
@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_preference_success(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_preference_data, sample_activity_preference):
    """Should soft delete an existing activity preference successfully"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    # Mock idempotency service returns not duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_delete=sample_deleted_ref_activity_preference_data,
        correlation_id="corr_delete_123",
    )

    assert result == sample_activity_preference
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_preference_not_found(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_preference_data):
    """Should raise error when trying to delete a non-existent activity preference"""

    # Mock no existing preference found
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity_preference(
        db=db_session_mock,
        preference_id=999,
        preference_delete=sample_deleted_ref_activity_preference_data,
        correlation_id="corr_delete_999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_preference_already_deleted(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_preference_data, sample_activity_preference):
    """Should handle already deleted activity preference gracefully"""

    # Mock existing preference found and already deleted
    sample_activity_preference.IsDeleted = "1"
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_delete=sample_deleted_ref_activity_preference_data,
        correlation_id="corr_delete_already",
    )

    assert result == sample_activity_preference
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_preference_duplicate_event(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_preference_data, sample_activity_preference):
    """Should return existing record if duplicate detected by idempotency service during delete"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    # Mock idempotency service returns duplicate
    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_delete=sample_deleted_ref_activity_preference_data,
        correlation_id="corr_delete_dup",
    )

    assert was_duplicate is True
    assert result == sample_activity_preference
    db_session_mock.commit.assert_not_called()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.record_processed_event')
def test_delete_ref_activity_preference_skip_duplicate_check(mock_record_processed_event, db_session_mock, sample_deleted_ref_activity_preference_data, sample_activity_preference):
    """Should soft delete an existing activity preference without duplicate check"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference

    mock_record_processed_event.return_value = None

    result, was_duplicate = delete_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_delete=sample_deleted_ref_activity_preference_data,
        correlation_id="corr_delete_no_dup_check",
        skip_duplicate_check=True
    )

    assert result == sample_activity_preference
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.record_processed_event')
def test_delete_ref_activity_preference_skip_duplicate_check_record_fail(mock_record_processed_event, db_session_mock, sample_deleted_ref_activity_preference_data, sample_activity_preference):
    """Skip duplicate check but record_processed_event fails (non-critical)"""

    db_session_mock.query().filter().first.return_value = sample_activity_preference
    mock_record_processed_event.side_effect = Exception("DB not reachable")

    result, was_duplicate = delete_ref_activity_preference(
        db=db_session_mock,
        preference_id=1,
        preference_delete=sample_deleted_ref_activity_preference_data,
        correlation_id="corr_delete_skip_fail",
        skip_duplicate_check=True
    )

    assert result == sample_activity_preference
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()
    mock_record_processed_event.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_preference_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_preference_error(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_preference_data, sample_activity_preference):
    """Should handle error during delete operation"""

    # Mock existing preference found
    db_session_mock.query().filter().first.return_value = sample_activity_preference
    db_session_mock.commit.side_effect = Exception("DB not reachable")

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        delete_ref_activity_preference(
            db=db_session_mock,
            preference_id=1,
            preference_delete=sample_deleted_ref_activity_preference_data,
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