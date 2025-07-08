import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from pear_schedule.crud.ref_activity_preference_crud import (
    create_or_update_ref_activity_preference,
    update_ref_activity_preference_idempotent,
    soft_delete_ref_activity_preference_idempotent,
    get_ref_activity_preferences,
    get_ref_activity_preference_by_id,
    get_preferences_by_patient_and_activity,
    get_patient_liked_activities,
    get_patient_disliked_activities
)
from pear_schedule.schemas.ref_activity_preference import RefActivityPreferenceCreate, RefActivityPreferenceUpdate


class TestRefActivityPreferenceCrud:
    
    def test_create_or_update_ref_activity_preference_create_new(self, db_session_mock, sample_activity_preference):
        """Test creating a new activity preference when one doesn't exist"""
        # Mock that no existing preference is found
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None
        
        preference_data = RefActivityPreferenceCreate(
            PatientId=1,
            ActivityId=1,
            IsLike="1",
            IsDeleted="0",
            CreatedDateTime=datetime.utcnow(),
            UpdatedDateTime=datetime.utcnow(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        # Mock refresh to set the Id after creation
        def mock_refresh(obj):
            obj.Id = 1
        db_session_mock.refresh.side_effect = mock_refresh
        
        result = create_or_update_ref_activity_preference(db_session_mock, preference_data, "test_user")
        
        db_session_mock.add.assert_called_once()
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once()

    def test_create_or_update_ref_activity_preference_update_existing(self, db_session_mock, sample_activity_preference):
        """Test updating an existing activity preference"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = sample_activity_preference
        
        preference_data = RefActivityPreferenceCreate(
            PatientId=1,
            ActivityId=1,
            IsLike="0",  # Changed from like to dislike
            IsDeleted="0",
            CreatedDateTime=datetime.utcnow(),
            UpdatedDateTime=datetime.utcnow(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        result = create_or_update_ref_activity_preference(db_session_mock, preference_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_preference)
        assert result == sample_activity_preference

    def test_update_ref_activity_preference_idempotent_exists(self, db_session_mock, sample_activity_preference):
        """Test updating an activity preference that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_preference
        
        update_data = RefActivityPreferenceUpdate(
            PatientId=1,
            ActivityId=1,
            IsLike="0",
            IsDeleted="0",
            UpdatedDateTime=datetime.utcnow(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_preference_idempotent(db_session_mock, 1, update_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_preference)
        assert result == sample_activity_preference

    def test_update_ref_activity_preference_idempotent_not_exists(self, db_session_mock):
        """Test updating an activity preference that doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        update_data = RefActivityPreferenceUpdate(
            PatientId=1,
            ActivityId=1,
            IsLike="0",
            IsDeleted="0",
            UpdatedDateTime=datetime.utcnow(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_preference_idempotent(db_session_mock, 999, update_data, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_activity_preference_idempotent_exists(self, db_session_mock, sample_activity_preference):
        """Test soft deleting an activity preference that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_preference
        
        result = soft_delete_ref_activity_preference_idempotent(db_session_mock, 1, "test_user")
        
        assert sample_activity_preference.IsDeleted == "1"
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_preference)
        assert result == sample_activity_preference

    def test_get_ref_activity_preferences_with_filters(self, db_session_mock, sample_activity_preference):
        """Test getting activity preferences with filters"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_activity_preference]
        db_session_mock.query.return_value.scalar.return_value = 1
        
        preferences, total_records, total_pages = get_ref_activity_preferences(
            db_session_mock,
            pageNo=0,
            pageSize=10,
            patient_id=1,
            activity_id=1,
            is_like="1"
        )
        
        assert len(preferences) == 1
        assert preferences[0] == sample_activity_preference
        assert total_records == 1
        assert total_pages == 1

    def test_get_preferences_by_patient_and_activity_found(self, db_session_mock, sample_activity_preference):
        """Test getting preference for a specific patient and activity"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = sample_activity_preference
        
        result = get_preferences_by_patient_and_activity(db_session_mock, 1, 1)
        
        assert result == sample_activity_preference

    def test_get_patient_liked_activities(self, db_session_mock, sample_activity_preference):
        """Test getting all activities liked by a patient"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_activity_preference]
        
        result = get_patient_liked_activities(db_session_mock, 1)
        
        assert len(result) == 1
        assert result[0] == sample_activity_preference

    def test_get_patient_disliked_activities(self, db_session_mock):
        """Test getting all activities disliked by a patient"""
        disliked_preference = Mock()
        disliked_preference.IsLike = "0"
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [disliked_preference]
        
        result = get_patient_disliked_activities(db_session_mock, 1)
        
        assert len(result) == 1
        assert result[0] == disliked_preference
