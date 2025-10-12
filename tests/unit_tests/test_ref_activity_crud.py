import pytest
from unittest import mock
from datetime import datetime

from pear_schedule.crud.ref_activity_crud import (
    create_ref_activity,
    update_ref_activity,
    delete_ref_activity,
    get_ref_activities,
    get_ref_activity_by_id,
    check_activity_exists,
    get_idempotency_stats,
    cleanup_old_processed_events,
    is_event_already_processed
)
from pear_schedule.schemas.ref_activity import RefActivityCreate, RefActivityUpdate, RefActivityDelete
from pear_schedule.services.idempotency_service import IdempotencyService

@pytest.fixture
def sample_updated_ref_data():
    return RefActivityUpdate(
        ActivityTitle="Updated Title",
        ActivityDesc="Updated Desc",
        IsDeleted=False,
        UpdatedDateTime=datetime.now(),
        ModifiedById="test_user"
    )

@pytest.fixture
def sample_deleted_ref_data():
    return RefActivityDelete(
        ActivityTitle="Deleted Title",
        ActivityDesc="Deleted Desc",
        IsDeleted="1",
        UpdatedDateTime=datetime.now(),
        ModifiedById="test_user"
    )

# ==== create_ref_activity tests ===
@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_success(mock_idempotency_process, db_session_mock, sample_ref_activity):
    """Test successful creation of a reference activity."""

    # Mock no existing activity
    db_session_mock.query().filter().first.side_effect = [None, sample_ref_activity]

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation() # executes create_operation
        return result, False

    # Mock idempotency service returns not duplicate
    mock_idempotency_process.side_effect = fake_process_idempotent

    activity_data = RefActivityCreate(
            ActivityID=1,
            ActivityTitle="Morning Exercise",
            ActivityDesc="Light exercise for seniors",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )

    result, was_duplicate = create_ref_activity(
        db=db_session_mock,
        activity=activity_data,
        correlation_id="corr-123",
        created_by="test_user"
    )

    assert result == sample_ref_activity
    assert was_duplicate is False
    db_session_mock.execute.assert_called_once()
    db_session_mock.flush.assert_called_once()
    db_session_mock.commit.assert_called_once()
    mock_idempotency_process.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_existing_raises_valueerror(mock_process_idempotent, db_session_mock, sample_ref_activity):
    """Test ValueError when activity already exists."""
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        # directly call operation() which will raise ValueError inside
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    activity_data = RefActivityCreate(
        ActivityID=1,
        ActivityTitle="Morning Exercise",
        ActivityDesc="Light exercise for seniors",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )

    with pytest.raises(ValueError, match="already exists"):
        create_ref_activity(
            db=db_session_mock,
            activity=activity_data,
            correlation_id="corr-123",
            created_by="test_user"
        )

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_fails_to_fetch_created(mock_process_idempotent, db_session_mock):
    """Test Exception when created activity not found after insert."""
    # first query finds nothing (proceed to insert)
    db_session_mock.query().filter().first.side_effect = [None, None]

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    activity_data = RefActivityCreate(
        ActivityID=99,
        ActivityTitle="Missing Record",
        ActivityDesc="Simulate missing",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )

    with pytest.raises(Exception, match="Failed to create activity"):
        create_ref_activity(
            db=db_session_mock,
            activity=activity_data,
            correlation_id="corr-999",
            created_by="test_user"
        )

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_duplicate_returns_existing(mock_process_idempotent, db_session_mock, sample_ref_activity):
    """Test duplicate idempotent event returns existing activity."""
    # mock idempotent call returns existing + duplicate=True
    mock_process_idempotent.return_value = (sample_ref_activity, True)
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    activity_data = RefActivityCreate(
        ActivityID=1,
        ActivityTitle="Morning Exercise",
        ActivityDesc="Light exercise for seniors",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )

    result, was_duplicate = create_ref_activity(
        db=db_session_mock,
        activity=activity_data,
        correlation_id="corr-dup",
        created_by="test_user"
    )

    assert result == sample_ref_activity
    assert was_duplicate is True

