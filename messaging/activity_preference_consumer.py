import logging
import threading
import json
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager

from .rabbitmq_client import RabbitMQClient
from pear_schedule.models.processed_events_model import MessageProcessingResult

logger = logging.getLogger(__name__)

class ActivityPreferenceConsumer:
    """
    Consumer for activity preference events with separated CRUD operations.
    
    This consumer processes activity preference events from the activity.preferences exchange
    and updates the scheduler's local REF_ACTIVITY_PREFERENCE table with idempotency guarantees.
    """
    
    def __init__(self):
        self.client = RabbitMQClient("scheduler-activity-preference-consumer")
        self.preference_queues = [
            "scheduler.activity.preference.created",
            "scheduler.activity.preference.updated", 
            "scheduler.activity.preference.deleted"
        ]
        self.shutdown_event = None
        self.is_consuming = False
        
        from pear_schedule.crud.ref_activity_preference_crud import (
            create_ref_activity_preference,
            update_ref_activity_preference,
            delete_ref_activity_preference,
            is_event_already_processed
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import (
            map_activity_preference_create,
            map_activity_preference_update
        )
        
        self.create_ref_activity_preference = create_ref_activity_preference
        self.update_ref_activity_preference = update_ref_activity_preference
        self.delete_ref_activity_preference = delete_ref_activity_preference
        self.is_event_already_processed = is_event_already_processed
        self.get_db = get_db
        
        self.map_activity_preference_create = map_activity_preference_create
        self.map_activity_preference_update = map_activity_preference_update
    
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
        """Set up consumer to listen to existing activity preference queues"""
        try:
            self.client.connect()
            
            self.client.channel.exchange_declare(
                exchange='activity.updates',
                exchange_type='topic',
                durable=True
            )
            
            for queue_name in self.preference_queues:
                self.client.consume(queue_name, self._handle_message_wrapper)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")
            
            logger.info("Scheduler activity preference consumer setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduler activity preference consumer: {str(e)}")
            raise
    
    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler activity preference consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler activity preference consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False
    
    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping activity preference consumer...")
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
            
            result = self._process_activity_preference_message(message)
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
    
    def _process_activity_preference_message(self, message: Dict[str, Any]) -> MessageProcessingResult:
        """Process activity preference message with sync event support."""
        try:
            message_data = self._parse_message(message)
            if not message_data:
                return MessageProcessingResult.FAILED_PERMANENT
            
            correlation_id = message_data['correlation_id']
            event_type = message_data['event_type']
            preference_id = message_data['preference_id']
            is_sync_event = message_data.get('is_sync_event', False)
            sync_reason = message_data.get('sync_reason')
            
            logger.info(f"Processing {event_type} for activity preference {preference_id} (correlation: {correlation_id}, sync: {is_sync_event}, reason: {sync_reason})")
            
            with self.get_db_transaction() as db:
                # For sync events, bypass duplicate check in CRUD
                if not is_sync_event and self.is_event_already_processed(db, correlation_id):
                    logger.info(f"Event already processed: {correlation_id}")
                    return MessageProcessingResult.DUPLICATE
                elif is_sync_event:
                    logger.info(f"Sync event detected - bypassing idempotency check for {correlation_id}")
                
                if event_type == 'ACTIVITY_PREFERENCE_CREATED':
                    result = self._handle_activity_preference_created(db, message_data)
                elif event_type == 'ACTIVITY_PREFERENCE_UPDATED':
                    result = self._handle_activity_preference_updated(db, message_data)
                elif event_type == 'ACTIVITY_PREFERENCE_DELETED':
                    result = self._handle_activity_preference_deleted(db, message_data)
                else:
                    logger.error(f"Unknown event type: {event_type}")
                    return MessageProcessingResult.FAILED_PERMANENT
                
                logger.debug(f"Transaction completed for {correlation_id}")
            
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
            logger.error(f"Error processing activity preference message: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _parse_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse and validate message structure."""
        try:
            message_data = message.get('data', {})
            
            required_fields = ['correlation_id', 'event_type', 'preference_id']
            for field in required_fields:
                if field not in message_data:
                    logger.error(f"Missing required field '{field}' in message")
                    return None
            
            logger.debug(f"Parsed message: {message_data}")
            return message_data
            
        except Exception as e:
            logger.error(f"Failed to parse message: {str(e)}")
            return None
    
    def _handle_activity_preference_created(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity preference creation events"""
        try:
            correlation_id = message_data['correlation_id']
            preference_id = message_data['preference_id']
            preference_data = message_data.get('data', {})
            created_by = message_data.get('created_by', 'activity_service')
            
            logger.info(f"Handling activity preference creation for preference {preference_id}")
            logger.debug(f"Preference data: {preference_data}")
            
            mapped_preference_data = self.map_activity_preference_create(preference_data)
            if not mapped_preference_data:
                logger.error(f"Failed to map activity preference data for preference {preference_id}")
                logger.debug(f"Source data: {preference_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped preference data: {mapped_preference_data}")
            
            from pear_schedule.schemas.ref_activity_preference import RefActivityPreferenceCreate
            try:
                ref_preference_data = RefActivityPreferenceCreate(**mapped_preference_data)
            except Exception as e:
                logger.error(f"Failed to create RefActivityPreferenceCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_preference_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            result, was_duplicate = self.create_ref_activity_preference(
                db=db,
                preference=ref_preference_data,
                correlation_id=correlation_id,
                created_by=created_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate creation event for activity preference {preference_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result:
                logger.info(f"Successfully created activity preference {preference_id}")
                return MessageProcessingResult.SUCCESS
            else:
                logger.error(f"Failed to create activity preference {preference_id}")
                return MessageProcessingResult.FAILED_RETRYABLE
            
        except ValueError as e:
            logger.warning(f"Business logic error creating activity preference: {str(e)}")
            return MessageProcessingResult.FAILED_PERMANENT
        except Exception as e:
            logger.error(f"Error handling activity preference creation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_activity_preference_updated(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity preference update events"""
        try:
            correlation_id = message_data['correlation_id']
            preference_id = message_data['preference_id']
            preference_data = message_data.get('new_data', {})
            modified_by = message_data.get('modified_by', 'activity_service')
            is_sync_event = message_data.get('is_sync_event', False)
            
            logger.info(f"Handling activity preference update for preference {preference_id}")
            
            mapped_update_data = self.map_activity_preference_update(preference_data)
            if not mapped_update_data:
                logger.error(f"Failed to map activity preference update data for preference {preference_id}")
                logger.debug(f"Source update data: {preference_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped update data: {mapped_update_data}")
            
            from pear_schedule.schemas.ref_activity_preference import RefActivityPreferenceUpdate
            try:
                ref_preference_update = RefActivityPreferenceUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefActivityPreferenceUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # For sync events, bypass duplicate check in CRUD
            result, was_duplicate = self.update_ref_activity_preference(
                db=db,
                preference_id=preference_id,
                preference_update=ref_preference_update,
                correlation_id=correlation_id,
                skip_duplicate_check=is_sync_event
            )
            
            if was_duplicate and not is_sync_event:
                logger.info(f"Duplicate update event for activity preference {preference_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                if is_sync_event:
                    # For sync events, try to create if doesn't exist
                    logger.warning(f"Preference {preference_id} not found during sync - attempting to create")
                    try:
                        from pear_schedule.schemas.ref_activity_preference import RefActivityPreferenceCreate
                        mapped_preference_data = self.map_activity_preference_create(preference_data)
                        if mapped_preference_data:
                            ref_preference_data = RefActivityPreferenceCreate(**mapped_preference_data)
                            create_result, _ = self.create_ref_activity_preference(
                                db=db,
                                preference=ref_preference_data,
                                correlation_id=correlation_id,
                                created_by=modified_by
                            )
                            if create_result:
                                logger.info(f"Successfully created preference {preference_id} during sync")
                                return MessageProcessingResult.SUCCESS
                    except Exception as e:
                        logger.error(f"Failed to create preference during sync: {str(e)}")
                        return MessageProcessingResult.FAILED_RETRYABLE
                else:
                    logger.warning(f"Activity preference {preference_id} not found for update")
                return MessageProcessingResult.SUCCESS
            
            logger.info(f"Successfully updated activity preference {preference_id}")
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling activity preference update: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_activity_preference_deleted(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle preference deletion events with source timestamp extraction"""
        try:
            correlation_id = message_data['correlation_id']
            preference_id = message_data['preference_id']
            preference_data = message_data.get('preference_data', {}) 
            deleted_by = message_data.get('deleted_by', 'activity_service')
            is_sync_event = message_data.get('is_sync_event', False)
            
            logger.info(f"Handling preference deletion for {preference_id}")
            
            deleted_datetime = message_data['timestamp']
            
            from pear_schedule.schemas.ref_activity_preference import RefActivityPreferenceDelete
            
            try:
                ref_preference_delete = RefActivityPreferenceDelete(
                    UpdatedDateTime=deleted_datetime,
                    ModifiedById=deleted_by
                )
            except Exception as e:
                logger.error(f"Pydantic validation failed: {str(e)}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            result, was_duplicate = self.delete_ref_activity_preference(
                db=db,
                preference_id=preference_id,
                preference_delete=ref_preference_delete,
                correlation_id=correlation_id,
                skip_duplicate_check=is_sync_event
            )
            
            if was_duplicate and not is_sync_event:
                return MessageProcessingResult.DUPLICATE
            
            logger.info(f"Successfully processed deletion for preference {preference_id}")
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling preference deletion: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for monitoring."""
        try:
            return {
                "status": "healthy",
                "service": "activity_preference_consumer",
                "is_consuming": self.is_consuming,
                "queues": self.preference_queues,
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
            logger.info("Scheduler activity preference consumer connections closed")
