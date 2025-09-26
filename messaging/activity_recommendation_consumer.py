import logging
import threading
import json
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager

from .rabbitmq_client import RabbitMQClient
from pear_schedule.models.processed_events_model import MessageProcessingResult

logger = logging.getLogger(__name__)

class ActivityRecommendationConsumer:
    """
    Consumer for activity recommendation events with separated CRUD operations.
    
    This consumer processes activity recommendation events from the activity.recommendations exchange
    and updates the scheduler's local REF_ACTIVITY_RECOMMENDATION table with idempotency guarantees.
    """
    
    def __init__(self):
        self.client = RabbitMQClient("scheduler-activity-recommendation-consumer")
        self.recommendation_queues = [
            "scheduler.activity.recommendation.created",
            "scheduler.activity.recommendation.updated", 
            "scheduler.activity.recommendation.deleted"
        ]
        self.shutdown_event = None
        self.is_consuming = False
        
        # Import dependencies - adjust imports based on your actual structure
        from pear_schedule.crud.ref_activity_recommendation_crud import (
            create_ref_activity_recommendation,
            update_ref_activity_recommendation,
            delete_ref_activity_recommendation,
            is_event_already_processed
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import (
            map_activity_recommendation_create,
            map_activity_recommendation_update
        )
        
        self.create_ref_activity_recommendation = create_ref_activity_recommendation
        self.update_ref_activity_recommendation = update_ref_activity_recommendation
        self.delete_ref_activity_recommendation = delete_ref_activity_recommendation
        self.is_event_already_processed = is_event_already_processed
        self.get_db = get_db
        
        self.map_activity_recommendation_create = map_activity_recommendation_create
        self.map_activity_recommendation_update = map_activity_recommendation_update
    
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
        """Set up consumer to listen to existing activity recommendation queues"""
        try:
            self.client.connect()
            
            # Declare the activity.recommendations exchange (idempotent)
            self.client.channel.exchange_declare(
                exchange='activity.updates',
                exchange_type='topic',
                durable=True
            )
            
            # Set up consumers for each existing activity recommendation queue
            for queue_name in self.recommendation_queues:
                # Don't declare the queue - it already exists as quorum queue
                # Set up the consumer with proper message handling
                self.client.consume(queue_name, self._handle_message_wrapper)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")
            
            logger.info("Scheduler activity recommendation consumer setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduler activity recommendation consumer: {str(e)}")
            raise
    
    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler activity recommendation consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler activity recommendation consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False
    
    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping activity recommendation consumer...")
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
            result = self._process_activity_recommendation_message(message)
            
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
    
    def _process_activity_recommendation_message(self, message: Dict[str, Any]) -> MessageProcessingResult:
        """
        Process activity recommendation message with FIXED session management and error handling.
        """
        try:
            # Parse and validate message structure
            message_data = self._parse_message(message)
            if not message_data:
                return MessageProcessingResult.FAILED_PERMANENT
            
            correlation_id = message_data['correlation_id']
            event_type = message_data['event_type']
            recommendation_id = message_data['recommendation_id']
            
            logger.info(f"Processing {event_type} for activity recommendation {recommendation_id} (correlation: {correlation_id})")
            
            # Use context manager for guaranteed transaction handling
            with self.get_db_transaction() as db:
                # Quick check for duplicates
                if self.is_event_already_processed(db, correlation_id):
                    logger.info(f"Event already processed: {correlation_id}")
                    return MessageProcessingResult.DUPLICATE
                
                # Route to appropriate handler
                if event_type == 'ACTIVITY_RECOMMENDATION_CREATED':
                    result = self._handle_activity_recommendation_created(db, message_data)
                elif event_type == 'ACTIVITY_RECOMMENDATION_UPDATED':
                    result = self._handle_activity_recommendation_updated(db, message_data)
                elif event_type == 'ACTIVITY_RECOMMENDATION_DELETED':
                    result = self._handle_activity_recommendation_deleted(db, message_data)
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
            logger.error(f"Error processing activity recommendation message: {str(e)}")
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
            required_fields = ['correlation_id', 'event_type', 'recommendation_id']
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
    
    def _handle_activity_recommendation_created(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity recommendation creation events with separation"""
        try:
            correlation_id = message_data['correlation_id']
            recommendation_id = message_data['recommendation_id']
            recommendation_data = message_data.get('recommendation_data', {})
            created_by = message_data.get('created_by', 'activity_service')
            
            logger.info(f"Handling activity recommendation creation for recommendation {recommendation_id}")
            logger.debug(f"Recommendation data: {recommendation_data}")
            
            # Convert recommendation data to scheduler's RefActivityRecommendation format
            mapped_recommendation_data = self.map_activity_recommendation_create(recommendation_data)
            if not mapped_recommendation_data:
                logger.error(f"Failed to map activity recommendation data for recommendation {recommendation_id}")
                logger.debug(f"Source data: {recommendation_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped recommendation data: {mapped_recommendation_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_activity_recommendation import RefActivityRecommendationCreate
            try:
                ref_recommendation_data = RefActivityRecommendationCreate(**mapped_recommendation_data)
            except Exception as e:
                logger.error(f"Failed to create RefActivityRecommendationCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_recommendation_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # Create recommendation using CRUD operation with idempotency
            result, was_duplicate = self.create_ref_activity_recommendation(
                db=db,
                recommendation=ref_recommendation_data,
                correlation_id=correlation_id,
                created_by=created_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate creation event for activity recommendation {recommendation_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result:
                logger.info(f"Successfully created activity recommendation {recommendation_id}")
                return MessageProcessingResult.SUCCESS
            else:
                logger.error(f"Failed to create activity recommendation {recommendation_id}")
                return MessageProcessingResult.FAILED_RETRYABLE
            
        except ValueError as e:
            # Business logic error (recommendation already exists)
            logger.warning(f"Business logic error creating activity recommendation: {str(e)}")
            return MessageProcessingResult.FAILED_PERMANENT
        except Exception as e:
            logger.error(f"Error handling activity recommendation creation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_activity_recommendation_updated(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity recommendation update events"""
        try:
            correlation_id = message_data['correlation_id']
            recommendation_id = message_data['recommendation_id']
            old_data = message_data.get('old_data', {})
            new_data = message_data.get('new_data', {})
            changes = message_data.get('changes', {})
            modified_by = message_data.get('modified_by', 'activity_service')
            
            logger.info(f"Handling activity recommendation update for recommendation {recommendation_id}")
            logger.debug(f"Changes: {changes}")
            
            # Convert new recommendation data to scheduler's RefActivityRecommendation format
            mapped_update_data = self.map_activity_recommendation_update(new_data)
            if not mapped_update_data:
                logger.error(f"Failed to map activity recommendation update data for recommendation {recommendation_id}")
                logger.debug(f"Source update data: {new_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped update data: {mapped_update_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_activity_recommendation import RefActivityRecommendationUpdate
            try:
                ref_recommendation_update = RefActivityRecommendationUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefActivityRecommendationUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # Update recommendation using CRUD operation with idempotency
            result, was_duplicate = self.update_ref_activity_recommendation(
                db=db,
                recommendation_id=recommendation_id,
                recommendation_update=ref_recommendation_update,
                correlation_id=correlation_id,
                updated_by=modified_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate update event for activity recommendation {recommendation_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                # Recommendation doesn't exist in scheduler DB 
                # For UPDATE messages, this might be acceptable depending on business rules
                logger.warning(f"Activity recommendation {recommendation_id} not found for update")
                logger.warning("Recommendation should be created by ACTIVITY_RECOMMENDATION_CREATED message first")
                return MessageProcessingResult.SUCCESS  # Don't requeue
            
            logger.info(f"Successfully updated activity recommendation {recommendation_id}")
            
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling activity recommendation update: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_activity_recommendation_deleted(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle activity recommendation deletion events"""
        try:
            correlation_id = message_data['correlation_id']
            recommendation_id = message_data['recommendation_id']
            deleted_by = message_data.get('deleted_by', 'activity_service')
            
            logger.info(f"Handling activity recommendation deletion for recommendation {recommendation_id}")
            
            # Delete recommendation using CRUD operation with idempotency
            result, was_duplicate = self.delete_ref_activity_recommendation(
                db=db,
                recommendation_id=recommendation_id,
                correlation_id=correlation_id,
                deleted_by=deleted_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate deletion event for activity recommendation {recommendation_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                logger.warning(f"Activity recommendation {recommendation_id} not found for deletion")
                # This is acceptable - recommendation might already be deleted
                
            logger.info(f"Successfully processed deletion for activity recommendation {recommendation_id}")
            
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling activity recommendation deletion: {str(e)}")
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
                "service": "activity_recommendation_consumer",
                "is_consuming": self.is_consuming,
                "queues": self.recommendation_queues,
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
            logger.info("Scheduler activity recommendation consumer connections closed")