# ==== update_ref_activity tests ===
@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_success(mock_idempotency_process, db_session_mock, sample_ref_activity, sample_updated_ref_data):
    """Test successful update of a reference activity."""
    # Mock existing activity found
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation() # executes update_operation
        return result, False
    mock_idempotency_process.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_update=sample_updated_ref_data,
        correlation_id="corr-update-123",
    )

    assert result == sample_ref_activity
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_not_found(mock_process_idempotent, db_session_mock, sample_updated_ref_data):
    """Test when activity to update not found."""
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_activity(
        db=db_session_mock,
        activity_id=999,
        activity_update=sample_updated_ref_data,
        correlation_id="corr-update-999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_duplicate_event(mock_process_idempotent, db_session_mock, sample_ref_activity, sample_updated_ref_data):
    """Test duplicate idempotent event returns existing activity."""
    # mock idempotent call returns existing + duplicate=True
    mock_process_idempotent.return_value = (sample_ref_activity, True)
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    result, was_duplicate = update_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_update=sample_updated_ref_data,
        correlation_id="corr-update-dup",
    )

    assert result == sample_ref_activity
    assert was_duplicate is True

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.record_processed_event')
def test_update_ref_activity_skip_duplicate_check(mock_record_processed_event, mock_process_idempotent, db_session_mock, sample_ref_activity, sample_updated_ref_data):
    """Test update when skipping duplicate idempotency check."""
    # Mock existing activity found
    db_session_mock.query().filter().first.return_value = sample_ref_activity
    mock_record_processed_event.return_value = None

    result, was_duplicate = update_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_update=sample_updated_ref_data,
        correlation_id="corr-update-skip",
        skip_duplicate_check=True
    )

    assert result == sample_ref_activity
    assert was_duplicate is False
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.record_processed_event')
@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_skip_duplicate_record_fails(mock_process_idempotent, mock_record_processed_event, db_session_mock, sample_ref_activity, sample_updated_ref_data):
    """Test that a warning is logged if record_processed_event fails while skipping duplicate check."""
    # Mock existing activity
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    # Make record_processed_event raise exception
    mock_record_processed_event.side_effect = Exception("non-critical failure")

    result, was_duplicate = update_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_update=sample_updated_ref_data,
        correlation_id="corr-update-warning",
        skip_duplicate_check=True
    )

    # Activity should still be returned correctly
    assert result == sample_ref_activity
    assert was_duplicate is False
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_process_raises(mock_process_idempotent, db_session_mock, sample_updated_ref_data):
    """Test that exceptions in process_idempotent trigger rollback and logger.error."""
    # Make process_idempotent raise exception
    mock_process_idempotent.side_effect = Exception("critical failure")

    with pytest.raises(Exception, match="critical failure"):
        update_ref_activity(
            db=db_session_mock,
            activity_id=1,
            activity_update=sample_updated_ref_data,
            correlation_id="corr-update-error"
        )

    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()

# ==== delete_ref_activity tests ===
@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_success(mock_idempotency_process, db_session_mock, sample_ref_activity, sample_deleted_ref_data):
    """Test soft deletion of a reference activity."""
    # Mock existing activity found
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()
        return result, False
    mock_idempotency_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_delete=sample_deleted_ref_data,
        correlation_id="corr-delete-123",
    )

    assert result == sample_ref_activity
    assert was_duplicate is False
    assert sample_ref_activity.IsDeleted == "1"
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_not_exists(mock_process_idempotent, db_session_mock, sample_deleted_ref_data):
    """Test deletion when activity not found."""
    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_process_idempotent.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity(
        db=db_session_mock,
        activity_id=999,
        activity_delete=sample_deleted_ref_data,
        correlation_id="corr-delete-999",
    )

    assert result is None
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_already_deleted(mock_process_idempotent, db_session_mock, sample_ref_activity, sample_deleted_ref_data):
    """Test deletion when activity is already marked as deleted."""
    # Mock existing activity already deleted
    sample_ref_activity.IsDeleted = "1"
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False
    mock_process_idempotent.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_delete=sample_deleted_ref_data,
        correlation_id="corr-delete-already",
    )

    assert result == sample_ref_activity
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_duplicate_event(mock_process_idempotent, db_session_mock, sample_ref_activity, sample_deleted_ref_data):
    """Test duplicate idempotent event returns existing activity."""
    # mock idempotent call returns existing + duplicate=True
    mock_process_idempotent.return_value = (sample_ref_activity, True)
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    result, was_duplicate = delete_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_delete=sample_deleted_ref_data,
        correlation_id="corr-delete-dup",
    )

    assert result == sample_ref_activity
    assert was_duplicate is True

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.record_processed_event')
def test_delete_ref_activity_skip_duplicate_check(mock_record_processed_event, mock_process_idempotent, db_session_mock, sample_ref_activity, sample_deleted_ref_data):
    """Test delete when skipping duplicate idempotency check."""
    # Mock existing activity found
    db_session_mock.query().filter().first.return_value = sample_ref_activity
    mock_record_processed_event.return_value = None

    result, was_duplicate = delete_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_delete=sample_deleted_ref_data,
        correlation_id="corr-delete-skip",
        skip_duplicate_check=True
    )

    assert result == sample_ref_activity
    assert was_duplicate is False
    assert sample_ref_activity.IsDeleted == "1"
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.record_processed_event')
@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_skip_duplicate_record_fails(mock_process_idempotent, mock_record_processed_event, db_session_mock, sample_ref_activity, sample_deleted_ref_data):
    """Test that a warning is logged if record_processed_event fails while skipping duplicate check."""
    # Mock existing activity
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    # Make record_processed_event raise exception
    mock_record_processed_event.side_effect = Exception("non-critical failure")

    result, was_duplicate = delete_ref_activity(
        db=db_session_mock,
        activity_id=1,
        activity_delete=sample_deleted_ref_data,
        correlation_id="corr-delete-warning",
        skip_duplicate_check=True
    )

    # Activity should still be returned correctly
    assert result == sample_ref_activity
    assert was_duplicate is False
    mock_process_idempotent.assert_not_called()
    mock_record_processed_event.assert_called_once()
    db_session_mock.commit.assert_called_once()

