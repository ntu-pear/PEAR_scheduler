import pytest
from unittest import mock
from datetime import datetime, date, time

from pear_schedule.crud.ref_centre_activity_availability_crud import (
    create_ref_centre_activity_availability,
    update_ref_centre_activity_availability,
    delete_ref_centre_activity_availability,
)
from pear_schedule.models.ref_centre_activity_availability_model import RefCentreActivityAvailability
from pear_schedule.schemas.ref_centre_activity_availability import (
    RefCentreActivityAvailabilityCreate,
    RefCentreActivityAvailabilityUpdate,
    RefCentreActivityAvailabilityDelete,
)

CRUD = "pear_schedule.crud.ref_centre_activity_availability_crud"


def fake_process_idempotent(db, correlation_id, event_type, aggregate_id, processed_by, operation):
    return operation(), False


@pytest.fixture
def create_data():
    return RefCentreActivityAvailabilityCreate(
        CentreActivityAvailabilityID=12,
        CentreActivityID=5,
        DaysOfWeek=10,
        StartTime=time(14),
        EndTime=time(16),
        StartDate=date(2026, 10, 1),
        EndDate=date(2026, 12, 31),
        IsDeleted="0",
        CreatedDateTime=datetime(2026, 10, 9, 10, 30),
        UpdatedDateTime=datetime(2026, 10, 9, 10, 30),
        CreatedById="1",
    )


@pytest.fixture
def existing_row():
    return RefCentreActivityAvailability(
        CentreActivityAvailabilityID=12,
        CentreActivityID=5,
        DaysOfWeek=1,
        StartTime=time(9),
        EndTime=time(10),
        StartDate=None,
        EndDate=None,
        IsDeleted="0",
        CreatedDateTime=datetime(2026, 1, 1),
        UpdatedDateTime=datetime(2026, 1, 1),
        CreatedById="1",
        ModifiedById="1",
    )


@pytest.fixture
def delete_data():
    return RefCentreActivityAvailabilityDelete(UpdatedDateTime=datetime(2026, 10, 9, 11), ModifiedById="2")


# ==== create ====

@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", side_effect=fake_process_idempotent)
def test_create_inserts_new_row(mock_idempotent, db_session_mock, create_data):
    db_session_mock.query().filter().first.return_value = None

    result, was_duplicate = create_ref_centre_activity_availability(
        db=db_session_mock, availability=create_data, correlation_id="C1", created_by="1"
    )

    assert was_duplicate is False
    assert result.CentreActivityAvailabilityID == 12
    assert result.DaysOfWeek == 10
    assert result.StartTime == time(14)
    db_session_mock.add.assert_called_once()
    db_session_mock.commit.assert_called_once()
    assert mock_idempotent.call_args.kwargs["event_type"] == "CENTRE_ACTIVITY_AVAILABILITY_CREATED"


@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", side_effect=fake_process_idempotent)
def test_create_overwrites_existing_row(mock_idempotent, db_session_mock, create_data, existing_row):
    existing_row.IsDeleted = "1"
    db_session_mock.query().filter().first.return_value = existing_row

    result, was_duplicate = create_ref_centre_activity_availability(
        db=db_session_mock, availability=create_data, correlation_id="C1", created_by="sync_script"
    )

    assert result is existing_row
    assert was_duplicate is False
    assert existing_row.DaysOfWeek == 10
    assert existing_row.StartTime == time(14)
    assert existing_row.StartDate == date(2026, 10, 1)
    assert existing_row.IsDeleted == "0"
    assert existing_row.ModifiedById == "sync_script"
    db_session_mock.add.assert_not_called()


@mock.patch(f"{CRUD}.IdempotencyService.record_processed_event")
def test_create_sync_records_event(mock_record, db_session_mock, create_data):
    db_session_mock.query().filter().first.return_value = None

    create_ref_centre_activity_availability(
        db=db_session_mock, availability=create_data, correlation_id="C1",
        created_by="sync_script", skip_duplicate_check=True
    )

    mock_record.assert_called_once()
    db_session_mock.commit.assert_called_once()


@mock.patch(f"{CRUD}.IdempotencyService.record_processed_event")
def test_create_record_event_false_skips_recording(mock_record, db_session_mock, create_data):
    db_session_mock.query().filter().first.return_value = None

    create_ref_centre_activity_availability(
        db=db_session_mock, availability=create_data, correlation_id="C1",
        created_by="2", skip_duplicate_check=True, record_event=False
    )

    mock_record.assert_not_called()
    db_session_mock.commit.assert_called_once()


