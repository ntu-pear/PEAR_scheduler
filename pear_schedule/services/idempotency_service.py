from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional, Dict, Any, Callable, TypeVar, Union
import json
import logging
from datetime import datetime, timedelta

from ..models.processed_events_model import ProcessedEvent

logger = logging.getLogger(__name__)

T = TypeVar('T')  # For generic return types


class IdempotencyService:
    """
    Service for handling idempotent operations using the PROCESSED_EVENTS table.
    
    This service integrates with the outbox pattern to ensure that events are
    processed exactly once, even if they are received multiple times.
    
    Industry best practices implemented:
    - Idempotent message processing
    - Event deduplication using correlation IDs
    - Atomic operations with database transactions
    - Comprehensive logging and error handling
    - Cleanup of old processed events
    """
    
    @staticmethod
    def is_already_processed(db: Session, correlation_id: str) -> bool:
        """
        Check if an event with the given correlation_id has already been processed.
        
        Args:
            db: Database session
            correlation_id: The correlation ID from the outbox event
            
        Returns:
            True if the event has already been processed, False otherwise
        """
        try:
            existing = db.query(ProcessedEvent).filter(
                ProcessedEvent.correlation_id == correlation_id
            ).first()
            
            if existing:
                logger.info(f"Event with correlation_id {correlation_id} already processed at {existing.processed_at}")
                logger.debug(f"Existing event details - Type: {existing.event_type}, Aggregate: {existing.aggregate_id}")
                return True
                
            logger.debug(f"Event with correlation_id {correlation_id} not previously processed")
            return False
            
        except Exception as e:
            logger.error(f"Error checking if event {correlation_id} was already processed: {e}")
            # In case of error, assume not processed to allow retry
            return False
    
    @staticmethod
    def mark_as_processed(
        db: Session,
        correlation_id: str,
        event_type: str,
        aggregate_id: str,
        processed_by: str,
        operation_result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> ProcessedEvent:
        """
        Mark an event as processed by creating a record in PROCESSED_EVENTS.
        
        Args:
            db: Database session (should be same transaction as business logic)
            correlation_id: The correlation ID from the outbox event
            event_type: Type of event (e.g., 'PATIENT_CREATED')
            aggregate_id: The entity ID that was processed
            processed_by: Service/user that processed the event
            operation_result: Optional result data for debugging
            error_message: Optional error message if processing had issues
            
        Returns:
            The created ProcessedEvent record
            
        Raises:
            IntegrityError: If correlation_id already exists (race condition)
        """
        try:
            logger.debug(f"Marking event {correlation_id} as processed")
            logger.debug(f"Event details - Type: {event_type}, Aggregate: {aggregate_id}, Processed by: {processed_by}")
            
            # Convert operation_result to JSON string if provided
            result_json = None
            if operation_result:
                try:
                    result_json = json.dumps(operation_result, default=str)
                except Exception as json_error:
                    logger.warning(f"Failed to serialize operation_result to JSON: {json_error}")
                    result_json = str(operation_result)
            
            processed_event = ProcessedEvent.create_from_correlation_id(
                correlation_id=correlation_id,
                event_type=event_type,
                aggregate_id=aggregate_id,
                processed_by=processed_by,
                operation_result=result_json,
                error_message=error_message
            )
            
            db.add(processed_event)
            
            # Force flush to detect constraint violations early
            try:
                db.flush()
                logger.debug(f"Flushed processed event record for {correlation_id}")
                
                # Verify the record was actually inserted
                verification = db.query(ProcessedEvent).filter(
                    ProcessedEvent.correlation_id == correlation_id
                ).first()
                if not verification:
                    logger.error(f"CRITICAL: Processed event record not found after flush for {correlation_id}")
                    
            except IntegrityError as integrity_error:
                logger.warning(f"Integrity constraint violation for {correlation_id} - likely a race condition")
                raise integrity_error
            except Exception as flush_error:
                logger.error(f"Unexpected error during flush for {correlation_id}: {flush_error}")
                raise
            
            logger.debug(f"Successfully marked event {correlation_id} as processed in PROCESSED_EVENTS table")
            return processed_event
            
        except IntegrityError as e:
            # This can happen in race conditions - another instance processed it first
            logger.warning(f"Race condition detected: correlation_id {correlation_id} already processed by another instance")
            logger.debug(f"IntegrityError details: {str(e)}")
            db.rollback()
            raise
        except Exception as e:
            logger.error(f"Unexpected error marking event {correlation_id} as processed: {e}")
            raise
    
    @staticmethod
    def process_idempotent(
        db: Session,
        correlation_id: str,
        event_type: str,
        aggregate_id: str,
        processed_by: str,
        operation: Callable[[], T]
    ) -> tuple[T, bool]:
        """
        Execute an operation idempotently using the correlation_id.
        
        This is the main method that should be used for idempotent processing.
        It checks if the event was already processed, and if not, executes the
        operation and marks it as processed.
        
        Args:
            db: Database session
            correlation_id: The correlation ID from the outbox event
            event_type: Type of event (e.g., 'PATIENT_CREATED')
            aggregate_id: The entity ID being processed
            processed_by: Service/user processing the event
            operation: A callable that performs the business logic
            
        Returns:
            Tuple of (operation_result, was_already_processed)
            - operation_result: The result of the operation (or None if already processed)
            - was_already_processed: True if event was already processed
            
        Example:
            ```python
            def create_patient_operation():
                return create_or_update_ref_patient(db, patient_data, user)
            
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="PATIENT_CREATED",
                aggregate_id=patient_id,
                processed_by="scheduler_service",
                operation=create_patient_operation
            )
            ```
        """
        logger.debug(f"Starting idempotent processing for correlation_id: {correlation_id}")
        logger.debug(f"Event type: {event_type}, Aggregate: {aggregate_id}")
        
        # Check if already processed
        if IdempotencyService.is_already_processed(db, correlation_id):
            logger.info(f"Skipping duplicate event {correlation_id} - already processed")
            return None, True
        
        try:
            # Execute the business operation
            logger.debug(f"Starting business operation for event {correlation_id}")
            operation_start_time = datetime.now()
            
            result = operation()
            
            operation_end_time = datetime.now()
            processing_duration = (operation_end_time - operation_start_time).total_seconds()
            
            logger.debug(f"Business operation completed for {correlation_id} in {processing_duration:.3f}s")
            
            # Mark as processed (this should be in the same transaction)
            operation_metadata = {
                "status": "success", 
                "processing_duration_seconds": processing_duration,
                "timestamp": operation_end_time.isoformat(),
                "has_result": result is not None
            }
            
            logger.debug(f"About to mark event {correlation_id} as processed")
            
            IdempotencyService.mark_as_processed(
                db=db,
                correlation_id=correlation_id,
                event_type=event_type,
                aggregate_id=aggregate_id,
                processed_by=processed_by,
                operation_result=operation_metadata
            )
            
            logger.info(f"Successfully processed event {correlation_id}")
            return result, False
            
        except IntegrityError as integrity_error:
            # Race condition - another instance processed this event
            logger.warning(f"Race condition during processing of {correlation_id}: {integrity_error}")
            # Return as if it was already processed
            return None, True
            
        except Exception as e:
            # Log the error but don't mark as processed - allow retry
            logger.error(f"Error during idempotent processing of event {correlation_id}: {str(e)}")
            logger.debug(f"Failed event details - Type: {event_type}, Aggregate: {aggregate_id}")
            
            # Optionally mark as processed with error for permanent failures
            # This depends on your error handling strategy
            if isinstance(e, ValueError):
                # Business logic errors - might want to mark as processed to avoid infinite retries
                logger.warning(f"Business logic error for {correlation_id}, marking as processed with error")
                try:
                    IdempotencyService.mark_as_processed(
                        db=db,
                        correlation_id=correlation_id,
                        event_type=event_type,
                        aggregate_id=aggregate_id,
                        processed_by=processed_by,
                        error_message=str(e)
                    )
                    db.commit()
                except Exception as mark_error:
                    logger.error(f"Failed to mark errored event as processed: {mark_error}")
            
            raise
    
    @staticmethod
    def record_processed_event(
        db: Session,
        correlation_id: str,
        event_type: str,
        aggregate_id: str,
        processed_by: str
    ) -> ProcessedEvent:
        """
        Record a processed event without checking for duplicates.
        Used for sync events where we want to track but not prevent processing.
        
        Args:
            db: Database session
            correlation_id: The correlation ID from the event
            event_type: Type of event (e.g., 'ACTIVITY_UPDATED')
            aggregate_id: The entity ID that was processed
            processed_by: Service/user that processed the event
            
        Returns:
            The created ProcessedEvent record
        """
        try:
            logger.debug(f"Recording processed event {correlation_id} (no duplicate check)")
            
            processed_event = ProcessedEvent.create_from_correlation_id(
                correlation_id=correlation_id,
                event_type=event_type,
                aggregate_id=aggregate_id,
                processed_by=processed_by,
                operation_result=json.dumps({"status": "recorded", "sync_event": True}, default=str),
                error_message=None
            )
            
            db.add(processed_event)
            db.flush()
            
            logger.debug(f"Recorded event {correlation_id} without duplicate check")
            return processed_event
            
        except Exception as e:
            # Non-critical failure - just log it
            logger.warning(f"Failed to record event {correlation_id}: {str(e)}")
            raise
    
    @staticmethod
    def cleanup_old_events(db: Session, older_than_days: int = 30) -> int:
        """
        Clean up old processed events to prevent table growth.
        
        Args:
            db: Database session
            older_than_days: Delete events older than this many days
            
        Returns:
            Number of deleted events
        """
        cutoff_date = datetime.now() - timedelta(days=older_than_days)
        
        logger.info(f"Starting cleanup of processed events older than {older_than_days} days (before {cutoff_date})")
        
        try:
            deleted_count = db.query(ProcessedEvent).filter(
                ProcessedEvent.processed_at < cutoff_date
            ).delete()
            
            db.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} processed events older than {older_than_days} days")
            else:
                logger.debug(f"No processed events older than {older_than_days} days to clean up")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error during processed events cleanup: {e}")
            db.rollback()
            raise
    
    @staticmethod
    def get_processing_stats(db: Session) -> Dict[str, Any]:
        """
        Get statistics about processed events for monitoring.
        
        Args:
            db: Database session
            
        Returns:
            Dictionary with processing statistics
        """
        try:
            from sqlalchemy import func, desc
            
            # Total processed events
            total_events = db.query(ProcessedEvent).count()
            
            # Events by type
            events_by_type = db.query(
                ProcessedEvent.event_type,
                func.count(ProcessedEvent.correlation_id).label('count')
            ).group_by(ProcessedEvent.event_type).all()
            
            # Recent events (last 24 hours)
            yesterday = datetime.now() - timedelta(hours=24)
            recent_events = db.query(ProcessedEvent).filter(
                ProcessedEvent.processed_at >= yesterday
            ).count()
            
            # Events with errors
            error_events = db.query(ProcessedEvent).filter(
                ProcessedEvent.error_message.isnot(None)
            ).count()
            
            # Most recent events
            latest_events = db.query(ProcessedEvent).order_by(
                ProcessedEvent.processed_at.desc()
            ).limit(5).all()
            
            latest_events_info = [
                {
                    "correlation_id": event.correlation_id[:8] + "...",  # Truncate for privacy
                    "event_type": event.event_type,
                    "aggregate_id": event.aggregate_id,
                    "processed_at": event.processed_at.isoformat(),
                    "has_error": event.error_message is not None
                }
                for event in latest_events
            ]
            
            stats = {
                "total_processed_events": total_events,
                "events_last_24h": recent_events,
                "events_with_errors": error_events,
                "events_by_type": [{"event_type": et, "count": count} for et, count in events_by_type],
                "latest_events": latest_events_info,
                "stats_generated_at": datetime.now().isoformat()
            }
            
            logger.debug(f"Generated processing stats: {total_events} total events, {recent_events} in last 24h")
            return stats
            
        except Exception as e:
            logger.error(f"Error generating processing stats: {e}")
            return {
                "error": str(e),
                "stats_generated_at": datetime.now().isoformat()
            }
