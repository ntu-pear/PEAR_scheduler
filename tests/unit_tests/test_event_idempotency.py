"""
Events in a cascade share a correlation_id. Each one must still be processed once.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from messaging.centre_activity_consumer import CentreActivityConsumer
from messaging.routine_consumer import RoutineConsumer
from pear_schedule.models.processed_events_model import MessageProcessingResult, ProcessedEvent
from pear_schedule.services.idempotency_service import IdempotencyService, event_key

CORR = "B46237BD-1A5F-4CE3-B9C4-13C80898F32C"


class TestEventKey:
    def test_same_event_same_key(self):
        assert event_key(CORR, "CENTRE_ACTIVITY_DELETED", 1) == event_key(CORR, "CENTRE_ACTIVITY_DELETED", "1")

    def test_cascade_events_get_different_keys(self):
        keys = {
            event_key(CORR, "CENTRE_ACTIVITY_DELETED", 1),
            event_key(CORR, "ACTIVITY_PREFERENCE_DELETED", 81),
            event_key(CORR, "ACTIVITY_PREFERENCE_DELETED", 82),
            event_key("other", "CENTRE_ACTIVITY_DELETED", 1),
        }
        assert len(keys) == 4

    def test_fits_the_correlation_id_column(self):
        key = event_key(CORR, "CENTRE_ACTIVITY_DELETED", 1)
        assert len(key) == 36 == ProcessedEvent.__table__.c.correlation_id.type.length
        uuid.UUID(key)


def _consumer(cls, handler_name):
    """Consumer with the DB and handler faked, processed keys kept in a set."""
    consumer = object.__new__(cls)
    processed, handled = set(), []
    consumer.get_db = lambda: iter([MagicMock()])
    consumer.is_event_already_processed = lambda db, key: key in processed

    def handler(db, message_data):
        handled.append(message_data["correlation_id"])
        processed.add(message_data["correlation_id"])
        return MessageProcessingResult.SUCCESS
    setattr(consumer, handler_name, handler)
    return consumer, processed, handled


class TestCascadeThroughConsumer:
    def _msg(self, event_type, cid):
        return {"data": {"correlation_id": CORR, "event_type": event_type, "centre_activity_id": cid}}

    def test_every_event_in_a_cascade_is_processed(self):
        consumer, _, handled = _consumer(CentreActivityConsumer, "_handle_centre_activity_deleted")
        assert consumer._process_centre_activity_message(self._msg("CENTRE_ACTIVITY_DELETED", 1)) == MessageProcessingResult.SUCCESS
        assert consumer._process_centre_activity_message(self._msg("CENTRE_ACTIVITY_DELETED", 2)) == MessageProcessingResult.SUCCESS
        assert len(handled) == 2

    def test_redelivery_of_the_same_event_is_still_a_duplicate(self):
        consumer, _, handled = _consumer(CentreActivityConsumer, "_handle_centre_activity_deleted")
        consumer._process_centre_activity_message(self._msg("CENTRE_ACTIVITY_DELETED", 1))
        assert consumer._process_centre_activity_message(self._msg("CENTRE_ACTIVITY_DELETED", 1)) == MessageProcessingResult.DUPLICATE
        assert len(handled) == 1

    def test_verification_uses_the_same_key(self):
        """If the check after success used the raw correlation_id it'd requeue forever."""
        consumer, processed, _ = _consumer(CentreActivityConsumer, "_handle_centre_activity_deleted")
        consumer._process_centre_activity_message(self._msg("CENTRE_ACTIVITY_DELETED", 1))
        assert processed == {event_key(CORR, "CENTRE_ACTIVITY_DELETED", 1)}

    def test_other_consumers_too(self):
        consumer, _, handled = _consumer(RoutineConsumer, "_handle_routine_deleted")
        for rid in (5, 6):
            msg = {"data": {"correlation_id": CORR, "event_type": "ROUTINE_DELETED", "routine_id": rid}}
            assert consumer._process_routine_message(msg) == MessageProcessingResult.SUCCESS
        assert len(handled) == 2


class TestProcessedEventsTable:
    @pytest.fixture
    def db(self):
        engine = create_engine("sqlite:///:memory:")
        ProcessedEvent.__table__.create(engine)
        session = sessionmaker(bind=engine)()
        yield session
        session.close()

    def test_cascade_events_can_all_be_recorded(self, db):
        """correlation_id is the primary key, so the raw id couldn't be stored twice."""
        for event_type, agg in (("CENTRE_ACTIVITY_DELETED", "1"), ("ACTIVITY_PREFERENCE_DELETED", "81")):
            IdempotencyService.mark_as_processed(db, event_key(CORR, event_type, agg), event_type, agg, "scheduler_service")
        db.commit()
        assert db.query(ProcessedEvent).count() == 2
        assert IdempotencyService.is_already_processed(db, event_key(CORR, "ACTIVITY_PREFERENCE_DELETED", "81"))
        assert not IdempotencyService.is_already_processed(db, event_key(CORR, "ACTIVITY_PREFERENCE_DELETED", "82"))
