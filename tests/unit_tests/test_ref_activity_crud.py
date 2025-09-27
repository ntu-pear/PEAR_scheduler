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
    
    def test_create_or_update_ref_activity_create_new(self, db_session_mock, sample_ref_activity):
        """Test creating a new activity when one doesn't exist"""
        # Mock that no existing activity is found
        db_session_mock.query().filter().first.side_effect = [None, sample_ref_activity]
        
        activity_data = RefActivityCreate(
            Id=1,
            Title="Morning Exercise",
            Desc="Light exercise for seniors",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )

    def test_create_or_update_ref_activity_update_existing(self, db_session_mock, sample_ref_activity):
        """Test updating an existing activity"""
        db_session_mock.query().filter().first.return_value = sample_ref_activity
        
        activity_data = RefActivityCreate(
            Id=1,
            Title="Updated Exercise",
            Desc="Updated description",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        result = create_or_update_ref_activity(db_session_mock, activity_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_ref_activity)
        assert result == sample_ref_activity

    def test_update_ref_activity_idempotent_activity_exists(self, db_session_mock, sample_ref_activity):
        """Test updating an activity that exists"""
        db_session_mock.query().filter().first.return_value = sample_ref_activity
        
        update_data = RefActivityUpdate(
            Id=1,
            Title="Updated Title",
            Desc="Updated Description",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_idempotent(db_session_mock, 1, update_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_ref_activity)
        assert result == sample_ref_activity

    def test_update_ref_activity_idempotent_activity_not_exists(self, db_session_mock):
        """Test updating an activity that doesn't exist"""
        db_session_mock.query().filter().first.return_value = None
        
        update_data = RefActivityUpdate(
            Id=1,
            Title="Updated Title",
            Desc="Updated Description",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_idempotent(db_session_mock, 999, update_data, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_activity_idempotent_activity_exists(self, db_session_mock, sample_ref_activity):
        """Test soft deleting an activity that exists"""
        db_session_mock.query().filter().first.return_value = sample_ref_activity
        
        result = soft_delete_ref_activity_idempotent(db_session_mock, 1, "test_user")
        
        assert sample_ref_activity.IsDeleted == "1"
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_ref_activity)
        assert result == sample_ref_activity

    def test_soft_delete_ref_activity_idempotent_activity_not_exists(self, db_session_mock):
        """Test soft deleting an activity that doesn't exist"""
        db_session_mock.query().filter().first.return_value = None
        
        result = soft_delete_ref_activity_idempotent(db_session_mock, 999, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_activity_idempotent_already_deleted(self, db_session_mock, sample_ref_activity):
        """Test soft deleting an activity that's already deleted"""
        sample_ref_activity.IsDeleted = "1"
        db_session_mock.query().filter().first.return_value = sample_ref_activity
        
        result = soft_delete_ref_activity_idempotent(db_session_mock, 1, "test_user")
        
        assert result == sample_ref_activity
        db_session_mock.commit.assert_not_called()

    def test_get_ref_activities_with_filters(self, db_session_mock, sample_ref_activity):
        """Test getting activities with title and start_date filters"""
        db_session_mock.query().filter().filter().filter().order_by().offset().limit().all.return_value = [sample_ref_activity]
        db_session_mock.query().scalar.return_value = 1
        
        activities, total_records, total_pages = get_ref_activities(
            db_session_mock,
            pageNo=0,
            pageSize=10,
            title="Exercise",
            start_date=datetime(2024, 1, 1)
        )
        
        assert len(activities) == 1
        assert activities[0] == sample_ref_activity
        assert total_records == 1
        assert total_pages == 1

    def test_get_ref_activities_no_filters(self, db_session_mock, sample_ref_activity):
        """Test getting activities without filters"""
        db_session_mock.query().filter().order_by().offset().limit().all.return_value = [sample_ref_activity]
        db_session_mock.query().scalar.return_value = 1
        
        activities, total_records, total_pages = get_ref_activities(db_session_mock)
        
        assert len(activities) == 1
        assert total_records == 1
        assert total_pages == 1

    def test_get_ref_activity_by_id_found(self, db_session_mock, sample_ref_activity):
        """Test getting an activity by ID when it exists"""
        db_session_mock.query().filter().first.return_value = sample_ref_activity
        
        result = get_ref_activity_by_id(db_session_mock, 1)
        
        assert result == sample_ref_activity

    def test_get_ref_activity_by_id_not_found(self, db_session_mock):
        """Test getting an activity by ID when it doesn't exist"""
        db_session_mock.query().filter().first.return_value = None
        
        result = get_ref_activity_by_id(db_session_mock, 999)
        
        assert result is None

    def test_get_ref_activities_pagination(self, db_session_mock):
        """Test pagination calculations"""
        db_session_mock.query().filter().order_by().offset().limit().all.return_value = []
        db_session_mock.query().scalar.return_value = 35
        
        activities, total_records, total_pages = get_ref_activities(
            db_session_mock,
            pageNo=2,
            pageSize=10
        )
        
        assert total_records == 35
        assert total_pages == 4  # math.ceil(35/10) = 4
