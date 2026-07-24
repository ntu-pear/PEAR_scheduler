import logging
import threading
from typing import Dict, Any, Optional
from contextlib import contextmanager

from .rabbitmq_client import RabbitMQClient
from pear_schedule.models.processed_events_model import MessageProcessingResult

logger = logging.getLogger(__name__)


class AdhocConsumer:
    """
    Consumer for adhoc events with separated CRUD operations.

    This consumer processes adhoc activity events from the activity.updates exchange
    and updates the scheduler's local ADHOC table with idempotency guarantees.
    """

    def __init__(self):
        self.client = RabbitMQClient("scheduler-adhoc-consumer")
        self.adhoc_queues = [
            "scheduler.activity.adhoc.created",
            "scheduler.activity.adhoc.updated",
            "scheduler.activity.adhoc.deleted",
        ]
        self.shutdown_event = None
        self.is_consuming = False

        from pear_schedule.crud.ref_adhoc_crud import (
            create_ref_adhoc,
            update_ref_adhoc,
            delete_ref_adhoc,
            is_event_already_processed,
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import map_adhoc_create, map_adhoc_update

        self.create_ref_adhoc = create_ref_adhoc
        self.update_ref_adhoc = update_ref_adhoc
        self.delete_ref_adhoc = delete_ref_adhoc
        self.is_event_already_processed = is_event_already_processed
        self.get_db = get_db
        self.map_adhoc_create = map_adhoc_create
        self.map_adhoc_update = map_adhoc_update

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
        """Set up consumer to listen to adhoc activity queues"""
        try:
            self.client.connect()

            self.client.channel.exchange_declare(exchange="activity.updates", exchange_type="topic", durable=True)

            for queue_name in self.adhoc_queues:
                self.client.consume(queue_name, self._handle_message_wrapper)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")

            logger.info("Scheduler adhoc consumer setup complete")

        except Exception as e:
            logger.error(f"Failed to setup scheduler adhoc consumer: {str(e)}")
            raise

    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler adhoc consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler adhoc consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False

    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping adhoc consumer...")
        self.is_consuming = False
        if self.client:
            self.client.stop_consuming()

    def _handle_message_wrapper(self, message: Dict[str, Any]) -> bool:
        """Wrapper for message handling with proper acknowledgment logic."""
        try:
            message_correlation = message.get("data", {}).get("correlation_id", "UNKNOWN")
            logger.debug(f"RECEIVED MESSAGE: correlation_id={message_correlation}")

            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("Shutdown signal received, stopping message processing")
                return False

            result = self._process_adhoc_message(message)
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

    def _process_adhoc_message(self, message: Dict[str, Any]) -> MessageProcessingResult:
        """
        Process activity message with FIXED session management and error handling.
        """
        try:
            message_data = self._parse_message(message)
            if not message_data:
                return MessageProcessingResult.FAILED_PERMANENT

            correlation_id = message_data["correlation_id"]
            event_type = message_data["event_type"]
            adhoc_id = message_data["adhoc_id"]
            is_sync_event = message_data.get("is_sync_event", False)
            sync_reason = message_data.get("sync_reason")

            logger.info(
                f"Processing {event_type} for adhoc {adhoc_id} (correlation: {correlation_id}, sync: {is_sync_event}, sync_reason: {sync_reason})"
            )

            # Use context manager for guaranteed transaction handling
            with self.get_db_transaction() as db:
                # Quick check for duplicates (BYPASS for sync events)
                if not is_sync_event and self.is_event_already_processed(db, correlation_id):
                    logger.info(f"Event already processed: {correlation_id}")
                    return MessageProcessingResult.DUPLICATE
                elif is_sync_event:
                    logger.info(f"Sync event detected - bypassing idempotency check for {correlation_id}")

                # Route to appropriate handler
                if event_type == "ADHOC_CREATED":
                    result = self._handle_adhoc_created(db, message_data)
                elif event_type == "ADHOC_UPDATED":
                    result = self._handle_adhoc_updated(db, message_data)
                elif event_type == "ADHOC_DELETED":
                    result = self._handle_adhoc_deleted(db, message_data)
                else:
                    logger.error(f"Unknown event type: {event_type}")
                    return MessageProcessingResult.FAILED_PERMANENT

                # Transaction will be comitted automatically by context manager
                logger.debug(f"Transaction completed for {correlation_id}")

            # Only verify if the result was SUCCESS
            if result == MessageProcessingResult.SUCCESS:
                # Verification step outside the transaction
                verification_db = next(self.get_db())
                try:
                    verified = self.is_event_already_processed(verification_db, correlation_id)
                    if not verified:
                        logger.warning(f"Event not found in processed events after commit: {correlation_id}")
                        return MessageProcessingResult.FAILED_RETRYABLE
                finally:
                    verification_db.close()

            return result

        except Exception as e:
            logger.error(f"Error processing adhoc message: {str(e)}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _parse_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse and validate message structure.

        Returns parsed message data or None if invalid.
        """
        try:
            # Extract message data
            message_data = message.get("data", {})

            # Validate required fields for idempotency
            required_fields = ["correlation_id", "event_type", "adhoc_id"]
            for field in required_fields:
                if field not in message_data:
                    logger.error(f"Missing required field '{field}' in message")
                    return None

            # Log the full message for debugging
            logger.debug(f"Parsed message: {message_data}")
            return message_data

        except Exception as e:
            logger.error(f"Failed to parse message: {str(e)}")
            return None

    def _handle_adhoc_created(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle adhoc creation event"""
        try:
            correlation_id = message_data["correlation_id"]
            adhoc_id = message_data["adhoc_id"]
            adhoc_data = message_data.get("activity_data", {})
            created_by = message_data.get("created_by", "activity_service")

            logger.info(f"Handling adhoc creation for adhoc {adhoc_id}")
            logger.debug(f"Adhoc data: {adhoc_data}")

            # Convert adhoc data to scheduler's RefAdhoc format
            mapped_adhoc_data = self.map_adhoc_create(adhoc_data)
            if not mapped_adhoc_data:
                logger.error(f"Failed to map adhoc data for adhoc {adhoc_id}")
                logger.debug(f"Source data: {adhoc_data}")
                return MessageProcessingResult.FAILED_PERMANENT

            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_adhoc import RefAdhocCreate

            try:
                ref_adhoc_data = RefAdhocCreate(**mapped_adhoc_data)
            except Exception as e:
                logger.error(f"Failed to create RefAdhocCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_adhoc_data}")
                return MessageProcessingResult.FAILED_PERMANENT

            # Create adhoc using CRUD operation with idempotency
            result, was_duplicate = self.create_ref_adhoc(
                db=db, adhoc=ref_adhoc_data, correlation_id=correlation_id, created_by=created_by
            )

            if was_duplicate:
                logger.info(f"Duplicate creation event for adhoc {adhoc_id}")
                return MessageProcessingResult.DUPLICATE

            if result:
                logger.info(f"Successfully created adhoc {adhoc_id}")
                return MessageProcessingResult.SUCCESS
            else:
                logger.error(f"Failed to create adhoc {adhoc_id}")
                return MessageProcessingResult.FAILED_RETRYABLE

        except ValueError as e:
            # Business logic error (adhoc already exists)
            logger.warning(f"Business logic error creating adhoc: {str(e)}")
            return MessageProcessingResult.FAILED_PERMANENT
        except Exception as e:
            logger.error(f"Error handling adhoc creation: {str(e)}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _handle_adhoc_updated(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle adhoc update event"""
        try:
            correlation_id = message_data["correlation_id"]
            adhoc_id = message_data["adhoc_id"]
            adhoc_data = message_data.get("adhoc_data", {})
            modified_by = message_data.get("modified_by", "activity_service")
            is_sync_event = message_data.get("is_sync_event", False)

            logger.info(f"Handling adhoc creation for adhoc {adhoc_id}")
            logger.debug(f"Adhoc data: {adhoc_data}")

            # Convert new adhoc data to scheduler's RefAdhoc format
            mapped_update_data = self.map_adhoc_update(adhoc_data)
            if not mapped_update_data:
                logger.error(f"Failed to map adhoc update data for adhoc {adhoc_id}")
                logger.debug(f"Source update data: {adhoc_data}")
                return MessageProcessingResult.FAILED_PERMANENT

            logger.debug(f"Mapped update data: {mapped_update_data}")

            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_adhoc import RefAdhocUpdate

            try:
                ref_adhoc_update = RefAdhocUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefAdhocUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return MessageProcessingResult.FAILED_PERMANENT

            # Update adhoc using CRUD operation with idempotency
            # For sync events, bypass duplicate check in CRUD
            result, was_duplicate = self.update_ref_adhoc(
                db=db,
                adhoc_id=adhoc_id,
                adhoc_update=ref_adhoc_update,
                correlation_id=correlation_id,
                skip_duplicate_check=is_sync_event,
            )

            if was_duplicate and not is_sync_event:
                logger.info(f"Duplicate update event for adhoc {adhoc_id}")
                return MessageProcessingResult.DUPLICATE

            if result is None:
                # Adhoc doesn't exist in scheduler DB
                if is_sync_event:
                    # For sync events, try to create the adhoc if it doesn't exist
                    logger.warning(f"Adhoc {adhoc_id} not found during sync - attempting to create")
                    try:
                        from pear_schedule.schemas.ref_adhoc import RefAdhocCreate

                        mapped_adhoc_data = self.map_adhoc_create(adhoc_data)
                        if mapped_adhoc_data:
                            ref_adhoc_data = RefAdhocCreate(**mapped_adhoc_data)
                            create_result, _ = self.create_ref_adhoc(
                                db=db, adhoc=ref_adhoc_data, correlation_id=correlation_id, created_by=modified_by
                            )
                            if create_result:
                                logger.info(f"Successfully created adhoc {adhoc_id} during sync")
                                return MessageProcessingResult.SUCCESS
                    except Exception as e:
                        logger.error(f"Failed to create adhoc during sync: {str(e)}")
                        return MessageProcessingResult.FAILED_RETRYABLE
                else:
                    logger.warning(f"Adhoc {adhoc_id} not found for update")
                    logger.warning("Adhoc should be created by ADHOC_CREATED message first")
                return MessageProcessingResult.SUCCESS  # Don't requeue

            logger.info(f"Successfully updated adhoc {adhoc_id}")

            return MessageProcessingResult.SUCCESS

        except Exception as e:
            logger.error(f"Error handling adhoc update: {str(e)}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def _handle_adhoc_deleted(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle adhoc deletion event with source timestamp extraction"""
        try:
            correlation_id = message_data["correlation_id"]
            adhoc_id = message_data["adhoc_id"]
            adhoc_data = message_data.get("adhoc_data", {})
            deleted_by = message_data.get("deleted_by", "activity_service")
            is_sync_event = message_data.get("is_sync_event", False)

            logger.info(f"Handling adhoc deletion for adhoc {adhoc_id}")

            # Extract timestamp in the timestamp
            deleted_datetime = message_data["timestamp"]

            # Parse datetime string if needed
            if deleted_datetime and isinstance(deleted_datetime, str):
                from datetime import datetime

                try:
                    deleted_datetime = datetime.fromisoformat(deleted_datetime.replace("Z", "+00:00"))
                except ValueError:
                    logger.warning(f"Failed to parse timestamp: {deleted_datetime}, using current time")
                    deleted_datetime = datetime.now()
            elif not deleted_datetime:
                # Fallback to current time if no timestamp provided
                from datetime import datetime

                deleted_datetime = datetime.now()
                logger.warning(f"No timestamp in delete message for adhoc {adhoc_id}, using current time")

            logger.debug(f"Using deletion timestamp: {deleted_datetime}")

            from pear_schedule.schemas.ref_adhoc import RefAdhocDelete

            try:
                ref_adhoc_delete = RefAdhocDelete(
                    UpdatedDateTime=deleted_datetime,
                    ModifiedById=deleted_by,
                )
            except Exception as e:
                logger.error(f"Pydantic validation failed: {str(e)}")
                return MessageProcessingResult.FAILED_PERMANENT

            result, was_duplicate = self.delete_ref_adhoc(
                db=db,
                adhoc_id=adhoc_id,
                adhoc_delete=ref_adhoc_delete,
                correlation_id=correlation_id,
                skip_duplicate_check=is_sync_event,
            )

            if was_duplicate and not is_sync_event:
                logger.info(f"Duplicate deletion event for adhoc {adhoc_id}")
                return MessageProcessingResult.DUPLICATE

            if result is None:
                logger.warning(f"Adhoc {adhoc_id} not found for deletion")
            else:
                logger.info(f"Successfully processed deletion for adhoc {adhoc_id}")

            return MessageProcessingResult.SUCCESS

        except Exception as e:
            logger.error(f"Error handling adhoc deletion: {str(e)}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get health status for monitoring.
        """
        try:
            return {
                "status": "healthy",
                "service": "adhoc_consumer",
                "is_consuming": self.is_consuming,
                "queues": self.adhoc_queues,
                "rabbitmq_connected": self.client.is_connected() if self.client else False,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def close(self):
        """Close connections"""
        if self.client:
            self.client.close()
            logger.info("Scheduler adhoc consumer connections closed")
