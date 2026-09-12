import pytest
from unittest import mock
from unittest.mock import Mock
from datetime import datetime

from pear_schedule.crud.ref_activity_routine_crud import (
    create_ref_activity_routine,
    update_ref_activity_routine,
    delete_ref_activity_routine,
    get_ref_activity_routines,
    get_ref_activity_routine_by_id,
    get_routine_by_patient_and_activity,
    get_patient_scheduled_routines,
    get_patient_excluded_routines,
    get_activity_routines_by_time_slot,
    get_idempotency_stats,
    cleanup_old_processed_events,
    is_event_already_processed
)

from pear_schedule.schemas.ref_activity_routine import (
    RefActivityRoutineCreate,
    RefActivityRoutineUpdate,
    RefActivityRoutineDelete
)


@pytest.fixture
def sample_created_ref_activity_routine_data():
    return RefActivityRoutineCreate(
        RoutineID=1,
        PatientID=4,
        ActivityID=9,
        IncludeInSchedule="1",
        RoutineIssues="Too slow",
        RoutineTimeSlots="0-2,4-2",
        IsDeleted="0",
        CreatedDateTime=datetime(2025, 1, 1, 10, 0, 0),
        UpdatedDateTime=datetime(2025, 1, 1, 10, 0, 0),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_updated_ref_activity_routine_data():
    return RefActivityRoutineUpdate(
        PatientID=4,
        ActivityID=9,
        IsDeleted=False,
        IncludeInSchedule="0",
        RoutineIssues="Updated issues",
        RoutineTimeSlots="1-6,3-6",
        UpdatedDateTime=datetime(2025, 1, 2, 10, 0, 0),
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_deleted_ref_activity_routine_data():
    return RefActivityRoutineDelete(
        UpdatedDateTime=datetime(2025, 1, 3, 10, 0, 0),
        ModifiedById="test_user"
    )


# ===== create_ref_activity_routine tests =====

@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_routine_success(mock_idempotent_process, db_session_mock, sample_created_ref_activity_routine_data, sample_activity_routine):
    """Should create a new activity routine successfully"""

    # Mock no existing routine found
    db_session_mock.query().filter().first.side_effect = [None, sample_activity_routine]

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        result = operation()  # executes create_operation
        return result, False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with mock.patch('pear_schedule.crud.ref_activity_routine_crud.RefActivityRoutine', return_value=sample_activity_routine):
        result, was_duplicate = create_ref_activity_routine(
            db=db_session_mock,
            routine=sample_created_ref_activity_routine_data,
            correlation_id="corr_id_123",
            created_by="test_user"
        )

        assert result == sample_activity_routine
        assert was_duplicate is False
        db_session_mock.add.assert_called_once()
        db_session_mock.flush.assert_called_once()
        db_session_mock.commit.assert_called_once()
        mock_idempotent_process.assert_called_once()


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_routine_uses_routine_id_as_key(mock_idempotent_process, db_session_mock, sample_created_ref_activity_routine_data, sample_activity_routine):
    """Should pass RoutineID as the aggregate_id to the idempotency service"""

    db_session_mock.query().filter().first.side_effect = [None, sample_activity_routine]

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with mock.patch('pear_schedule.crud.ref_activity_routine_crud.RefActivityRoutine', return_value=sample_activity_routine):
        create_ref_activity_routine(
            db=db_session_mock,
            routine=sample_created_ref_activity_routine_data,
            correlation_id="corr_id_123",
            created_by="test_user"
        )

    kwargs = mock_idempotent_process.call_args.kwargs
    assert kwargs["event_type"] == "ROUTINE_CREATED"
    assert kwargs["aggregate_id"] == "1"  # RoutineID from the source event


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.record_processed_event')
def test_create_ref_activity_routine_skip_duplicate_check(mock_records_processed_event, db_session_mock, sample_created_ref_activity_routine_data, sample_activity_routine):
    """Should create a new activity routine without duplicate check (sync event)"""

    db_session_mock.query().filter().first.return_value = None
    mock_records_processed_event.return_value = None

    with mock.patch('pear_schedule.crud.ref_activity_routine_crud.RefActivityRoutine', return_value=sample_activity_routine):
        result, was_duplicate = create_ref_activity_routine(
            db=db_session_mock,
            routine=sample_created_ref_activity_routine_data,
            correlation_id="222",
            created_by="test_user",
            skip_duplicate_check=True
        )

        assert result == sample_activity_routine
        assert was_duplicate is False
        db_session_mock.add.assert_called_once()
        db_session_mock.commit.assert_called_once()
        mock_records_processed_event.assert_called_once()


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_routine_reactivate_soft_deleted(mock_idempotent_process, db_session_mock, sample_created_ref_activity_routine_data, sample_activity_routine):
    """Should reactivate a soft-deleted activity routine instead of creating a duplicate"""

    soft_deleted_routine = sample_activity_routine
    soft_deleted_routine.IsDeleted = "1"
    db_session_mock.query().filter().first.side_effect = [soft_deleted_routine, soft_deleted_routine]

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with mock.patch('pear_schedule.crud.ref_activity_routine_crud.RefActivityRoutine', return_value=soft_deleted_routine):
        result, was_duplicate = create_ref_activity_routine(
            db=db_session_mock,
            routine=sample_created_ref_activity_routine_data,
            correlation_id="corr_id_456",
            created_by="test_user"
        )

        assert result == soft_deleted_routine
        assert result.IsDeleted == "0"
        assert was_duplicate is False
        db_session_mock.commit.assert_called_once()


def test_create_ref_activity_routine_duplicate_raises(db_session_mock, sample_created_ref_activity_routine_data, sample_activity_routine):
    """Should raise ValueError when creating a routine that already exists and is not deleted"""

    sample_activity_routine.IsDeleted = "0"
    db_session_mock.query().filter().first.return_value = sample_activity_routine

    with pytest.raises(ValueError):
        create_ref_activity_routine(
            db=db_session_mock,
            routine=sample_created_ref_activity_routine_data,
            correlation_id="corr_id_789",
            created_by="test_user"
        )


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_routine_duplicate_detected(mock_idempotent_process, db_session_mock, sample_created_ref_activity_routine_data, sample_activity_routine):
    """Should return the existing record when the idempotency service detects a replay"""

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent
    db_session_mock.query().filter().first.return_value = sample_activity_routine

    result, was_duplicate = create_ref_activity_routine(
        db=db_session_mock,
        routine=sample_created_ref_activity_routine_data,
        correlation_id="corr_id_101",
        created_by="test_user"
    )

    assert was_duplicate is True
    assert result == sample_activity_routine


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_routine_foreign_key_patient_error(mock_idempotent_process, db_session_mock, sample_created_ref_activity_routine_data):
    """Should roll back and re-raise on an invalid PatientID"""

    db_session_mock.query().filter().first.return_value = None
    db_session_mock.add.side_effect = Exception("FOREIGN KEY constraint failed: REF_PATIENT")

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        create_ref_activity_routine(
            db=db_session_mock,
            routine=sample_created_ref_activity_routine_data,
            correlation_id="corr_id_102",
            created_by="test_user"
        )

    assert "foreign key" in str(exc_info.value).lower()
    db_session_mock.rollback.assert_called_once()


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_create_ref_activity_routine_foreign_key_activity_error(mock_idempotent_process, db_session_mock, sample_created_ref_activity_routine_data):
    """Should roll back and re-raise on an invalid ActivityID"""

    db_session_mock.query().filter().first.return_value = None
    db_session_mock.add.side_effect = Exception("FOREIGN KEY constraint failed: REF_ACTIVITY")

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    with pytest.raises(Exception) as exc_info:
        create_ref_activity_routine(
            db=db_session_mock,
            routine=sample_created_ref_activity_routine_data,
            correlation_id="corr_id_103",
            created_by="test_user"
        )

    assert "foreign key" in str(exc_info.value).lower()
    db_session_mock.rollback.assert_called_once()


# ===== update_ref_activity_routine tests =====

@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_routine_success(mock_idempotent_process, db_session_mock, sample_updated_ref_activity_routine_data, sample_activity_routine):
    """Should update an existing activity routine successfully"""

    db_session_mock.query().filter().first.return_value = sample_activity_routine

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_activity_routine(
        db=db_session_mock,
        routine_id=1,
        routine_update=sample_updated_ref_activity_routine_data,
        correlation_id="corr_id_201"
    )

    assert result == sample_activity_routine
    assert was_duplicate is False
    db_session_mock.flush.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_routine_applies_patient_and_activity(mock_idempotent_process, db_session_mock, sample_activity_routine):
    """PatientID/ActivityID must actually be applied - they were silently skipped when the
    schema used PatientId/ActivityId and the model used PatientID/ActivityID."""

    sample_activity_routine.PatientID = 4
    sample_activity_routine.ActivityID = 9
    db_session_mock.query().filter().first.return_value = sample_activity_routine

    update_data = RefActivityRoutineUpdate(
        PatientID=77,
        ActivityID=88,
        IsDeleted=False,
        UpdatedDateTime=datetime(2025, 1, 2, 10, 0, 0),
        ModifiedById="test_user"
    )

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, _ = update_ref_activity_routine(
        db=db_session_mock,
        routine_id=1,
        routine_update=update_data,
        correlation_id="corr_id_202"
    )

    assert result.PatientID == 77
    assert result.ActivityID == 88


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_routine_not_found(mock_idempotent_process, db_session_mock, sample_updated_ref_activity_routine_data):
    """Should return None when the routine does not exist"""

    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = update_ref_activity_routine(
        db=db_session_mock,
        routine_id=999,
        routine_update=sample_updated_ref_activity_routine_data,
        correlation_id="corr_id_203"
    )

    assert result is None
    assert was_duplicate is False


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_update_ref_activity_routine_duplicate_detected(mock_idempotent_process, db_session_mock, sample_updated_ref_activity_routine_data, sample_activity_routine):
    """Should return the current state when the idempotency service detects a replay"""

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent
    db_session_mock.query().filter().first.return_value = sample_activity_routine

    result, was_duplicate = update_ref_activity_routine(
        db=db_session_mock,
        routine_id=1,
        routine_update=sample_updated_ref_activity_routine_data,
        correlation_id="corr_id_204"
    )

    assert was_duplicate is True
    assert result == sample_activity_routine


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.record_processed_event')
def test_update_ref_activity_routine_skip_duplicate_check(mock_records_processed_event, db_session_mock, sample_updated_ref_activity_routine_data, sample_activity_routine):
    """Should update without the duplicate check for sync events"""

    db_session_mock.query().filter().first.return_value = sample_activity_routine
    mock_records_processed_event.return_value = None

    result, was_duplicate = update_ref_activity_routine(
        db=db_session_mock,
        routine_id=1,
        routine_update=sample_updated_ref_activity_routine_data,
        correlation_id="corr_id_205",
        skip_duplicate_check=True
    )

    assert result == sample_activity_routine
    assert was_duplicate is False
    mock_records_processed_event.assert_called_once()


# ===== delete_ref_activity_routine tests =====

@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_routine_success(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_routine_data, sample_activity_routine):
    """Should soft delete an existing activity routine"""

    sample_activity_routine.IsDeleted = "0"
    db_session_mock.query().filter().first.return_value = sample_activity_routine

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity_routine(
        db=db_session_mock,
        routine_id=1,
        routine_delete=sample_deleted_ref_activity_routine_data,
        correlation_id="corr_id_301"
    )

    assert result == sample_activity_routine
    assert result.IsDeleted == "1"
    assert was_duplicate is False
    db_session_mock.commit.assert_called_once()


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_routine_already_deleted(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_routine_data, sample_activity_routine):
    """Should succeed gracefully when the routine is already soft deleted"""

    sample_activity_routine.IsDeleted = "1"
    db_session_mock.query().filter().first.return_value = sample_activity_routine

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity_routine(
        db=db_session_mock,
        routine_id=1,
        routine_delete=sample_deleted_ref_activity_routine_data,
        correlation_id="corr_id_302"
    )

    assert result == sample_activity_routine
    assert result.IsDeleted == "1"
    assert was_duplicate is False


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_routine_not_found(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_routine_data):
    """Should return None when the routine does not exist"""

    db_session_mock.query().filter().first.return_value = None

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return operation(), False

    mock_idempotent_process.side_effect = fake_process_idempotent

    result, was_duplicate = delete_ref_activity_routine(
        db=db_session_mock,
        routine_id=999,
        routine_delete=sample_deleted_ref_activity_routine_data,
        correlation_id="corr_id_303"
    )

    assert result is None
    assert was_duplicate is False


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.process_idempotent')
def test_delete_ref_activity_routine_duplicate_detected(mock_idempotent_process, db_session_mock, sample_deleted_ref_activity_routine_data, sample_activity_routine):
    """Should return the current state when the idempotency service detects a replay"""

    def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
        return None, True

    mock_idempotent_process.side_effect = fake_process_idempotent
    db_session_mock.query().filter().first.return_value = sample_activity_routine

    result, was_duplicate = delete_ref_activity_routine(
        db=db_session_mock,
        routine_id=1,
        routine_delete=sample_deleted_ref_activity_routine_data,
        correlation_id="corr_id_304"
    )

    assert was_duplicate is True
    assert result == sample_activity_routine


# ===== read helper tests (unchanged functions) =====

class TestRefActivityRoutineReadHelpers:

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


# ===== idempotency helper passthrough tests =====

@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.is_already_processed')
def test_is_event_already_processed(mock_is_already_processed, db_session_mock):
    """Should delegate to the idempotency service"""
    mock_is_already_processed.return_value = True

    assert is_event_already_processed(db_session_mock, "corr_id_401") is True
    mock_is_already_processed.assert_called_once_with(db_session_mock, "corr_id_401")


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.get_processing_stats')
def test_get_idempotency_stats(mock_get_stats, db_session_mock):
    """Should delegate to the idempotency service"""
    mock_get_stats.return_value = {"total": 5}

    assert get_idempotency_stats(db_session_mock) == {"total": 5}
    mock_get_stats.assert_called_once_with(db_session_mock)


@mock.patch('pear_schedule.crud.ref_activity_routine_crud.IdempotencyService.cleanup_old_events')
def test_cleanup_old_processed_events(mock_cleanup, db_session_mock):
    """Should delegate to the idempotency service"""
    mock_cleanup.return_value = 3

    assert cleanup_old_processed_events(db_session_mock, older_than_days=15) == 3
    mock_cleanup.assert_called_once_with(db_session_mock, 15)
