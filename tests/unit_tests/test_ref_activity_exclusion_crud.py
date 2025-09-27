import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from pear_schedule.crud.ref_activity_exclusion_crud import (
    create_or_update_ref_activity_exclusion,
    update_ref_activity_exclusion_idempotent,
    soft_delete_ref_activity_exclusion_idempotent,
    get_ref_activity_exclusions,
    get_ref_activity_exclusion_by_id,
    get_exclusions_by_patient_and_activity
)
from pear_schedule.schemas.ref_activity_exclusion import RefActivityExclusionCreate, RefActivityExclusionUpdate


class TestRefActivityExclusionCrud:
    
    def test_create_or_update_ref_activity_exclusion_create_new(self, db_session_mock, sample_activity_exclusion):
        """Test creating a new activity exclusion when one doesn't exist"""
        # Mock that no existing exclusion is found
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None
        
        exclusion_data = RefActivityExclusionCreate(
            PatientId=1,
            ActivityId=1,
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 1, 7),
            ExclusionRemarks="Patient has mobility issues",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        # Mock refresh to set the Id after creation
        def mock_refresh(obj):
            obj.Id = 1
        db_session_mock.refresh.side_effect = mock_refresh
        
        result = create_or_update_ref_activity_exclusion(db_session_mock, exclusion_data, "test_user")
        
        db_session_mock.add.assert_called_once()
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once()

    def test_create_or_update_ref_activity_exclusion_update_existing(self, db_session_mock, sample_activity_exclusion):
        """Test updating an existing activity exclusion"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = sample_activity_exclusion
        
        exclusion_data = RefActivityExclusionCreate(
            PatientId=1,
            ActivityId=1,
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 1, 14),
            ExclusionRemarks="Updated remarks",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        result = create_or_update_ref_activity_exclusion(db_session_mock, exclusion_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_exclusion)
        assert result == sample_activity_exclusion

    def test_update_ref_activity_exclusion_idempotent_exists(self, db_session_mock, sample_activity_exclusion):
        """Test updating an activity exclusion that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_exclusion
        
        update_data = RefActivityExclusionUpdate(
            PatientId=1,
            ActivityId=1,
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 1, 14),
            ExclusionRemarks="Updated exclusion remarks",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_exclusion_idempotent(db_session_mock, 1, update_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_exclusion)
        assert result == sample_activity_exclusion

    def test_update_ref_activity_exclusion_idempotent_not_exists(self, db_session_mock):
        """Test updating an activity exclusion that doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        update_data = RefActivityExclusionUpdate(
            PatientId=1,
            ActivityId=1,
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 1, 14),
            ExclusionRemarks="Updated exclusion remarks",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_exclusion_idempotent(db_session_mock, 999, update_data, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_activity_exclusion_idempotent_exists(self, db_session_mock, sample_activity_exclusion):
        """Test soft deleting an activity exclusion that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_exclusion
        
        result = soft_delete_ref_activity_exclusion_idempotent(db_session_mock, 1, "test_user")
        
        assert sample_activity_exclusion.IsDeleted == "1"
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_exclusion)
        assert result == sample_activity_exclusion

    def test_soft_delete_ref_activity_exclusion_idempotent_not_exists(self, db_session_mock):
        """Test soft deleting an activity exclusion that doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        result = soft_delete_ref_activity_exclusion_idempotent(db_session_mock, 999, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_activity_exclusion_idempotent_already_deleted(self, db_session_mock, sample_activity_exclusion):
        """Test soft deleting an activity exclusion that's already deleted"""
        sample_activity_exclusion.IsDeleted = "1"
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_exclusion
        
        result = soft_delete_ref_activity_exclusion_idempotent(db_session_mock, 1, "test_user")
        
        assert result == sample_activity_exclusion
        db_session_mock.commit.assert_not_called()

    def test_get_ref_activity_exclusions_with_filters(self, db_session_mock, sample_activity_exclusion):
        """Test getting activity exclusions with patient_id and activity_id filters"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_activity_exclusion]
        db_session_mock.query.return_value.scalar.return_value = 1
        
        exclusions, total_records, total_pages = get_ref_activity_exclusions(
            db_session_mock,
            pageNo=0,
            pageSize=10,
            patient_id=1,
            activity_id=1
        )
        
        assert len(exclusions) == 1
        assert exclusions[0] == sample_activity_exclusion
        assert total_records == 1
        assert total_pages == 1

    def test_get_ref_activity_exclusions_no_filters(self, db_session_mock, sample_activity_exclusion):
        """Test getting activity exclusions without filters"""
        db_session_mock.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_activity_exclusion]
        db_session_mock.query.return_value.scalar.return_value = 1
        
        exclusions, total_records, total_pages = get_ref_activity_exclusions(db_session_mock)
        
        assert len(exclusions) == 1
        assert total_records == 1
        assert total_pages == 1

    def test_get_ref_activity_exclusion_by_id_found(self, db_session_mock, sample_activity_exclusion):
        """Test getting an activity exclusion by ID when it exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_exclusion
        
        result = get_ref_activity_exclusion_by_id(db_session_mock, 1)
        
        assert result == sample_activity_exclusion

    def test_get_ref_activity_exclusion_by_id_not_found(self, db_session_mock):
        """Test getting an activity exclusion by ID when it doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        result = get_ref_activity_exclusion_by_id(db_session_mock, 999)
        
        assert result is None

    def test_get_exclusions_by_patient_and_activity_found(self, db_session_mock, sample_activity_exclusion):
        """Test getting exclusions for a specific patient and activity"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_activity_exclusion]
        
        result = get_exclusions_by_patient_and_activity(db_session_mock, 1, 1)
        
        assert len(result) == 1
        assert result[0] == sample_activity_exclusion

    def test_get_exclusions_by_patient_and_activity_not_found(self, db_session_mock):
        """Test getting exclusions for a specific patient and activity when none exist"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = []
        
        result = get_exclusions_by_patient_and_activity(db_session_mock, 999, 999)
        
        assert len(result) == 0
