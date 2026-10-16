"""
A malformed allocation event must be acked (dropped), not requeued forever. No DB, no broker.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

from messaging.patient_allocation_consumer import PatientAllocationConsumer
from pear_schedule.models.processed_events_model import MessageProcessingResult


def _consumer(processed=False):
    consumer = PatientAllocationConsumer.__new__(PatientAllocationConsumer)
    consumer.shutdown_event = None

    @contextmanager
    def transaction():
        yield MagicMock()

    consumer.get_db_transaction = transaction
    consumer.get_db = lambda: iter([MagicMock()])
    # nothing is ever recorded for a failed event
    consumer.is_event_already_processed = MagicMock(return_value=processed)
    consumer.map_patient_allocation_create = MagicMock(return_value=None)  # mapping fails
    consumer.create_ref_patient_allocation = MagicMock()
    return consumer


def _message(**data):
    return {"data": {"correlation_id": "c1", "event_type": "PATIENT_ALLOCATION_CREATED", "allocation_id": 9,
                     "allocation_data": {"bad": True}, **data}}


def test_unmappable_event_is_acked_not_requeued():
    consumer = _consumer()
    assert consumer._handle_message_wrapper(_message()) is True
    consumer.create_ref_patient_allocation.assert_not_called()


def test_unknown_event_type_is_acked():
    assert _consumer()._handle_message_wrapper(_message(event_type="SOMETHING_ELSE")) is True


def test_data_that_is_not_an_object_is_acked():
    consumer = _consumer()
    assert consumer._handle_message_wrapper({"data": None}) is True
    assert consumer._handle_message_wrapper({"data": "oops"}) is True
    assert consumer._handle_message_wrapper(["not", "a", "dict"]) is True


def test_success_still_needs_the_processed_record():
    consumer = _consumer()
    consumer.map_patient_allocation_create = MagicMock(side_effect=lambda d: d)
    consumer._handle_patient_allocation_created = MagicMock(return_value=MessageProcessingResult.SUCCESS)
    # no processed_events row after a success means retry
    assert consumer._handle_message_wrapper(_message()) is False
