import logging
import threading
import json
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager

from .rabbitmq_client import RabbitMQClient
from pear_schedule.models.processed_events_model import MessageProcessingResult

logger = logging.getLogger(__name__)

class CentreActivityConsumer:
    """
    Consumer for centre activity events with separated CRUD operations.
    
    This consumer processes centre activity events from the activity.updates exchange
    and updates the scheduler's local REF_CENTRE_ACTIVITY table with idempotency guarantees.
    """
    
    def __init__(self):
        self.client = RabbitMQClient("scheduler-centre-activity-consumer")
        self.activity_queues = [
            "scheduler.activity.centre_activity.created",
            "scheduler.activity.centre_activity.updated", 
            "scheduler.activity.centre_activity.deleted"
        ]
        self.shutdown_event = None
        self.is_consuming = False
        
        # Import dependencies - adjust imports based on your actual structure
        from pear_schedule.crud.ref_centre_activity_crud import (
            create_ref_centre_activity,
            update_ref_centre_activity,
            delete_ref_centre_activity,
            is_event_already_processed
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import (
            map_centre_activity_create,
            map_centre_activity_update
        )
        
        self.create_ref_centre_activity = create_ref_centre_activity
        self.update_ref_centre_activity = update_ref_centre_activity
        self.delete_ref_centre_activity = delete_ref_centre_activity
        self.is_event_already_processed = is_event_already_processed
        self.get_db = get_db
        
        self.map_centre_activity_create = map_centre_activity_create
        self.map_centre_activity_update = map_centre_activity_update
    
    @contextmanager
    def get_db_transaction(self):
        """Context manager for database transactions with proper cleanup"""
        db = next(self.get_db())
        try:
            # SQLAlchemy sessions have implicit transactions - no need for explicit begin()
            logger.debug("Started database session transaction")
            yield db
            # Don't commit here - let the CRUD functions handle commits
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
            pass  # Don't let logging issues break message processing
    
    def set_shutdown_event(self, shutdown_event: threading.Event):
        """Set the shutdown event for graceful shutdown"""
        self.shutdown_event = shutdown_event
        if self.client:
            self.client.set_shutdown_event(shutdown_event)
    
    def setup_consumer(self):
        """Set up consumer to listen to existing activity queues"""
        try:
            self.client.connect()
            
            # Declare the activity.updates exchange (idempotent)
            self.client.channel.exchange_declare(
                exchange='activity.updates',
                exchange_type='topic',
                durable=True
            )
            
            # Set up consumers for each existing activity queue
            for queue_name in self.activity_queues:
                # Don't declare the queue - it already exists as quorum queue
                # Set up the consumer with proper message handling
                self.client.consume(queue_name, self._handle_message_wrapper)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")
            
            logger.info("Scheduler centre activity consumer setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduler centre activity consumer: {str(e)}")
            raise
    
    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler centre activity consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler centre activity consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False
    
    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping centre activity consumer...")
        self.is_consuming = False
        if self.client:
            self.client.stop_consuming()
    
    def _handle_message_wrapper(self, message: Dict[str, Any]) -> bool:
        """
        Wrapper for message handling with proper acknowledgment logic.
        
        Returns True if message should be acknowledged (success or permanent failure),
        False if message should be rejected/requeued (temporary failure).
        """
        try:
            # Log every message received for debugging
            message_correlation = message.get('data', {}).get('correlation_id', 'UNKNOWN')
            logger.debug(f"RECEIVED MESSAGE: correlation_id={message_correlation}")
            
            # Check if we should shutdown
            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("Shutdown signal received, stopping message processing")
                return False
            
            # Process the message
            result = self._process_centre_activity_message(message)
            
            # Force log flush after processing each message
            self._flush_logs()
            
            # Handle different processing results
            if result == MessageProcessingResult.SUCCESS:
                logger.debug("Message processed successfully")
                return True  # Acknowledge
                
            elif result == MessageProcessingResult.DUPLICATE:
                logger.info("Duplicate message processed (idempotent)")
                return True  # Acknowledge - duplicate is success
                
            elif result == MessageProcessingResult.FAILED_RETRYABLE:
                logger.warning("Message processing failed (retryable)")
                return False  # Reject and requeue
                
            elif result == MessageProcessingResult.FAILED_PERMANENT:
                logger.error("Message processing failed permanently")
                return True  # Acknowledge to send to DLQ
                
            else:
                logger.error(f"Unknown processing result: {result}")
                return False  # Reject and requeue
                
        except Exception as e:
            logger.error(f"Fatal error in message wrapper: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            self._flush_logs()
            return False  # Reject and requeue
    
    def _process_centre_activity_message(self, message: Dict[str, Any]) -> MessageProcessingResult:
        """
        Process centre activity message with FIXED session management and error handling.
        """
        try:
            # Parse and validate message structure
            message_data = self._parse_message(message)
            if not message_data:
                return MessageProcessingResult.FAILED_PERMANENT
            
            correlation_id = message_data['correlation_id']
            event_type = message_data['event_type']
            centre_activity_id = message_data['centre_activity_id']
            
            logger.info(f"Processing {event_type} for centre activity {centre_activity_id} (correlation: {correlation_id})")
            
            # Use context manager for guaranteed transaction handling
            with self.get_db_transaction() as db:
                # Quick check for duplicates
                if self.is_event_already_processed(db, correlation_id):
                    logger.info(f"Event already processed: {correlation_id}")
                    return MessageProcessingResult.DUPLICATE
                
                # Route to appropriate handler
                if event_type == 'CENTRE_ACTIVITY_CREATED':
                    result = self._handle_centre_activity_created(db, message_data)
                elif event_type == 'CENTRE_ACTIVITY_UPDATED':
                    result = self._handle_centre_activity_updated(db, message_data)
                elif event_type == 'CENTRE_ACTIVITY_DELETED':
                    result = self._handle_centre_activity_deleted(db, message_data)
                else:
                    logger.error(f"Unknown event type: {event_type}")
                    return MessageProcessingResult.FAILED_PERMANENT
                
                # Transaction will be committed automatically by context manager
                logger.debug(f"Transaction completed for {correlation_id}")
            
            # Verification step outside the transaction
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
            logger.error(f"Error processing centre activity message: {str(e)}")
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
            message_data = message.get('data', {})
            
            # Validate required fields for idempotency
            required_fields = ['correlation_id', 'event_type', 'centre_activity_id']
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
    
    def _handle_centre_activity_created(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle centre activity creation events with separation"""
        try:
            correlation_id = message_data['correlation_id']
            centre_activity_id = message_data['centre_activity_id']
            centre_activity_data = message_data.get('centre_activity_data', {})
            created_by = message_data.get('created_by', 'activity_service')
            
            logger.info(f"Handling activity creation for activity {centre_activity_id}")
            logger.debug(f"Activity data: {centre_activity_data}")
            
            # Convert activity data to scheduler's RefCentreActivity format
            mapped_centre_activity_data = self.map_centre_activity_create(centre_activity_data)
            if not mapped_centre_activity_data:
                logger.error(f"Failed to map centre activity data for activity {centre_activity_id}")
                logger.debug(f"Source data: {centre_activity_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped centre activity data: {mapped_centre_activity_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_centre_activity import RefCentreActivityCreate
            try:
                ref_centre_activity_data = RefCentreActivityCreate(**mapped_centre_activity_data)
            except Exception as e:
                logger.error(f"Failed to create RefCentreActivityCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_centre_activity_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # Create centre activity using CRUD operation with idempotency
            result, was_duplicate = self.create_ref_centre_activity(
                db=db,
                centre_activity=ref_centre_activity_data,
                correlation_id=correlation_id,
                created_by=created_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate creation event for centre activity {centre_activity_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result:
                logger.info(f"Successfully created centre activity {centre_activity_id}")
                return MessageProcessingResult.SUCCESS
            else:
                logger.error(f"Failed to create centre activity {centre_activity_id}")
                return MessageProcessingResult.FAILED_RETRYABLE
            
        except ValueError as e:
            # Business logic error (centre activity already exists)
            logger.warning(f"Business logic error creating centre activity: {str(e)}")
            return MessageProcessingResult.FAILED_PERMANENT
        except Exception as e:
            logger.error(f"Error handling centre activity creation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_centre_activity_updated(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity update events"""
        try:
            correlation_id = message_data['correlation_id']
            centre_activity_id = message_data['centre_activity_id']
            original_centre_activity_data = message_data.get('original_centre_activity_data', {})
            new_centre_activity_data = message_data.get('new_centre_activity_data', {})
            changes = message_data.get('changes', {})
            modified_by = message_data.get('modified_by', 'activity_service')
            
            logger.info(f"Handling centre activity update for centre activity {centre_activity_id}")
            logger.debug(f"Changes: {changes}")
            
            # Convert new activity data to scheduler's RefActivity format
            mapped_update_data = self.map_centre_activity_update(new_centre_activity_data)
            if not mapped_update_data:
                logger.error(f"Failed to map activity update data for activity {centre_activity_id}")
                logger.debug(f"Source update data: {new_centre_activity_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped update data: {mapped_update_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_centre_activity import RefCentreActivityUpdate
            try:
                ref_centre_activity_update = RefCentreActivityUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefActivityUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # Update activity using CRUD operation with idempotency
            result, was_duplicate = self.update_ref_centre_activity(
                db=db,
                centre_activity_id=centre_activity_id,
                centre_activity_update=ref_centre_activity_update,
                correlation_id=correlation_id,
                updated_by=modified_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate update event for activity {centre_activity_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                # Activity doesn't exist in scheduler DB 
                # For UPDATE messages, this might be acceptable depending on business rules
                logger.warning(f"Activity {centre_activity_id} not found for update")
                logger.warning("Activity should be created by CENTRE_ACTIVITY_CREATED message first")
                return MessageProcessingResult.SUCCESS  # Don't requeue
            
            logger.info(f"Successfully updated activity {centre_activity_id}")
            
            # Check if changes affect scheduling
            scheduling_affecting_changes = [
                'active', 'start_date', 'end_date'
            ]
            
            if any(field in changes for field in scheduling_affecting_changes):
                logger.info(f"Activity {centre_activity_id} scheduling-relevant changes detected: {list(changes.keys())}")
                # TODO: Trigger schedule recalculation if needed
                # This could involve:
                # 1. Updating related centre activities
                # 2. Recalculating patient schedules
                # 3. Notifying affected patients/caregivers
            
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling activity update: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_centre_activity_deleted(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity deletion events"""
        try:
            correlation_id = message_data['correlation_id']
            centre_activity_id = message_data['centre_activity_id']
            deleted_by = message_data.get('deleted_by', 'activity_service')
            
            logger.info(f"Handling activity deletion for activity {centre_activity_id}")
            
            # Delete activity using CRUD operation with idempotency
            result, was_duplicate = self.delete_ref_centre_activity(
                db=db,
                centre_activity_id=centre_activity_id,
                correlation_id=correlation_id,
                deleted_by=deleted_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate deletion event for activity {centre_activity_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                logger.warning(f"Activity {centre_activity_id} not found for deletion")
                # This is acceptable - activity might already be deleted
                
            logger.info(f"Successfully processed deletion for activity {centre_activity_id}")
            
            # TODO: Handle cascade effects of activity deletion
            # This might involve:
            # 1. Removing activity from patient schedules
            # 2. Notifying affected patients/caregivers
            # 3. Updating centre activity configurations
            
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling activity deletion: {str(e)}")
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
                "service": "activity_consumer",
                "is_consuming": self.is_consuming,
                "queues": self.activity_queues,
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
            logger.info("Scheduler activity consumer connections closed")
