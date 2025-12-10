import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from pear_schedule.crud.ref_activity_routine_crud import (
    create_or_update_ref_activity_routine,
    update_ref_activity_routine_idempotent,
    soft_delete_ref_activity_routine_idempotent,
    get_ref_activity_routines,
    get_ref_activity_routine_by_id,
    get_routine_by_patient_and_activity,
    get_patient_scheduled_routines,
    get_patient_excluded_routines,
    get_activity_routines_by_time_slot
)
from pear_schedule.schemas.ref_activity_routine import RefActivityRoutineCreate, RefActivityRoutineUpdate


class TestRefActivityRoutineCrud:
    
    def test_create_or_update_ref_activity_routine_create_new(self, db_session_mock, sample_activity_routine):
        """Test creating a new activity routine when one doesn't exist"""
        # Mock that no existing routine is found
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None
        
        routine_data = RefActivityRoutineCreate(
            PatientId=4,
            ActivityId=9,
            IncludeInSchedule="1",
            RoutineIssues="Too slow",
            RoutineTimeSlots="0-2,4-2",
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
        
        result = create_or_update_ref_activity_routine(db_session_mock, routine_data, "test_user")
        
        db_session_mock.add.assert_called_once()
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once()

    def test_create_or_update_ref_activity_routine_update_existing(self, db_session_mock, sample_activity_routine):
        """Test updating an existing activity routine"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = sample_activity_routine
        
        routine_data = RefActivityRoutineCreate(
            PatientId=1,
            ActivityId=1,
            IncludeInSchedule="0",  # Changed from included to excluded
            RoutineIssues="Patient has scheduling conflicts",
            RoutineTimeSlots="14:00-15:00",  # Updated time slot
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        result = create_or_update_ref_activity_routine(db_session_mock, routine_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_routine)
        assert result == sample_activity_routine

    def test_update_ref_activity_routine_idempotent_exists(self, db_session_mock, sample_activity_routine):
        """Test updating an activity routine that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_routine
        
        update_data = RefActivityRoutineUpdate(
            PatientId=1,
            ActivityId=1,
            IncludeInSchedule="0",
            RoutineIssues="Updated issues",
            RoutineTimeSlots="16:00-17:00",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_routine_idempotent(db_session_mock, 1, update_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_routine)
        assert result == sample_activity_routine

    def test_update_ref_activity_routine_idempotent_not_exists(self, db_session_mock):
        """Test updating an activity routine that doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        update_data = RefActivityRoutineUpdate(
            PatientId=1,
            ActivityId=1,
            IncludeInSchedule="0",
            RoutineIssues="Updated issues",
            RoutineTimeSlots="16:00-17:00",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )
        
        result = update_ref_activity_routine_idempotent(db_session_mock, 999, update_data, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_activity_routine_idempotent_exists(self, db_session_mock, sample_activity_routine):
        """Test soft deleting an activity routine that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_routine
        
        result = soft_delete_ref_activity_routine_idempotent(db_session_mock, 1, "test_user")
        
        assert sample_activity_routine.IsDeleted == "1"
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_activity_routine)
        assert result == sample_activity_routine

    def test_get_ref_activity_routines_with_filters(self, db_session_mock, sample_activity_routine):
        """Test getting activity routines with filters"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_activity_routine]
        db_session_mock.query.return_value.scalar.return_value = 1
        
        routines, total_records, total_pages = get_ref_activity_routines(
            db_session_mock,
            pageNo=0,
            pageSize=10,
            patient_id=1,
            activity_id=1,
            include_in_schedule="1"
        )
        
        assert len(routines) == 1
        assert routines[0] == sample_activity_routine
        assert total_records == 1
        assert total_pages == 1

    def test_get_routine_by_patient_and_activity_found(self, db_session_mock, sample_activity_routine):
        """Test getting routine for a specific patient and activity"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = sample_activity_routine
        
        result = get_routine_by_patient_and_activity(db_session_mock, 1, 1)
        
        assert result == sample_activity_routine

    def test_get_patient_scheduled_routines(self, db_session_mock, sample_activity_routine):
        """Test getting all routines included in schedule for a patient"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_activity_routine]
        
        result = get_patient_scheduled_routines(db_session_mock, 1)
        
        assert len(result) == 1
        assert result[0] == sample_activity_routine

    def test_get_patient_excluded_routines(self, db_session_mock):
        """Test getting all routines excluded from schedule for a patient"""
        excluded_routine = Mock()
        excluded_routine.IncludeInSchedule = "0"
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [excluded_routine]
        
        result = get_patient_excluded_routines(db_session_mock, 1)
        
        assert len(result) == 1
        assert result[0] == excluded_routine

    def test_get_activity_routines_by_time_slot(self, db_session_mock, sample_activity_routine):
        """Test getting all routines for a specific time slot"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_activity_routine]
        
        result = get_activity_routines_by_time_slot(db_session_mock, "09:00")
        
        assert len(result) == 1
        assert result[0] == sample_activity_routine

    def test_get_ref_activity_routine_by_id_found(self, db_session_mock, sample_activity_routine):
        """Test getting an activity routine by ID when it exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_activity_routine
        
        result = get_ref_activity_routine_by_id(db_session_mock, 1)
        
        assert result == sample_activity_routine

    def test_get_ref_activity_routine_by_id_not_found(self, db_session_mock):
        """Test getting an activity routine by ID when it doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        result = get_ref_activity_routine_by_id(db_session_mock, 999)
        
        assert result is None

    def test_get_activity_routines_by_complex_time_slot(self, db_session_mock, sample_complex_routine):
        """Test getting routines by complex time slot pattern"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_complex_routine]
        
        result = get_activity_routines_by_time_slot(db_session_mock, "1-6")
        
        assert len(result) == 1
        assert result[0] == sample_complex_routine
        assert result[0].RoutineTimeSlots == "1-6,3-6"  # Tuesday and Thursday at 6pm
        assert "Tues and Thurs" in result[0].RoutineIssues
