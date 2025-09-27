import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from pear_schedule.crud.ref_activity_recommendation_crud import (
    create_or_update_ref_activity_recommendation,
    update_ref_activity_recommendation_idempotent,
    soft_delete_ref_activity_recommendation_idempotent,
    get_ref_activity_recommendations,
    get_ref_activity_recommendation_by_id,
    get_recommendations_by_patient_and_activity,
    get_doctor_recommendations_for_patient,
    get_recommended_activities_for_patient
)
from pear_schedule.schemas.ref_activity_recommendation import RefActivityRecommendationCreate, RefActivityRecommendationUpdate


class TestRefActivityRecommendationCrud:
    
    def test_create_or_update_ref_activity_recommendation_create_new(self, db_session_mock, sample_activity_recommendation):
        """Test creating a new activity recommendation when one doesn't exist"""
        # Mock that no existing recommendation is found
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None
        
        recommendation_data = RefActivityRecommendationCreate(
            PatientId=1,
            ActivityId=1,
            DoctorId="doc123",
            DoctorRecommendation="1",
            DoctorRemarks="Good for mobility",
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
        
        result = create_or_update_ref_activity_recommendation(db_session_mock, recommendation_data, "test_user")
        
        db_session_mock.add.assert_called_once()
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once()

    def test_create_or_update_ref_activity_recommendation_update_existing(self, db_session_mock, sample_activity_recommendation):
        """Test updating an existing activity recommendation"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = sample_activity_recommendation
        
        recommendation_data = RefActivityRecommendationCreate(
            PatientId=1,
            ActivityId=1,
            DoctorId="doc123",
            DoctorRecommendation="0",  # Changed from recommended to not recommended
            DoctorRemarks="Updated remarks - not suitable anymore",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        result = create_or_update_ref_activity_recommendation(db_session_mock, recommendation_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_recommendation)
        assert result == sample_activity_recommendation

    def test_update_ref_activity_recommendation_idempotent_exists(self, db_session_mock, sample_activity_recommendation):
        """Test updating an activity recommendation that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_recommendation
        
        update_data = RefActivityRecommendationUpdate(
            PatientId=1,
            ActivityId=1,
            DoctorId="doc123",
            DoctorRecommendation="0",
            DoctorRemarks="Updated recommendation",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_recommendation_idempotent(db_session_mock, 1, update_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_recommendation)
        assert result == sample_activity_recommendation

    def test_update_ref_activity_recommendation_idempotent_not_exists(self, db_session_mock):
        """Test updating an activity recommendation that doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        update_data = RefActivityRecommendationUpdate(
            PatientId=1,
            ActivityId=1,
            DoctorId="doc123",
            DoctorRecommendation="0",
            DoctorRemarks="Updated recommendation",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_recommendation_idempotent(db_session_mock, 999, update_data, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_activity_recommendation_idempotent_exists(self, db_session_mock, sample_activity_recommendation):
        """Test soft deleting an activity recommendation that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_recommendation
        
        result = soft_delete_ref_activity_recommendation_idempotent(db_session_mock, 1, "test_user")
        
        assert sample_activity_recommendation.IsDeleted == "1"
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_recommendation)
        assert result == sample_activity_recommendation

    def test_get_ref_activity_recommendations_with_filters(self, db_session_mock, sample_activity_recommendation):
        """Test getting activity recommendations with filters"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_activity_recommendation]
        db_session_mock.query.return_value.scalar.return_value = 1
        
        recommendations, total_records, total_pages = get_ref_activity_recommendations(
            db_session_mock,
            pageNo=0,
            pageSize=10,
            patient_id=1,
            activity_id=1,
            doctor_id="doc123",
            is_recommended="1"
        )
        
        assert len(recommendations) == 1
        assert recommendations[0] == sample_activity_recommendation
        assert total_records == 1
        assert total_pages == 1

    def test_get_recommendations_by_patient_and_activity_found(self, db_session_mock, sample_activity_recommendation):
        """Test getting recommendations for a specific patient and activity"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_activity_recommendation]
        
        result = get_recommendations_by_patient_and_activity(db_session_mock, 1, 1)
        
        assert len(result) == 1
        assert result[0] == sample_activity_recommendation

    def test_get_doctor_recommendations_for_patient(self, db_session_mock, sample_activity_recommendation):
        """Test getting all recommendations by a doctor for a specific patient"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_activity_recommendation]
        
        result = get_doctor_recommendations_for_patient(db_session_mock, 1, "doc123")
        
        assert len(result) == 1
        assert result[0] == sample_activity_recommendation

    def test_get_recommended_activities_for_patient(self, db_session_mock, sample_activity_recommendation):
        """Test getting all recommended activities for a patient"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_activity_recommendation]
        
        result = get_recommended_activities_for_patient(db_session_mock, 1)
        
        assert len(result) == 1
        assert result[0] == sample_activity_recommendation

    def test_get_ref_activity_recommendation_by_id_found(self, db_session_mock, sample_activity_recommendation):
        """Test getting an activity recommendation by ID when it exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_recommendation
        
        result = get_ref_activity_recommendation_by_id(db_session_mock, 1)
        
        assert result == sample_activity_recommendation

    def test_get_ref_activity_recommendation_by_id_not_found(self, db_session_mock):
        """Test getting an activity recommendation by ID when it doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        result = get_ref_activity_recommendation_by_id(db_session_mock, 999)
        
        assert result is None
