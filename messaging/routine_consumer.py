import logging
import threading
from typing import Dict, Any, Optional
from contextlib import contextmanager

from .rabbitmq_client import RabbitMQClient
from pear_schedule.models.processed_events_model import MessageProcessingResult

logger = logging.getLogger(__name__)

class RoutineConsumer:
    """
    Consumer for activity routine events with separated CRUD operations.

    This consumer processes activity routine events from the activity.updates exchange
    and updates the scheduler's local REF_ACTIVITY_ROUTINE table with idempotency guarantees.
    """

    def __init__(self):
        self.client = RabbitMQClient("scheduler-routine-consumer")
        self.routine_queues = [
            "scheduler.activity.routine.created",
            "scheduler.activity.routine.updated",
            "scheduler.activity.routine.deleted"
        ]
        self.shutdown_event = None
        self.is_consuming = False

        from pear_schedule.crud.ref_activity_routine_crud import (
            create_ref_activity_routine,
            update_ref_activity_routine,
            delete_ref_activity_routine,
            is_event_already_processed
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import (
            map_routine_create,
            map_routine_update
        )

        self.create_ref_activity_routine = create_ref_activity_routine
        self.update_ref_activity_routine = update_ref_activity_routine
        self.delete_ref_activity_routine = delete_ref_activity_routine
        self.is_event_already_processed = is_event_already_processed
        self.get_db = get_db

        self.map_routine_create = map_routine_create
        self.map_routine_update = map_routine_update

    @contextmanager
    def get_db_transaction(self):
        """Context manager for database transactions with proper cleanup"""
        db = next(self.get_db())
        try:
            logger.debug("Started database session transaction")
            yield db
            logger.debug("Database session transaction completed")
        except Exception as e:
            logger.error(f"Rolling back transaction due to error: {e}")
            db.rollback()
            raise
        finally:
            db.close()
            logger.debug("Closed database session")

    def _flush_logs(self):
        """Force flush all log handlers to ensure logs are written immediately"""
        try:
            for handler in logging.getLogger().handlers:
                handler.flush()
            for handler in logger.handlers:
                handler.flush()
        except Exception:
            pass

    def set_shutdown_event(self, shutdown_event: threading.Event):
        """Set the shutdown event for graceful shutdown"""
        self.shutdown_event = shutdown_event
        if self.client:
            self.client.set_shutdown_event(shutdown_event)

    def setup_consumer(self):
        """Set up consumer to listen to existing activity routine queues"""
        try:
            self.client.connect()

            self.client.channel.exchange_declare(
                exchange='activity.updates',
                exchange_type='topic',
                durable=True
            )

            for queue_name in self.routine_queues:
                self.client.consume(queue_name, self._handle_message_wrapper)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")

            logger.info("Scheduler activity routine consumer setup complete")

        except Exception as e:
            logger.error(f"Failed to setup scheduler activity routine consumer: {str(e)}")
            raise

    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler activity routine consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler activity routine consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False

    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping activity routine consumer...")
        self.is_consuming = False
        if self.client:
            self.client.stop_consuming()

    def _handle_message_wrapper(self, message: Dict[str, Any]) -> bool:
        """Wrapper for message handling with proper acknowledgment logic."""
        try:
            message_correlation = message.get('data', {}).get('correlation_id', 'UNKNOWN')
            logger.debug(f"RECEIVED MESSAGE: correlation_id={message_correlation}")

            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("Shutdown signal received, stopping message processing")
                return False

            result = self._process_routine_message(message)
            self._flush_logs()

            if result == MessageProcessingResult.SUCCESS:
                logger.debug("Message processed successfully")
                return True
            elif result == MessageProcessingResult.DUPLICATE:
                logger.info("Duplicate message processed (idempotent)")
                return True
            elif result == MessageProcessingResult.FAILED_RETRYABLE:
                logger.warning("Message processing failed (retryable)")
                return False
            elif result == MessageProcessingResult.FAILED_PERMANENT:
                logger.error("Message processing failed permanently")
                return True
            else:
                logger.error(f"Unknown processing result: {result}")
                return False

        except Exception as e:
            logger.error(f"Fatal error in message wrapper: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            self._flush_logs()
            return False

    def _process_routine_message(self, message: Dict[str, Any]) -> MessageProcessingResult:
        """Process activity routine message with sync event support."""
        try:
            message_data = self._parse_message(message)
            if not message_data:
                return MessageProcessingResult.FAILED_PERMANENT

            correlation_id = message_data['correlation_id']
            event_type = message_data['event_type']
            routine_id = message_data['routine_id']
            is_sync_event = message_data.get('is_sync_event', False)
            sync_reason = message_data.get('sync_reason')

            logger.info(f"Processing {event_type} for activity routine {routine_id} (correlation: {correlation_id}, sync: {is_sync_event}, reason: {sync_reason})")

            with self.get_db_transaction() as db:
                # For sync events, bypass duplicate check in CRUD
                if not is_sync_event and self.is_event_already_processed(db, correlation_id):
                    logger.info(f"Event already processed: {correlation_id}")
                    return MessageProcessingResult.DUPLICATE
                elif is_sync_event:
                    logger.info(f"Sync event detected - bypassing idempotency check for {correlation_id}")

                if event_type == 'ROUTINE_CREATED':
                    result = self._handle_routine_created(db, message_data)
                elif event_type == 'ROUTINE_UPDATED':
                    result = self._handle_routine_updated(db, message_data)
                elif event_type == 'ROUTINE_DELETED':
                    result = self._handle_routine_deleted(db, message_data)
                else:
                    logger.error(f"Unknown event type: {event_type}")
                    return MessageProcessingResult.FAILED_PERMANENT

                logger.debug(f"Transaction completed for {correlation_id}")

            # Only verify if the result was SUCCESS
            if result == MessageProcessingResult.SUCCESS:
                verification_db = next(self.get_db())
                try:
                    verified = self.is_event_already_processed(verification_db, correlation_id)
                    if not verified:
                        logger.error(f"CRITICAL: processed_events record missing for {correlation_id}")
                        return MessageProcessingResult.FAILED_RETRYABLE
                finally:
                    verification_db.close()

            return result

        except Exception as e:
            logger.error(f"Error processing activity routine message: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _parse_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse and validate message structure."""
        try:
            message_data = message.get('data', {})

            required_fields = ['correlation_id', 'event_type', 'routine_id']
            for field in required_fields:
                if field not in message_data:
                    logger.error(f"Missing required field '{field}' in message")
                    return None

            logger.debug(f"Parsed message: {message_data}")
            return message_data

        except Exception as e:
            logger.error(f"Failed to parse message: {str(e)}")
            return None

    def _handle_routine_created(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity routine creation events"""
        try:
            correlation_id = message_data['correlation_id']
            routine_id = message_data['routine_id']
            routine_data = message_data.get('routine_data', {})
            created_by = message_data.get('created_by', 'activity_service')

            logger.info(f"Handling activity routine creation for routine {routine_id}")
            logger.debug(f"Routine data: {routine_data}")

            mapped_routine_data = self.map_routine_create(routine_data)
            if not mapped_routine_data:
                logger.error(f"Failed to map activity routine data for routine {routine_id}")
                logger.debug(f"Source data: {routine_data}")
                return MessageProcessingResult.FAILED_PERMANENT

            logger.debug(f"Mapped routine data: {mapped_routine_data}")

            from pear_schedule.schemas.ref_activity_routine import RefActivityRoutineCreate
            try:
                ref_routine_data = RefActivityRoutineCreate(**mapped_routine_data)
            except Exception as e:
                logger.error(f"Failed to create RefActivityRoutineCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_routine_data}")
                return MessageProcessingResult.FAILED_PERMANENT

            result, was_duplicate = self.create_ref_activity_routine(
                db=db,
                routine=ref_routine_data,
                correlation_id=correlation_id,
                created_by=created_by
            )

            if was_duplicate:
                logger.info(f"Duplicate creation event for activity routine {routine_id}")
                return MessageProcessingResult.DUPLICATE

            if result:
                logger.info(f"Successfully created activity routine {routine_id}")
                return MessageProcessingResult.SUCCESS
            else:
                logger.error(f"Failed to create activity routine {routine_id}")
                return MessageProcessingResult.FAILED_RETRYABLE

        except ValueError as e:
            logger.warning(f"Business logic error creating activity routine: {str(e)}")
            return MessageProcessingResult.FAILED_PERMANENT
        except Exception as e:
            logger.error(f"Error handling activity routine creation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _handle_routine_updated(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity routine update events"""
        try:
            correlation_id = message_data['correlation_id']
            routine_id = message_data['routine_id']
            routine_data = message_data.get('new_data', {})
            modified_by = message_data.get('modified_by', 'activity_service')
            is_sync_event = message_data.get('is_sync_event', False)

            logger.info(f"Handling activity routine update for routine {routine_id}")

            mapped_update_data = self.map_routine_update(routine_data)
            if not mapped_update_data:
                logger.error(f"Failed to map activity routine update data for routine {routine_id}")
                logger.debug(f"Source update data: {routine_data}")
                return MessageProcessingResult.FAILED_PERMANENT

            logger.debug(f"Mapped update data: {mapped_update_data}")

            from pear_schedule.schemas.ref_activity_routine import RefActivityRoutineUpdate
            try:
                ref_routine_update = RefActivityRoutineUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefActivityRoutineUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return MessageProcessingResult.FAILED_PERMANENT

            # For sync events, bypass duplicate check in CRUD
            result, was_duplicate = self.update_ref_activity_routine(
                db=db,
                routine_id=routine_id,
                routine_update=ref_routine_update,
                correlation_id=correlation_id,
                skip_duplicate_check=is_sync_event
            )

            if was_duplicate and not is_sync_event:
                logger.info(f"Duplicate update event for activity routine {routine_id}")
                return MessageProcessingResult.DUPLICATE

            if result is None:
                if is_sync_event:
                    # For sync events, try to create if doesn't exist
                    logger.warning(f"Routine {routine_id} not found during sync - attempting to create")
                    try:
                        from pear_schedule.schemas.ref_activity_routine import RefActivityRoutineCreate
                        mapped_routine_data = self.map_routine_create(routine_data)
                        if mapped_routine_data:
                            ref_routine_data = RefActivityRoutineCreate(**mapped_routine_data)
                            create_result, _ = self.create_ref_activity_routine(
                                db=db,
                                routine=ref_routine_data,
                                correlation_id=correlation_id,
                                created_by=modified_by
                            )
                            if create_result:
                                logger.info(f"Successfully created routine {routine_id} during sync")
                                return MessageProcessingResult.SUCCESS
                    except Exception as e:
                        logger.error(f"Failed to create routine during sync: {str(e)}")
                        return MessageProcessingResult.FAILED_RETRYABLE
                else:
                    logger.warning(f"Activity routine {routine_id} not found for update")
                return MessageProcessingResult.SUCCESS

            logger.info(f"Successfully updated activity routine {routine_id}")
            return MessageProcessingResult.SUCCESS

        except Exception as e:
            logger.error(f"Error handling activity routine update: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _handle_routine_deleted(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle routine deletion events with source timestamp extraction"""
        try:
            correlation_id = message_data['correlation_id']
            routine_id = message_data['routine_id']
            deleted_by = message_data.get('deleted_by', 'activity_service')
            is_sync_event = message_data.get('is_sync_event', False)

            logger.info(f"Handling routine deletion for {routine_id}")

            # Extract timestamp from 'timestamp'
            deleted_datetime = message_data.get('timestamp')

            # Parse datetime string if needed
            if deleted_datetime and isinstance(deleted_datetime, str):
                from datetime import datetime

                try:
                    deleted_datetime = datetime.fromisoformat(deleted_datetime.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Failed to parse timestamp: {deleted_datetime}, using current time")
                    deleted_datetime = datetime.now()
            elif not deleted_datetime:
                # Fallback to current time if no timestamp provided
                from datetime import datetime

                deleted_datetime = datetime.now()
                logger.warning(f"No timestamp in delete message for routine {routine_id}, using current time")

            logger.debug(f"Using deletion timestamp: {deleted_datetime}")

            from pear_schedule.schemas.ref_activity_routine import RefActivityRoutineDelete

            try:
                ref_routine_delete = RefActivityRoutineDelete(
                    UpdatedDateTime=deleted_datetime,
                    ModifiedById=deleted_by
                )
            except Exception as e:
                logger.error(f"Pydantic validation failed: {str(e)}")
                return MessageProcessingResult.FAILED_PERMANENT

            result, was_duplicate = self.delete_ref_activity_routine(
                db=db,
                routine_id=routine_id,
                routine_delete=ref_routine_delete,
                correlation_id=correlation_id,
                skip_duplicate_check=is_sync_event
            )

            if was_duplicate and not is_sync_event:
                return MessageProcessingResult.DUPLICATE

            logger.info(f"Successfully processed deletion for routine {routine_id}")
            return MessageProcessingResult.SUCCESS

        except Exception as e:
            logger.error(f"Error handling routine deletion: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for monitoring."""
        try:
            return {
                "status": "healthy",
                "service": "routine_consumer",
                "is_consuming": self.is_consuming,
                "queues": self.routine_queues,
                "rabbitmq_connected": self.client.is_connected if self.client else False
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
            logger.info("Scheduler activity routine consumer connections closed")
