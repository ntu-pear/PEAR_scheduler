import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from pear_schedule.models.processed_events_model import MessageProcessingResult

from .rabbitmq_client import RabbitMQClient

logger = logging.getLogger(__name__)

class PatientMedicationConsumer:
    """
    Consumer for patient medication events with separated CRUD operations.
    
    This consumer processes patient medication events from the patient.medication.updates exchange
    and updates the scheduler's local REF_PATIENT_MEDICATION table with idempotency guarantees.
    """
    
    def __init__(self):
        self.client = RabbitMQClient("scheduler-patient-medication-consumer")
        self.medication_queues = [
            "scheduler.patient.medication.created",
            "scheduler.patient.medication.updated", 
            "scheduler.patient.medication.deleted"
        ]
        self.shutdown_event = None
        self.is_consuming = False
        
        from messaging.mappers.mapper_util import (
            map_patient_medication_create,
            map_patient_medication_update,
        )
        from pear_schedule.crud.ref_patient_medication_crud import (
            create_ref_patient_medication,
            delete_ref_patient_medication,
            is_event_already_processed,
            update_ref_patient_medication,
        )
        from pear_schedule.database import get_db
        
        self.create_ref_patient_medication = create_ref_patient_medication
        self.update_ref_patient_medication = update_ref_patient_medication
        self.delete_ref_patient_medication = delete_ref_patient_medication
        self.is_event_already_processed = is_event_already_processed
        self.get_db = get_db
        
        self.map_patient_medication_create = map_patient_medication_create
        self.map_patient_medication_update = map_patient_medication_update
    
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
        """Set up consumer to listen to existing patient medication queues"""
        try:
            self.client.connect()
            
            self.client.channel.exchange_declare(
                exchange='patient.updates',
                exchange_type='topic',
                durable=True
            )
            
            for queue_name in self.medication_queues:
                self.client.consume(queue_name, self._handle_message_wrapper)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")
            
            logger.info("Scheduler patient medication consumer setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduler patient medication consumer: {str(e)}")
            raise
    
    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler patient medication consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler patient medication consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False
    
    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping patient medication consumer...")
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
            
            result = self._process_patient_medication_message(message)
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
    
    def _process_patient_medication_message(self, message: Dict[str, Any]) -> MessageProcessingResult:
        """Process patient medication message with sync event support."""
        try:
            message_data = self._parse_message(message)
            if not message_data:
                return MessageProcessingResult.FAILED_PERMANENT
            
            correlation_id = message_data['correlation_id']
            event_type = message_data['event_type']
            medication_id = message_data['medication_id']
            is_sync_event = message_data.get('is_sync_event', False)
            sync_reason = message_data.get('sync_reason')
            
            logger.info(f"Processing {event_type} for patient medication {medication_id} (correlation: {correlation_id}, sync: {is_sync_event}, reason: {sync_reason})")
            
            with self.get_db_transaction() as db:
                # For sync events, bypass duplicate check in CRUD
                if not is_sync_event and self.is_event_already_processed(db, correlation_id):
                    logger.info(f"Event already processed: {correlation_id}")
                    return MessageProcessingResult.DUPLICATE
                elif is_sync_event:
                    logger.info(f"Sync event detected - bypassing idempotency check for {correlation_id}")
                
                if event_type == 'PATIENT_MEDICATION_CREATED':
                    result = self._handle_patient_medication_created(db, message_data)
                elif event_type == 'PATIENT_MEDICATION_UPDATED':
                    result = self._handle_patient_medication_updated(db, message_data)
                elif event_type == 'PATIENT_MEDICATION_DELETED':
                    result = self._handle_patient_medication_deleted(db, message_data)
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
            logger.error(f"Error processing patient medication message: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _parse_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse and validate message structure."""
        try:
            message_data = message.get('data', {})
            
            required_fields = ['correlation_id', 'event_type', 'medication_id']
            for field in required_fields:
                if field not in message_data:
                    logger.error(f"Missing required field '{field}' in message")
                    return None
            
            logger.debug(f"Parsed message: {message_data}")
            return message_data
            
        except Exception as e:
            logger.error(f"Failed to parse message: {str(e)}")
            return None
    
    def _handle_patient_medication_created(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle patient medication creation events"""
        try:
            correlation_id = message_data['correlation_id']
            medication_id = message_data['medication_id']
            medication_data = message_data.get('medication_data', {})
            patient_id = message_data.get('patient_id')
            created_by = message_data.get('created_by', 'patient_service')
            
            logger.info(f"Handling patient medication creation for medication {medication_id} (patient: {patient_id})")
            logger.debug(f"Medication data: {medication_data}")
            
            mapped_medication_data = self.map_patient_medication_create(medication_data)
            if not mapped_medication_data:
                logger.error(f"Failed to map medication data for medication {medication_id}")
                logger.debug(f"Source data: {medication_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped medication data: {mapped_medication_data}")
            
            from pear_schedule.schemas.ref_patient_medication import (
                RefPatientMedicationCreate,
            )
            try:
                ref_medication_data = RefPatientMedicationCreate(**mapped_medication_data)
            except Exception as e:
                logger.error(f"Failed to create RefPatientMedicationCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_medication_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            result, was_duplicate = self.create_ref_patient_medication(
                db=db,
                medication=ref_medication_data,
                correlation_id=correlation_id,
                created_by=created_by
            )
            
            if was_duplicate:
                logger.info(f"Duplicate creation event for medication {medication_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result:
                logger.info(f"Successfully created patient medication {medication_id}")
                return MessageProcessingResult.SUCCESS
            else:
                logger.error(f"Failed to create patient medication {medication_id}")
                return MessageProcessingResult.FAILED_RETRYABLE
            
        except ValueError as e:
            logger.warning(f"Business logic error creating medication: {str(e)}")
            return MessageProcessingResult.FAILED_PERMANENT
        except Exception as e:
            logger.error(f"Error handling patient medication creation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_patient_medication_updated(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle patient medication update events"""
        try:
            correlation_id = message_data['correlation_id']
            medication_id = message_data['medication_id']
            medication_data = message_data.get('new_data', {}) # use new_data based on new payload standardisation
            patient_id = message_data.get('patient_id')
            modified_by = message_data.get('modified_by', 'patient_service')
            is_sync_event = message_data.get('is_sync_event', False)
            
            logger.info(f"Handling patient medication update for medication {medication_id} (patient: {patient_id})")
            
            mapped_update_data = self.map_patient_medication_update(medication_data)
            if not mapped_update_data:
                logger.error(f"Failed to map medication update data for medication {medication_id}")
                logger.debug(f"Source update data: {medication_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            logger.debug(f"Mapped update data: {mapped_update_data}")
            
            from pear_schedule.schemas.ref_patient_medication import (
                RefPatientMedicationUpdate,
            )
            try:
                ref_medication_update = RefPatientMedicationUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefPatientMedicationUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # For sync events, bypass duplicate check in CRUD
            result, was_duplicate = self.update_ref_patient_medication(
                db=db,
                medication_id=medication_id,
                medication_update=ref_medication_update,
                correlation_id=correlation_id,
                skip_duplicate_check=is_sync_event
            )
            
            if was_duplicate and not is_sync_event:
                logger.info(f"Duplicate update event for medication {medication_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                if is_sync_event:
                    # For sync events, try to create if doesn't exist
                    logger.warning(f"Medication {medication_id} not found during sync - attempting to create")
                    try:
                        from pear_schedule.schemas.ref_patient_medication import (
                            RefPatientMedicationCreate,
                        )
                        mapped_medication_data = self.map_patient_medication_create(medication_data)
                        if mapped_medication_data:
                            ref_medication_data = RefPatientMedicationCreate(**mapped_medication_data)
                            create_result, _ = self.create_ref_patient_medication(
                                db=db,
                                medication=ref_medication_data,
                                correlation_id=correlation_id,
                                created_by=modified_by
                            )
                            if create_result:
                                logger.info(f"Successfully created medication {medication_id} during sync")
                                return MessageProcessingResult.SUCCESS
                    except Exception as e:
                        logger.error(f"Failed to create medication during sync: {str(e)}")
                        return MessageProcessingResult.FAILED_RETRYABLE
                else:
                    logger.warning(f"Patient medication {medication_id} not found for update")
                return MessageProcessingResult.SUCCESS
            
            logger.info(f"Successfully updated patient medication {medication_id}")
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling patient medication update: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def _handle_patient_medication_deleted(self, db, message_data: Dict[str, Any]) -> MessageProcessingResult:
        """Handle patient medication deletion events"""
        try:
            correlation_id = message_data['correlation_id']
            medication_id = message_data['medication_id']
            patient_id = message_data.get('patient_id')
            updated_datetime = message_data.get('timestamp')
            deleted_by = message_data.get('deleted_by', 'patient_service')
            is_sync_event = message_data.get('is_sync_event', False)
            
            logger.info(f"Handling patient medication deletion for medication {medication_id} (patient: {patient_id})")
               
            from pear_schedule.schemas.ref_patient_medication import (
                RefPatientMedicationDelete,
            )
            
            try:
                # Force update timestamp for sync events
                if is_sync_event:
                    updated_datetime = datetime.now()
                    logger.debug(f"Sync event - forcing timestamp update to {updated_datetime}")
                
                ref_medication_delete = RefPatientMedicationDelete(
                    UpdatedDateTime=updated_datetime if updated_datetime else datetime.now(),
                    ModifiedById=deleted_by
                )
                
            except Exception as e:
                logger.error(f"Pydantic validation failed: {str(e)}")
                logger.error(f"Raw data - UpdatedDateTime: {updated_datetime}, ModifiedById: {deleted_by}")
                return MessageProcessingResult.FAILED_PERMANENT
            
            # For sync events, bypass duplicate check in CRUD
            result, was_duplicate = self.delete_ref_patient_medication(
                db=db,
                medication_id=medication_id,
                medication_delete=ref_medication_delete,
                correlation_id=correlation_id,
                skip_duplicate_check=is_sync_event
            )
            
            if was_duplicate and not is_sync_event:
                logger.info(f"Duplicate deletion event for medication {medication_id}")
                return MessageProcessingResult.DUPLICATE
            
            if result is None:
                logger.warning(f"Patient medication {medication_id} not found for deletion")
                
            logger.info(f"Successfully processed deletion for patient medication {medication_id}")
            return MessageProcessingResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Error handling patient medication deletion: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return MessageProcessingResult.FAILED_RETRYABLE
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for monitoring."""
        try:
            return {
                "status": "healthy",
                "service": "patient_medication_consumer",
                "is_consuming": self.is_consuming,
                "queues": self.medication_queues,
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
            logger.info("Scheduler patient medication consumer connections closed")
