import logging
import threading
import json
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager

from .rabbitmq_client import RabbitMQClient
from pear_schedule.models.processed_events_model import MessageProcessingResult

logger = logging.getLogger(__name__)

class ActivityExclusionConsumer:
    """
    Consumer for activity exclusion events with separated CRUD operations.
    
    This consumer processes activity exclusion events from the activity.updates exchange
    and updates the scheduler's local REF_ACTIVITY_EXCLUSION table with idempotency guarantees.
    """
    
    def __init__(self):
        self.client = RabbitMQClient("scheduler-activity-exclusion-consumer")
        self.exclusion_queues = [
            "scheduler.activity.centre_activity_exclusion.created",
            "scheduler.activity.centre_activity_exclusion.updated", 
            "scheduler.activity.centre_activity_exclusion.deleted"
        ]
        self.shutdown_event = None
        self.is_consuming = False
        
        # Import dependencies - adjust imports based on your actual structure
        from pear_schedule.crud.ref_activity_exclusion_crud import (
            create_ref_activity_exclusion,
            update_ref_activity_exclusion,
            delete_ref_activity_exclusion,
            is_event_already_processed
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import (
            map_activity_exclusion_create,
            map_activity_exclusion_update
        )
        
        self.create_ref_activity_exclusion = create_ref_activity_exclusion
        self.update_ref_activity_exclusion = update_ref_activity_exclusion
        self.delete_ref_activity_exclusion = delete_ref_activity_exclusion
        self.is_event_already_processed = is_event_already_processed
        self.get_db = get_db
        
        self.map_activity_exclusion_create = map_activity_exclusion_create
        self.map_activity_exclusion_update = map_activity_exclusion_update
    
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
        """Set up consumer to listen to existing activity exclusion queues"""
        try:
            self.client.connect()
            
            # Declare the activity.updates exchange (idempotent)
            self.client.channel.exchange_declare(
                exchange='activity.updates',
                exchange_type='topic',
                durable=True
            )
            
            # Set up consumers for each existing activity exclusion queue
            for queue_name in self.exclusion_queues:
                # Don't declare the queue - it already exists as quorum queue
                # Set up the consumer with proper message handling
                self.client.consume(queue_name, self._handle_message_wrapper)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")
            
            logger.info("Scheduler activity exclusion consumer setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduler activity exclusion consumer: {str(e)}")
            raise
    
    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler activity exclusion consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler activity exclusion consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False
    
    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping activity exclusion consumer...")
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
            result = self._process_activity_exclusion_message(message)
            
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
    
    def _process_activity_exclusion_message(self, message: Dict[str, Any]) -> MessageProcessingResult:
        """
        Process activity exclusion message with FIXED session management and error handling.
        """
        try:
            # Parse and validate message structure
            message_data = self._parse_message(message)
            if not message_data:
                return MessageProcessingResult.FAILED_PERMANENT
            
            correlation_id = message_data['correlation_id']
            event_type = message_data['event_type']
            exclusion_id = message_data['exclusion_id']
            
            logger.info(f"Processing {event_type} for activity exclusion {exclusion_id} (correlation: {correlation_id})")
            
            # Use context manager for guaranteed transaction handling
            with self.get_db_transaction() as db:
                # Quick check for duplicates
                if self.is_event_already_processed(db, correlation_id):
                    logger.info(f"Event already processed: {correlation_id}")
                    return MessageProcessingResult.DUPLICATE
                
                # Route to appropriate handler
                if event_type == 'ACTIVITY_EXCLUSION_CREATED':
                    result = self._handle_activity_exclusion_created(db, message_data)
                elif event_type == 'ACTIVITY_EXCLUSION_UPDATED':
                    result = self._handle_activity_exclusion_updated(db, message_data)
                elif event_type == 'ACTIVITY_EXCLUSION_DELETED':
                    result = self._handle_activity_exclusion_deleted(db, message_data)
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
            logger.error(f"Error processing activity exclusion message: {str(e)}")
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
            required_fields = ['correlation_id', 'event_type', 'exclusion_id']
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
    
    def _handle_activity_exclusion_created(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity exclusion creation events with separation"""
        try:
            correlation_id = message_data['correlation_id']
            exclusion_id = message_data['exclusion_id']
            exclusion_data = message_data.get('exclusion_data', {})
            created_by = message_data.get('created_by', 'activity_service')
            
            logger.info(f"Handling activity exclusion creation for exclusion {exclusion_id}")
            logger.debug(f"Exclusion data: {exclusion_data}")
            
            # Convert exclusion data to scheduler's RefActivityExclusion format
            mapped_exclusion_data = self.map_activity_exclusion_create(exclusion_data)
            if not mapped_exclusion_data:
                logger.error(f"Failed to map activity exclusion data for exclusion {exclusion_id}")
                logger.debug(f"Source data: {exclusion_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped exclusion data: {mapped_exclusion_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_activity_exclusion import RefActivityExclusionCreate
            try:
                # Add debug logging to see mapped data structure
                logger.debug(f"Creating RefActivityExclusionCreate with data: {mapped_exclusion_data}")
                
                ref_exclusion_data = RefActivityExclusionCreate(**mapped_exclusion_data)
                logger.debug(f"Successfully created schema: {ref_exclusion_data}")
            except Exception as e:
                logger.error(f"Failed to create RefActivityExclusionCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_exclusion_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # Create exclusion using CRUD operation with idempotency
            result, was_duplicate = self.create_ref_activity_exclusion(
                db=db,
                exclusion=ref_exclusion_data,
                correlation_id=correlation_id,
                created_by=created_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate creation event for activity exclusion {exclusion_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result:
                logger.info(f"Successfully created activity exclusion {exclusion_id}")
                return MessageProcessingResult.SUCCESS
            else:
                logger.error(f"Failed to create activity exclusion {exclusion_id}")
                return MessageProcessingResult.FAILED_RETRYABLE
            
        except ValueError as e:
            # Business logic error (exclusion already exists)
            logger.warning(f"Business logic error creating activity exclusion: {str(e)}")
            return MessageProcessingResult.FAILED_PERMANENT
        except Exception as e:
            error_msg = str(e)
            # Check for foreign key constraint violations
            if "FOREIGN KEY constraint" in error_msg:
                if "REF_PATIENT" in error_msg:
                    logger.warning(f"Patient {exclusion_id} does not exist in scheduler database - this is expected for sync operations")
                    return MessageProcessingResult.SUCCESS  # Don't requeue - patient should be synced separately
                elif "REF_ACTIVITY" in error_msg:
                    logger.warning(f"Activity does not exist in scheduler database for exclusion {exclusion_id}")
                    return MessageProcessingResult.SUCCESS  # Don't requeue - activity should be synced separately
                else:
                    logger.error(f"Unknown foreign key constraint violation: {error_msg}")
                    return MessageProcessingResult.FAILED_PERMANENT
            
            logger.error(f"Error handling activity exclusion creation: {error_msg}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_activity_exclusion_updated(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity exclusion update events"""
        try:
            correlation_id = message_data['correlation_id']
            exclusion_id = message_data['exclusion_id']
            old_data = message_data.get('old_data', {})
            new_data = message_data.get('new_data', {})
            changes = message_data.get('changes', {})
            modified_by = message_data.get('modified_by', 'activity_service')
            
            logger.info(f"Handling activity exclusion update for exclusion {exclusion_id}")
            logger.debug(f"Changes: {changes}")
            
            # Convert new exclusion data to scheduler's RefActivityExclusion format
            mapped_update_data = self.map_activity_exclusion_update(new_data)
            if not mapped_update_data:
                logger.error(f"Failed to map activity exclusion update data for exclusion {exclusion_id}")
                logger.debug(f"Source update data: {new_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped update data: {mapped_update_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_activity_exclusion import RefActivityExclusionUpdate
            try:
                ref_exclusion_update = RefActivityExclusionUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefActivityExclusionUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # Update exclusion using CRUD operation with idempotency
            result, was_duplicate = self.update_ref_activity_exclusion(
                db=db,
                exclusion_id=exclusion_id,
                exclusion_update=ref_exclusion_update,
                correlation_id=correlation_id,
                updated_by=modified_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate update event for activity exclusion {exclusion_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                # Exclusion doesn't exist in scheduler DB 
                # For UPDATE messages, this might be acceptable depending on business rules
                logger.warning(f"Activity exclusion {exclusion_id} not found for update")
                logger.warning("Exclusion should be created by ACTIVITY_EXCLUSION_CREATED message first")
                return MessageProcessingResult.SUCCESS  # Don't requeue
            
            logger.info(f"Successfully updated activity exclusion {exclusion_id}")
            
            # Check if changes affect scheduling
            scheduling_affecting_changes = [
                'PatientID', 'ActivityID', 'StartDateTime', 'EndDateTime'
            ]
            
            if any(field in changes for field in scheduling_affecting_changes):
                logger.info(f"Activity exclusion {exclusion_id} scheduling-relevant changes detected: {list(changes.keys())}")
                # TODO: Trigger schedule recalculation if needed
                # This could involve:
                # 1. Updating patient schedules based on exclusions
                # 2. Recalculating activity availability
                # 3. Notifying affected patients/caregivers
            
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling activity exclusion update: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_activity_exclusion_deleted(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity exclusion deletion events"""
        try:
            correlation_id = message_data['correlation_id']
            exclusion_id = message_data['exclusion_id']
            deleted_by = message_data.get('deleted_by', 'activity_service')
            
            logger.info(f"Handling activity exclusion deletion for exclusion {exclusion_id}")
            
            # Delete exclusion using CRUD operation with idempotency
            result, was_duplicate = self.delete_ref_activity_exclusion(
                db=db,
                exclusion_id=exclusion_id,
                correlation_id=correlation_id,
                deleted_by=deleted_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate deletion event for activity exclusion {exclusion_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                logger.warning(f"Activity exclusion {exclusion_id} not found for deletion")
                # This is acceptable - exclusion might already be deleted
                
            logger.info(f"Successfully processed deletion for activity exclusion {exclusion_id}")
            
            # TODO: Handle cascade effects of exclusion deletion
            # This might involve:
            # 1. Updating patient schedules to remove exclusion constraints
            # 2. Recalculating activity availability
            # 3. Notifying affected patients/caregivers
            
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling activity exclusion deletion: {str(e)}")
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
                "service": "activity_exclusion_consumer",
                "is_consuming": self.is_consuming,
                "queues": self.exclusion_queues,
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
            logger.info("Scheduler activity exclusion consumer connections closed")
