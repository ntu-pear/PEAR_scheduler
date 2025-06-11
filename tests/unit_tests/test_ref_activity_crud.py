import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from app.crud.ref_activity_crud import (
    create_or_update_ref_activity,
    update_ref_activity_idempotent,
    soft_delete_ref_activity_idempotent,
    get_ref_activities,
    get_ref_activity_by_id
)
from app.schemas.ref_activity import RefActivityCreate, RefActivityUpdate


class TestRefActivityCrud:
    
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
            CreatedDateTime=datetime.utcnow(),
            UpdatedDateTime=datetime.utcnow(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        with patch('app.crud.ref_activity_crud.text') as mock_text:
            result = create_or_update_ref_activity(db_session_mock, activity_data, "test_user")
        
        db_session_mock.execute.assert_called_once()
        db_session_mock.commit.assert_called_once()
        assert result == sample_ref_activity

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
            CreatedDateTime=datetime.utcnow(),
            UpdatedDateTime=datetime.utcnow(),
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
            UpdatedDateTime=datetime.utcnow(),
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
            UpdatedDateTime=datetime.utcnow(),
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