@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", return_value=(None, True))
def test_create_duplicate_returns_existing(mock_idempotent, db_session_mock, create_data, existing_row):
    db_session_mock.query().filter().first.return_value = existing_row

    result, was_duplicate = create_ref_centre_activity_availability(
        db=db_session_mock, availability=create_data, correlation_id="C1", created_by="1"
    )

    assert was_duplicate is True
    assert result is existing_row
    db_session_mock.commit.assert_not_called()


@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", side_effect=Exception("FOREIGN KEY constraint REF_CENTRE_ACTIVITY"))
def test_create_error_rolls_back_and_raises(mock_idempotent, db_session_mock, create_data):
    with pytest.raises(Exception):
        create_ref_centre_activity_availability(
            db=db_session_mock, availability=create_data, correlation_id="C1", created_by="1"
        )
    db_session_mock.rollback.assert_called_once()
    db_session_mock.commit.assert_not_called()


# ==== update ====

@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", side_effect=fake_process_idempotent)
def test_update_applies_fields_including_cleared_dates(mock_idempotent, db_session_mock, existing_row):
    existing_row.StartDate = date(2026, 1, 1)
    db_session_mock.query().filter().first.return_value = existing_row
    update = RefCentreActivityAvailabilityUpdate(
        DaysOfWeek=16, StartTime=time(11), EndTime=time(12), StartDate=None,
        UpdatedDateTime=datetime(2026, 10, 9, 11), ModifiedById="2"
    )

    result, was_duplicate = update_ref_centre_activity_availability(
        db=db_session_mock, availability_id=12, availability_update=update, correlation_id="U1"
    )

    assert result is existing_row
    assert was_duplicate is False
    assert existing_row.DaysOfWeek == 16
    assert existing_row.StartTime == time(11)
    assert existing_row.StartDate is None
    assert existing_row.CentreActivityAvailabilityID == 12
    db_session_mock.commit.assert_called_once()


@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", side_effect=fake_process_idempotent)
def test_update_not_found_returns_none(mock_idempotent, db_session_mock):
    db_session_mock.query().filter().first.return_value = None
    update = RefCentreActivityAvailabilityUpdate(UpdatedDateTime=datetime.now(), ModifiedById="2")

    result, was_duplicate = update_ref_centre_activity_availability(
        db=db_session_mock, availability_id=99, availability_update=update, correlation_id="U1"
    )

    assert result is None
    assert was_duplicate is False
    # The processed-event record still needs committing so the consumer's verification passes
    db_session_mock.commit.assert_called_once()


# ==== delete ====

@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", side_effect=fake_process_idempotent)
def test_delete_soft_deletes(mock_idempotent, db_session_mock, existing_row, delete_data):
    db_session_mock.query().filter().first.return_value = existing_row

    result, was_duplicate = delete_ref_centre_activity_availability(
        db=db_session_mock, availability_id=12, availability_delete=delete_data, correlation_id="D1"
    )

    assert result is existing_row
    assert existing_row.IsDeleted == "1"
    assert existing_row.ModifiedById == "2"
    assert existing_row.UpdatedDateTime == datetime(2026, 10, 9, 11)
    db_session_mock.commit.assert_called_once()


@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", side_effect=fake_process_idempotent)
def test_delete_already_deleted_is_noop(mock_idempotent, db_session_mock, existing_row, delete_data):
    existing_row.IsDeleted = "1"
    existing_row.ModifiedById = "1"
    db_session_mock.query().filter().first.return_value = existing_row

    result, _ = delete_ref_centre_activity_availability(
        db=db_session_mock, availability_id=12, availability_delete=delete_data, correlation_id="D1"
    )

    assert result is existing_row
    assert existing_row.ModifiedById == "1"


@mock.patch(f"{CRUD}.IdempotencyService.process_idempotent", side_effect=fake_process_idempotent)
def test_delete_not_found_returns_none(mock_idempotent, db_session_mock, delete_data):
    db_session_mock.query().filter().first.return_value = None

    result, was_duplicate = delete_ref_centre_activity_availability(
        db=db_session_mock, availability_id=99, availability_delete=delete_data, correlation_id="D1"
    )

    assert result is None
    assert was_duplicate is False
