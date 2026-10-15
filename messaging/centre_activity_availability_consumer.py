import logging
import threading
from typing import Dict, Any, Optional
from contextlib import contextmanager

from .rabbitmq_client import RabbitMQClient
from pear_schedule.models.processed_events_model import MessageProcessingResult

logger = logging.getLogger(__name__)

class CentreActivityAvailabilityConsumer:
    """
    Consumer for centre activity availability events.

    Processes CENTRE_ACTIVITY_AVAILABILITY_* events from the activity.updates exchange
    and keeps the scheduler's REF_CENTRE_ACTIVITY_AVAILABILITY table in sync, with
    idempotency guarantees. Values are stored raw (bitmask, times, dates); conversion
    to schedule slots happens when the scheduler reads them.
    """

    def __init__(self):
        self.client = RabbitMQClient("scheduler-centre-activity-availability-consumer")
        self.availability_queues = [
            "scheduler.activity.centre_activity_availability.created",
            "scheduler.activity.centre_activity_availability.updated",
            "scheduler.activity.centre_activity_availability.deleted"
        ]
        self.shutdown_event = None
        self.is_consuming = False

        from pear_schedule.crud.ref_centre_activity_availability_crud import (
            create_ref_centre_activity_availability,
            update_ref_centre_activity_availability,
            delete_ref_centre_activity_availability,
            is_event_already_processed
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import map_centre_activity_availability_create

        self.create_ref_centre_activity_availability = create_ref_centre_activity_availability
        self.update_ref_centre_activity_availability = update_ref_centre_activity_availability
        self.delete_ref_centre_activity_availability = delete_ref_centre_activity_availability
        self.is_event_already_processed = is_event_already_processed
        self.get_db = get_db

        self.map_centre_activity_availability_create = map_centre_activity_availability_create

    @contextmanager
    def get_db_transaction(self):
        """Context manager for database transactions with proper cleanup"""
        db = next(self.get_db())
        try:
            yield db
            # Don't commit here - let the CRUD functions handle commits
        except Exception as e:
            logger.error(f"Rolling back transaction due to error: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    def _flush_logs(self):
        """Force flush all log handlers to ensure logs are written immediately"""
        try:
            for handler in logging.getLogger().handlers:
                handler.flush()
            for handler in logger.handlers:
                handler.flush()
        except Exception:
            pass  # Don't let logging issues break message processing

    def set_shutdown_event(self, shutdown_event: threading.Event):
        """Set the shutdown event for graceful shutdown"""
        self.shutdown_event = shutdown_event
        if self.client:
            self.client.set_shutdown_event(shutdown_event)

    def setup_consumer(self):
        """Set up consumer to listen to the centre activity availability queues"""
        try:
            self.client.connect()

            # Declare the activity.updates exchange (idempotent)
            self.client.channel.exchange_declare(
                exchange='activity.updates',
                exchange_type='topic',
                durable=True
            )

            for queue_name in self.availability_queues:
                # Queues are declared as quorum queues in PEAR_message_queue/definitions.yaml
                self.client.consume(queue_name, self._handle_message_wrapper)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")

            logger.info("Scheduler centre activity availability consumer setup complete")

        except Exception as e:
            logger.error(f"Failed to setup scheduler centre activity availability consumer: {str(e)}")
            raise

    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler centre activity availability consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler centre activity availability consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False

    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping centre activity availability consumer...")
        self.is_consuming = False
        if self.client:
            self.client.stop_consuming()

    def _handle_message_wrapper(self, message: Dict[str, Any]) -> bool:
        """
        Returns True if the message should be acknowledged (success, duplicate or permanent failure),
        False if it should be rejected and requeued (retryable failure).
        """
        try:
            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("Shutdown signal received, stopping message processing")
                return False

            result = self._process_availability_message(message)
            self._flush_logs()

            if result in (MessageProcessingResult.SUCCESS, MessageProcessingResult.DUPLICATE):
                return True
            elif result == MessageProcessingResult.FAILED_PERMANENT:
                logger.error("Message processing failed permanently")
                return True
            elif result == MessageProcessingResult.FAILED_RETRYABLE:
                logger.warning("Message processing failed (retryable)")
                return False
            else:
                logger.error(f"Unknown processing result: {result}")
                return False

        except Exception as e:
            logger.error(f"Fatal error in message wrapper: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            self._flush_logs()
            return False

    def _process_availability_message(self, message: Dict[str, Any]) -> MessageProcessingResult:
        """Route a centre activity availability message to the right handler."""
        try:
            message_data = self._parse_message(message)
            if not message_data:
                return MessageProcessingResult.FAILED_PERMANENT

            correlation_id = message_data['correlation_id']
            event_type = message_data['event_type']
            availability_id = message_data['availability_id']
            is_sync_event = message_data.get('is_sync_event', False)

            logger.info(f"Processing {event_type} for centre activity availability {availability_id} (correlation: {correlation_id}, sync: {is_sync_event})")

            with self.get_db_transaction() as db:
                if not is_sync_event and self.is_event_already_processed(db, correlation_id):
                    logger.info(f"Event already processed: {correlation_id}")
                    return MessageProcessingResult.DUPLICATE

                if event_type == 'CENTRE_ACTIVITY_AVAILABILITY_CREATED':
                    result = self._handle_created(db, message_data)
                elif event_type == 'CENTRE_ACTIVITY_AVAILABILITY_UPDATED':
                    result = self._handle_updated(db, message_data)
                elif event_type == 'CENTRE_ACTIVITY_AVAILABILITY_DELETED':
                    result = self._handle_deleted(db, message_data)
                else:
                    logger.error(f"Unknown event type: {event_type}")
                    return MessageProcessingResult.FAILED_PERMANENT

            # Verify the processed-event record landed before acknowledging
            if result == MessageProcessingResult.SUCCESS:
                verification_db = next(self.get_db())
                try:
                    if not self.is_event_already_processed(verification_db, correlation_id):
                        logger.error(f"CRITICAL: processed_events record missing for {correlation_id}")
                        return MessageProcessingResult.FAILED_RETRYABLE
                finally:
                    verification_db.close()

            return result

        except Exception as e:
            logger.error(f"Error processing centre activity availability message: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _parse_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate message structure; returns the data payload or None if invalid."""
        try:
            message_data = message.get('data', {})

            for field in ('correlation_id', 'event_type', 'availability_id'):
                if field not in message_data:
                    logger.error(f"Missing required field '{field}' in message")
                    return None

            return message_data

        except Exception as e:
            logger.error(f"Failed to parse message: {str(e)}")
            return None

    def _build_create_schema(self, availability_data: Dict[str, Any]):
        """Map source data to RefCentreActivityAvailabilityCreate; returns None if the data is unusable."""
        from pear_schedule.schemas.ref_centre_activity_availability import RefCentreActivityAvailabilityCreate

        mapped = self.map_centre_activity_availability_create(availability_data)
        if not mapped:
            logger.error(f"Failed to map centre activity availability data: {availability_data}")
            return None
        try:
            return RefCentreActivityAvailabilityCreate(**mapped)
        except Exception as e:
            logger.error(f"Failed to create RefCentreActivityAvailabilityCreate schema: {str(e)} - mapped data: {mapped}")
            return None

    def _handle_created(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle availability creation events (also used by the backfill sync script)."""
        availability_id = message_data['availability_id']
        try:
            ref_availability = self._build_create_schema(message_data.get('availability_data', {}))
            if ref_availability is None:
                return MessageProcessingResult.FAILED_PERMANENT

            result, was_duplicate = self.create_ref_centre_activity_availability(
                db=db,
                availability=ref_availability,
                correlation_id=message_data['correlation_id'],
                created_by=message_data.get('created_by') or 'activity_service',
                skip_duplicate_check=message_data.get('is_sync_event', False)
            )

            if was_duplicate:
                return MessageProcessingResult.DUPLICATE
            if result:
                logger.info(f"Successfully created centre activity availability {availability_id}")
                return MessageProcessingResult.SUCCESS
            return MessageProcessingResult.FAILED_RETRYABLE

        except Exception as e:
            # Includes FK violations when REF_CENTRE_ACTIVITY hasn't synced yet: retry,
            # then let the delivery limit route it to the DLQ instead of silently dropping it.
            logger.error(f"Error handling centre activity availability creation {availability_id}: {str(e)}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _handle_updated(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle availability update events using the full new_data snapshot."""
        from pear_schedule.schemas.ref_centre_activity_availability import RefCentreActivityAvailabilityUpdate

        availability_id = message_data['availability_id']
        is_sync_event = message_data.get('is_sync_event', False)
        try:
            new_data = message_data.get('new_data', {})
            full_record = self._build_create_schema(new_data)
            if full_record is None:
                return MessageProcessingResult.FAILED_PERMANENT

            # Full overwrite so cleared optional fields (e.g. StartDate -> None) propagate
            ref_update = RefCentreActivityAvailabilityUpdate(
                CentreActivityID=full_record.CentreActivityID,
                DaysOfWeek=full_record.DaysOfWeek,
                StartTime=full_record.StartTime,
                EndTime=full_record.EndTime,
                StartDate=full_record.StartDate,
                EndDate=full_record.EndDate,
                IsDeleted=full_record.IsDeleted,
                UpdatedDateTime=full_record.UpdatedDateTime,
                ModifiedById=message_data.get('modified_by') or full_record.ModifiedById or 'activity_service',
            )

            result, was_duplicate = self.update_ref_centre_activity_availability(
                db=db,
                availability_id=availability_id,
                availability_update=ref_update,
                correlation_id=message_data['correlation_id'],
                skip_duplicate_check=is_sync_event
            )

            if was_duplicate and not is_sync_event:
                return MessageProcessingResult.DUPLICATE

            if result is None:
                # Row missing (e.g. the create was never received) - upsert from the snapshot
                logger.warning(f"Centre activity availability {availability_id} not found for update - creating from snapshot")
                create_result, _ = self.create_ref_centre_activity_availability(
                    db=db,
                    availability=full_record,
                    correlation_id=message_data['correlation_id'],
                    created_by=ref_update.ModifiedById,
                    skip_duplicate_check=True,
                    record_event=False  # the update call above already recorded this correlation_id
                )
                return MessageProcessingResult.SUCCESS if create_result else MessageProcessingResult.FAILED_RETRYABLE

            logger.info(f"Successfully updated centre activity availability {availability_id}")
            return MessageProcessingResult.SUCCESS

        except Exception as e:
            logger.error(f"Error handling centre activity availability update {availability_id}: {str(e)}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _handle_deleted(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle availability (soft) deletion events."""
        from pear_schedule.schemas.ref_centre_activity_availability import RefCentreActivityAvailabilityDelete

        availability_id = message_data['availability_id']
        is_sync_event = message_data.get('is_sync_event', False)
        try:
            try:
                ref_delete = RefCentreActivityAvailabilityDelete(
                    UpdatedDateTime=message_data['timestamp'],
                    ModifiedById=message_data.get('deleted_by') or 'activity_service'
                )
            except Exception as e:
                logger.error(f"Invalid delete message for centre activity availability {availability_id}: {str(e)}")
                return MessageProcessingResult.FAILED_PERMANENT

            result, was_duplicate = self.delete_ref_centre_activity_availability(
                db=db,
                availability_id=availability_id,
                availability_delete=ref_delete,
                correlation_id=message_data['correlation_id'],
                skip_duplicate_check=is_sync_event
            )

            if was_duplicate and not is_sync_event:
                return MessageProcessingResult.DUPLICATE

            if result is None:
                logger.warning(f"Centre activity availability {availability_id} not found for deletion - nothing to do")
            else:
                logger.info(f"Successfully processed deletion for centre activity availability {availability_id}")
            return MessageProcessingResult.SUCCESS

        except Exception as e:
            logger.error(f"Error handling centre activity availability deletion {availability_id}: {str(e)}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for monitoring."""
        try:
            return {
                "status": "healthy",
                "service": "centre_activity_availability_consumer",
                "is_consuming": self.is_consuming,
                "queues": self.availability_queues,
                "rabbitmq_connected": self.client.is_connected() if self.client else False
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    def close(self):
        """Close connections"""
        if self.client:
            self.client.close()
            logger.info("Scheduler centre activity availability consumer connections closed")
