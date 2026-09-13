from unittest.mock import patch
from datetime import datetime
import pytest
from sqlalchemy.exc import IntegrityError

from pear_schedule.services.idempotency_service import IdempotencyService
from pear_schedule.models.processed_events_model import ProcessedEvent


def make_processed_event(correlation_id="corr-1", event_type="PATIENT_CREATED", aggregate_id="1"):
    return ProcessedEvent(
        correlation_id=correlation_id,
        event_type=event_type,
        aggregate_id=aggregate_id,
        processed_by="scheduler_service",
        processed_at=datetime.now(),
    )


class TestIsAlreadyProcessed:

    def test_returns_false_when_not_processed(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = None

        assert IdempotencyService.is_already_processed(db_session_mock, "corr-1") is False

    def test_returns_true_when_already_processed(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = make_processed_event()

        assert IdempotencyService.is_already_processed(db_session_mock, "corr-1") is True

    def test_returns_false_on_query_exception(self, db_session_mock):
        db_session_mock.query.side_effect = Exception("db unavailable")

        assert IdempotencyService.is_already_processed(db_session_mock, "corr-1") is False


class TestMarkAsProcessed:

    def test_creates_and_flushes_processed_event(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = make_processed_event()

        result = IdempotencyService.mark_as_processed(
            db_session_mock,
            correlation_id="corr-1",
            event_type="PATIENT_CREATED",
            aggregate_id="1",
            processed_by="scheduler_service",
        )

        db_session_mock.add.assert_called_once()
        db_session_mock.flush.assert_called_once()
        added_event = db_session_mock.add.call_args[0][0]
        assert added_event.correlation_id == "corr-1"
        assert result is added_event

    def test_serializes_operation_result_to_json(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = make_processed_event()

        IdempotencyService.mark_as_processed(
            db_session_mock,
            correlation_id="corr-1",
            event_type="PATIENT_CREATED",
            aggregate_id="1",
            processed_by="scheduler_service",
            operation_result={"status": "success"},
        )

        added_event = db_session_mock.add.call_args[0][0]
        assert added_event.operation_result == '{"status": "success"}'

    def test_falls_back_to_str_when_json_serialization_fails(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = make_processed_event()

        with patch("pear_schedule.services.idempotency_service.json.dumps", side_effect=TypeError("not serializable")):
            IdempotencyService.mark_as_processed(
                db_session_mock,
                correlation_id="corr-1",
                event_type="PATIENT_CREATED",
                aggregate_id="1",
                processed_by="scheduler_service",
                operation_result={"status": "success"},
            )

        added_event = db_session_mock.add.call_args[0][0]
        assert added_event.operation_result == str({"status": "success"})

    def test_logs_but_does_not_raise_when_verification_finds_nothing(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = None

        result = IdempotencyService.mark_as_processed(
            db_session_mock,
            correlation_id="corr-1",
            event_type="PATIENT_CREATED",
            aggregate_id="1",
            processed_by="scheduler_service",
        )

        assert result is not None

    def test_integrity_error_during_flush_rolls_back_and_reraises(self, db_session_mock):
        db_session_mock.flush.side_effect = IntegrityError("stmt", {}, Exception("duplicate key"))

        with pytest.raises(IntegrityError):
            IdempotencyService.mark_as_processed(
                db_session_mock,
                correlation_id="corr-1",
                event_type="PATIENT_CREATED",
                aggregate_id="1",
                processed_by="scheduler_service",
            )

        db_session_mock.rollback.assert_called_once()

    def test_generic_error_during_flush_reraises_without_rollback(self, db_session_mock):
        db_session_mock.flush.side_effect = Exception("flush failed")

        with pytest.raises(Exception, match="flush failed"):
            IdempotencyService.mark_as_processed(
                db_session_mock,
                correlation_id="corr-1",
                event_type="PATIENT_CREATED",
                aggregate_id="1",
                processed_by="scheduler_service",
            )

        db_session_mock.rollback.assert_not_called()


class TestProcessIdempotent:

    def test_skips_when_already_processed(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = make_processed_event()
        operation = lambda: pytest.fail("operation should not run for a duplicate event")

        result, was_duplicate = IdempotencyService.process_idempotent(
            db_session_mock,
            correlation_id="corr-1",
            event_type="PATIENT_CREATED",
            aggregate_id="1",
            processed_by="scheduler_service",
            operation=operation,
        )

        assert result is None
        assert was_duplicate is True

    def test_executes_operation_and_marks_processed_on_success(self, db_session_mock):
        # first() is called twice: is_already_processed's check (None), then
        # mark_as_processed's post-flush verification.
        db_session_mock.query.return_value.filter.return_value.first.side_effect = [None, make_processed_event()]
        operation = lambda: "operation result"

        result, was_duplicate = IdempotencyService.process_idempotent(
            db_session_mock,
            correlation_id="corr-1",
            event_type="PATIENT_CREATED",
            aggregate_id="1",
            processed_by="scheduler_service",
            operation=operation,
        )

        assert result == "operation result"
        assert was_duplicate is False
        db_session_mock.add.assert_called_once()

    def test_integrity_error_from_operation_returns_duplicate_tuple(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = None

        def operation():
            raise IntegrityError("stmt", {}, Exception("duplicate key"))

        result, was_duplicate = IdempotencyService.process_idempotent(
            db_session_mock,
            correlation_id="corr-1",
            event_type="PATIENT_CREATED",
            aggregate_id="1",
            processed_by="scheduler_service",
            operation=operation,
        )

        assert result is None
        assert was_duplicate is True

    def test_value_error_marks_processed_with_error_and_reraises(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = None

        def operation():
            raise ValueError("bad business data")

        with pytest.raises(ValueError, match="bad business data"):
            IdempotencyService.process_idempotent(
                db_session_mock,
                correlation_id="corr-1",
                event_type="PATIENT_CREATED",
                aggregate_id="1",
                processed_by="scheduler_service",
                operation=operation,
            )

        added_event = db_session_mock.add.call_args[0][0]
        assert added_event.error_message == "bad business data"
        db_session_mock.commit.assert_called_once()

    def test_value_error_still_reraises_when_marking_as_processed_also_fails(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        db_session_mock.flush.side_effect = Exception("flush failed")

        def operation():
            raise ValueError("bad business data")

        with pytest.raises(ValueError, match="bad business data"):
            IdempotencyService.process_idempotent(
                db_session_mock,
                correlation_id="corr-1",
                event_type="PATIENT_CREATED",
                aggregate_id="1",
                processed_by="scheduler_service",
                operation=operation,
            )

        db_session_mock.commit.assert_not_called()

    def test_generic_exception_reraises_without_marking_processed(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.first.return_value = None

        def operation():
            raise RuntimeError("unexpected failure")

        with pytest.raises(RuntimeError, match="unexpected failure"):
            IdempotencyService.process_idempotent(
                db_session_mock,
                correlation_id="corr-1",
                event_type="PATIENT_CREATED",
                aggregate_id="1",
                processed_by="scheduler_service",
                operation=operation,
            )

        db_session_mock.add.assert_not_called()


class TestRecordProcessedEvent:

    def test_records_without_duplicate_check(self, db_session_mock):
        result = IdempotencyService.record_processed_event(
            db_session_mock,
            correlation_id="corr-1",
            event_type="ACTIVITY_UPDATED",
            aggregate_id="1",
            processed_by="scheduler_service",
        )

        db_session_mock.query.assert_not_called()
        db_session_mock.add.assert_called_once()
        db_session_mock.flush.assert_called_once()
        assert result.correlation_id == "corr-1"

    def test_raises_when_flush_fails(self, db_session_mock):
        db_session_mock.flush.side_effect = Exception("flush failed")

        with pytest.raises(Exception, match="flush failed"):
            IdempotencyService.record_processed_event(
                db_session_mock,
                correlation_id="corr-1",
                event_type="ACTIVITY_UPDATED",
                aggregate_id="1",
                processed_by="scheduler_service",
            )


class TestCleanupOldEvents:

    def test_deletes_events_older_than_cutoff_and_commits(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.delete.return_value = 3

        deleted_count = IdempotencyService.cleanup_old_events(db_session_mock, older_than_days=30)

        assert deleted_count == 3
        db_session_mock.commit.assert_called_once()

    def test_returns_zero_when_nothing_to_delete(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.delete.return_value = 0

        deleted_count = IdempotencyService.cleanup_old_events(db_session_mock)

        assert deleted_count == 0

    def test_rolls_back_and_reraises_on_error(self, db_session_mock):
        db_session_mock.query.return_value.filter.return_value.delete.side_effect = Exception("delete failed")

        with pytest.raises(Exception, match="delete failed"):
            IdempotencyService.cleanup_old_events(db_session_mock)

        db_session_mock.rollback.assert_called_once()


class TestGetProcessingStats:

    def test_returns_stats_dict_on_success(self, db_session_mock):
        # same mock_query for every chain, so use side_effect in call order
        db_session_mock.query.return_value.count.side_effect = [10, 2, 1]
        db_session_mock.query.return_value.all.side_effect = [
            [("PATIENT_CREATED", 6), ("PATIENT_UPDATED", 4)],
            [make_processed_event(correlation_id="12345678-abcd")],
        ]

        stats = IdempotencyService.get_processing_stats(db_session_mock)

        assert stats["total_processed_events"] == 10
        assert stats["events_last_24h"] == 2
        assert stats["events_with_errors"] == 1
        assert stats["events_by_type"] == [
            {"event_type": "PATIENT_CREATED", "count": 6},
            {"event_type": "PATIENT_UPDATED", "count": 4},
        ]
        assert stats["latest_events"][0]["correlation_id"] == "12345678..."

    def test_returns_error_dict_on_exception(self, db_session_mock):
        db_session_mock.query.side_effect = Exception("stats query failed")

        stats = IdempotencyService.get_processing_stats(db_session_mock)

        assert stats["error"] == "stats query failed"
        assert "stats_generated_at" in stats
