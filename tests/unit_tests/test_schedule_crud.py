import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from fastapi import HTTPException
from pear_schedule.crud.schedule_crud import (
    create_schedule,
    update_schedule,
    delete_schedule,
    get_schedule,
    get_schedules,
)
from pear_schedule.schemas.schedule import ScheduleCreate, ScheduleUpdate


class TestScheduleCrud:

    def test_create_schedule_success(self, db_session_mock, sample_schedule, mock_log_crud_action, mock_serialize_data):
        """Test creating a new schedule successfully"""
        # create_schedule makes two sequential .first() calls on the same mock chain:
        # 1) the overlap check (None = no overlap), 2) the post-insert retrieval (sample_schedule)
        db_session_mock.query.return_value.filter.return_value.first.side_effect = [None, sample_schedule]

        schedule_data = ScheduleCreate(
            PatientId=3,
            StartDate=datetime(2024, 12, 2),
            EndDate=datetime(2024, 12, 8, 23, 59, 59),
            Monday="Breathing+Vital Check--Board Games--Picture Coloring--Lunch--Watch television--Act1--Leslie history routine--Clip Coupons",
            Tuesday="Breathing+Vital Check--Musical Instrument Lesson--Picture Coloring--Lunch--Watch television--Act1--Brisk Walking--String beads",
            Wednesday="Breathing+Vital Check--Mahjong--Watch television--Lunch--Picture Coloring--Act1--Leslie history routine--Clip Coupons",
            Thursday="Breathing+Vital Check--Watch television--Picture Coloring--Lunch--Sort poker chips--String beads--Clip Coupons--Sewing",
            Friday="Breathing+Vital Check--Watch television--Picture Coloring--Lunch--Sort poker chips--Act1--Leslie history routine--String beads",
            Saturday="",
            Sunday="",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )

        with patch('pear_schedule.crud.schedule_crud.text') as mock_text:
            result = create_schedule(db_session_mock, schedule_data, "test_user", "Test User")

        db_session_mock.execute.assert_called_once()
        db_session_mock.commit.assert_called_once()
        mock_log_crud_action.assert_called_once()
        assert result == sample_schedule

    def test_create_schedule_overlapping_schedule_exists(self, db_session_mock, sample_schedule):
        """Test creating a schedule when an overlapping one already exists"""
        # Mock that an overlapping schedule exists
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = sample_schedule

        schedule_data = ScheduleCreate(
            PatientId=3,
            StartDate=datetime(2024, 12, 5),  # Overlaps with existing schedule
            EndDate=datetime(2024, 12, 12),
            Monday="Different Activities",
            Tuesday="Different Activities",
            Wednesday="Different Activities",
            Thursday="Different Activities",
            Friday="Different Activities",
            Saturday="Weekend Activities",
            Sunday="Sunday Activities",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )

        with pytest.raises(HTTPException) as exc_info:
            create_schedule(db_session_mock, schedule_data, "test_user", "Test User")

        assert exc_info.value.status_code == 400
        assert "overlaps with existing schedule" in str(exc_info.value.detail)
        db_session_mock.execute.assert_not_called()

    def test_update_schedule_success(self, db_session_mock, sample_schedule, mock_log_crud_action, mock_serialize_data):
        """Test updating a schedule successfully"""
        # update_schedule makes two sequential .first() calls on the same mock chain:
        # 1) the existence check (sample_schedule), 2) the overlap check (None = no overlap)
        db_session_mock.query.return_value.filter.return_value.first.side_effect = [sample_schedule, None]

        update_data = ScheduleUpdate(
            PatientId=1,
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 1, 7),
            Monday="Updated Morning Exercise",
            Tuesday="Updated Music Therapy",
            Wednesday="Updated Art Class",
            Thursday="Updated Physical Therapy",
            Friday="Updated Cooking Class",
            Saturday="Updated Family Visit",
            Sunday="Updated Religious Service",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )

        result = update_schedule(db_session_mock, 1, update_data, "test_user", "Test User")

        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_schedule)
        mock_log_crud_action.assert_called_once()
        assert result == sample_schedule

    def test_update_schedule_not_found(self, db_session_mock):
        """Test updating a schedule that doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None

        update_data = ScheduleUpdate(
            PatientId=1,
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 1, 7),
            Monday="Updated Morning Exercise",
            Tuesday="Updated Music Therapy",
            Wednesday="Updated Art Class",
            Thursday="Updated Physical Therapy",
            Friday="Updated Cooking Class",
            Saturday="Updated Family Visit",
            Sunday="Updated Religious Service",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )

        with pytest.raises(HTTPException) as exc_info:
            update_schedule(db_session_mock, 999, update_data, "test_user", "Test User")

        assert exc_info.value.status_code == 404
        assert "Schedule not found" in str(exc_info.value.detail)

    def test_update_schedule_overlapping_schedule_exists(self, db_session_mock, sample_schedule):
        """Test updating a schedule when an overlapping one exists"""
        # Mock that the schedule exists
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_schedule

        # Mock that an overlapping schedule exists (excluding current)
        overlapping_schedule = Mock()
        overlapping_schedule.Id = 2
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = overlapping_schedule

        update_data = ScheduleUpdate(
            PatientId=1,
            StartDate=datetime(2024, 1, 3),
            EndDate=datetime(2024, 1, 10),
            Monday="Updated Morning Exercise",
            Tuesday="Updated Music Therapy",
            Wednesday="Updated Art Class",
            Thursday="Updated Physical Therapy",
            Friday="Updated Cooking Class",
            Saturday="Updated Family Visit",
            Sunday="Updated Religious Service",
            IsDeleted="0",
            UpdatedDateTime=datetime.now(),
            ModifiedById="test_user"
        )

        with pytest.raises(HTTPException) as exc_info:
            update_schedule(db_session_mock, 1, update_data, "test_user", "Test User")

        assert exc_info.value.status_code == 400
        assert "overlaps with existing schedule" in str(exc_info.value.detail)

    def test_delete_schedule_success(self, db_session_mock, sample_schedule, mock_log_crud_action, mock_serialize_data):
        """Test deleting a schedule successfully"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_schedule

        result = delete_schedule(db_session_mock, 1, "test_user", "Test User")

        assert sample_schedule.IsDeleted == "1"
        db_session_mock.commit.assert_called_once()
        mock_log_crud_action.assert_called_once()
        assert result == sample_schedule

    def test_delete_schedule_not_found(self, db_session_mock):
        """Test deleting a schedule that doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_schedule(db_session_mock, 999, "test_user", "Test User")

        assert exc_info.value.status_code == 404
        assert "Schedule not found" in str(exc_info.value.detail)

    def test_get_schedule_found(self, db_session_mock, sample_schedule):
        """Test getting a schedule by ID when it exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_schedule

        result = get_schedule(db_session_mock, 1)

        assert result == sample_schedule

    def test_get_schedule_not_found(self, db_session_mock):
        """Test getting a schedule by ID when it doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None

        result = get_schedule(db_session_mock, 999)

        assert result is None

    def test_get_schedules_with_filters(self, db_session_mock, sample_schedule):
        """Test getting schedules with patient_id and date filters"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_schedule]
        db_session_mock.query.return_value.scalar.return_value = 1

        schedules, total_records, total_pages = get_schedules(
            db_session_mock,
            pageNo=0,
            pageSize=10,
            patient_id=1,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31)
        )

        assert len(schedules) == 1
        assert schedules[0] == sample_schedule
        assert total_records == 1
        assert total_pages == 1

    def test_get_schedules_no_filters(self, db_session_mock, sample_schedule):
        """Test getting schedules without filters"""
        db_session_mock.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_schedule]
        db_session_mock.query.return_value.scalar.return_value = 1

        schedules, total_records, total_pages = get_schedules(db_session_mock)

        assert len(schedules) == 1
        assert total_records == 1
        assert total_pages == 1

    def test_create_schedule_with_realistic_overlapping_data(self, db_session_mock, sample_overlapping_schedule):
        """Test creating schedule with realistic overlapping scenario"""
        # Mock that an overlapping schedule exists
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = sample_overlapping_schedule

        schedule_data = ScheduleCreate(
            PatientId=3,
            StartDate=datetime(2024, 12, 5),  # Overlaps with existing from 2024-12-02 to 2024-12-08
            EndDate=datetime(2024, 12, 12),
            Monday="Different Monday Activities",
            Tuesday="Different Tuesday Activities",
            Wednesday="Different Wednesday Activities",
            Thursday="Different Thursday Activities",
            Friday="Different Friday Activities",
            Saturday="Weekend Activities",
            Sunday="Sunday Activities",
            IsDeleted="0",
            CreatedDateTime=datetime.now(),
            UpdatedDateTime=datetime.now(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )

        with pytest.raises(HTTPException) as exc_info:
            create_schedule(db_session_mock, schedule_data, "test_user", "Test User")

        assert exc_info.value.status_code == 400
        assert "overlaps with existing schedule" in str(exc_info.value.detail)
