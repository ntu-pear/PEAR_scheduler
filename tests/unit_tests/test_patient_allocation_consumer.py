"""Patient allocation consumer results. No DB, no broker."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from messaging.patient_allocation_consumer import PatientAllocationConsumer
from messaging.mappers.mapper_util import map_patient_allocation_create
from pear_schedule.models.processed_events_model import MessageProcessingResult


def _consumer(processed=False):
    consumer = PatientAllocationConsumer.__new__(PatientAllocationConsumer)
    consumer.shutdown_event = None
    consumer.map_patient_allocation_create = map_patient_allocation_create
    consumer.create_ref_patient_allocation = MagicMock(return_value=(object(), False))
    consumer.is_event_already_processed = MagicMock(return_value=processed)
    consumer.get_db = lambda: iter([MagicMock()])

    @contextmanager
    def tx():
        yield MagicMock()

    consumer.get_db_transaction = tx
    return consumer


def _message(allocation_data):
    return {"data": {"correlation_id": "c1", "event_type": "PATIENT_ALLOCATION_CREATED", "allocation_id": 9,
                     "allocation_data": allocation_data}}


class TestBadPayload:
    def test_malformed_allocation_is_acked_not_requeued(self):
        """A permanent failure records no event, the check after it used to turn it into a retry every time."""
        consumer = _consumer(processed=False)
        message = _message({"PatientId": "not a number"})
        assert consumer._process_patient_allocation_message(message) == MessageProcessingResult.FAILED_PERMANENT
        assert consumer._handle_message_wrapper(message) is True
        consumer.create_ref_patient_allocation.assert_not_called()

    def test_success_without_its_record_still_retries(self):
        consumer = _consumer(processed=False)
        consumer.map_patient_allocation_create = lambda data: {"ok": True}
        consumer._handle_patient_allocation_created = MagicMock(return_value=MessageProcessingResult.SUCCESS)
        assert consumer._process_patient_allocation_message(_message({})) == MessageProcessingResult.FAILED_RETRYABLE

    def test_data_that_is_not_an_object_is_acked(self):
        consumer = _consumer()
        assert consumer._handle_message_wrapper({"data": None}) is True
        assert consumer._handle_message_wrapper({"data": "oops"}) is True
        assert consumer._handle_message_wrapper(["not", "a", "dict"]) is True