@mock.patch('pear_schedule.crud.ref_activity_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_process_raises(mock_process_idempotent, db_session_mock, sample_deleted_ref_data):
    """Test that exceptions in process_idempotent trigger rollback and logger.error."""
    # Make process_idempotent raise exception
    mock_process_idempotent.side_effect = Exception("critical failure")

    with pytest.raises(Exception, match="critical failure"):
        delete_ref_activity(
            db=db_session_mock,
            activity_id=1,
            activity_delete=sample_deleted_ref_data,
            correlation_id="corr-delete-error"
        )

    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()

# ==== get_ref_activity_by_id tests ===
def test_get_ref_activity_by_id_found(db_session_mock, sample_ref_activity):
    """Test fetching an activity by ID when it exists."""
    db_session_mock.query().filter().first.return_value = sample_ref_activity

    result = get_ref_activity_by_id(db=db_session_mock, activity_id=1)

    assert result == sample_ref_activity
    db_session_mock.query().filter().first.assert_called_once()

def test_get_ref_activity_by_id_not_found(db_session_mock):
    """Test fetching an activity by ID when it does not exist."""
    db_session_mock.query().filter().first.return_value = None

    result = get_ref_activity_by_id(db=db_session_mock, activity_id=999)

    assert result is None
    db_session_mock.query().filter().first.assert_called_once()

# ==== get_ref_activities tests ===
def test_get_ref_activities_no_filters(db_session_mock, sample_ref_activity):
    """Test fetching all activities with pagination without filters."""
    db_session_mock.query().filter().all.return_value = [sample_ref_activity]

    count_filter_mock = db_session_mock.query.return_value.filter.return_value
    count_filter_mock.scalar.return_value = 1
    
    activities, total_records, total_pages = get_ref_activities(
        db=db_session_mock,
        page_no=0,
        page_size=10
    )
    
    assert len(activities) == 1
    assert activities[0] == sample_ref_activity
    assert total_records == 1
    assert total_pages == 1

def test_get_ref_activities_with_title_filter(db_session_mock, sample_ref_activity):
    """Test fetching activities with title filter."""
    db_session_mock.query().filter().all.return_value = [sample_ref_activity]

    count_filter_mock = db_session_mock.query.return_value.filter.return_value
    count_filter_mock.scalar.return_value = 1

    activities, total_records, total_pages = get_ref_activities(
        db=db_session_mock,
        title_filter="Morning",
        page_no=0,
        page_size=10
    )

    assert len(activities) == 1
    assert activities[0] == sample_ref_activity
    assert total_records == 1
    assert total_pages == 1

def test_get_ref_activities_pagination(db_session_mock, sample_ref_activity):
    """Test fetching activities with pagination."""
    db_session_mock.query().filter().all.return_value = [sample_ref_activity]

    count_filter_mock = db_session_mock.query.return_value.filter.return_value
    count_filter_mock.scalar.return_value = 35  # Simulate 15 total records

    activities, total_records, total_pages = get_ref_activities(
        db=db_session_mock,
        page_no=2,
        page_size=10
    )

    assert len(activities) == 1
    assert activities[0] == sample_ref_activity
    assert total_records == 35
    assert total_pages == 4  # 35 records with page size 10 should yield 2 pages

# ===== check_activity_exists tests ===
def test_check_activity_exists_true(db_session_mock):
    """Test activity exists returns True."""
    db_session_mock.query.return_value.filter.return_value.scalar.return_value = 1

    exists = check_activity_exists(db=db_session_mock, activity_id=1)

    assert exists is True
    db_session_mock.query.return_value.filter.return_value.scalar.assert_called_once()


def test_check_activity_exists_false(db_session_mock):
    """Test activity exists returns False."""
    db_session_mock.query.return_value.filter.return_value.scalar.return_value = 0

    exists = check_activity_exists(db=db_session_mock, activity_id=999)

    assert exists is False
    db_session_mock.query.return_value.filter.return_value.scalar.assert_called_once()

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