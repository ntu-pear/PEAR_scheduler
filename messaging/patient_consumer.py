import logging
import threading
from typing import Dict, Any
from datetime import datetime

from .rabbitmq_client import RabbitMQClient

logger = logging.getLogger(__name__)

class PatientConsumer:
    """
    Consumer for patient events from patient.updates exchange
    Updates the scheduler's local REF_PATIENT table
    """
    
    def __init__(self):
        self.client = RabbitMQClient("scheduler-patient-consumer")
        self.patient_queues = [
            "scheduler.patient.created",
            "scheduler.patient.updated",
            "scheduler.patient.deleted"
        ]
        self.shutdown_event = None
        self.is_consuming = False
        
        # Import here to avoid circular imports
        from pear_schedule.crud.ref_patient_crud import (
            create_or_update_ref_patient,
            update_ref_patient_idempotent,
            soft_delete_ref_patient_idempotent
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import (
            map_patient_create,
            map_patient_update
        )
        
        self.create_or_update_ref_patient = create_or_update_ref_patient
        self.update_ref_patient_idempotent = update_ref_patient_idempotent
        self.soft_delete_ref_patient_idempotent = soft_delete_ref_patient_idempotent
        self.get_db = get_db
        
        self.map_patient_create = map_patient_create
        self.map_patient_update = map_patient_update
    
    def set_shutdown_event(self, shutdown_event: threading.Event):
        """Set the shutdown event for graceful shutdown"""
        self.shutdown_event = shutdown_event
        if self.client:
            self.client.set_shutdown_event(shutdown_event)
    
    def setup_consumer(self):
        """Set up consumer to listen to existing patient queues"""
        try:
            self.client.connect()
            
            # Declare the patient.updates exchange (idempotent)
            self.client.channel.exchange_declare(
                exchange='patient.updates',
                exchange_type='topic',
                durable=True
            )
            
            # Set up consumers for each existing patient queue
            for queue_name in self.patient_queues:
                # Don't declare the queue - it already exists as quorum queue
                # Just set up the consumer
                self.client.consume(queue_name, self.handle_patient_message)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")
            
            logger.info("Scheduler patient consumer setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduler patient consumer: {str(e)}")
            raise
    
    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler patient consumer...")
            self.is_consuming = True
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler patient consumer: {str(e)}")
            raise
        finally:
            self.is_consuming = False
    
    def stop(self):
        """Stop the consumer gracefully"""
        logger.info("Stopping patient consumer...")
        self.is_consuming = False
        if self.client:
            self.client.stop_consuming()
    
    def handle_patient_message(self, message: Dict[str, Any]) -> bool:
        """
        Handle incoming patient messages from patient.updates exchange
        Returns True if message was processed successfully
        """
        try:
            # Check if we should shutdown
            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("Shutdown signal received, stopping message processing")
                return False
            
            # Log the full message for debugging
            logger.info(f"Received message: {message}")
            
            # Extract message data
            message_data = message.get('data', {})
            event_type = message_data.get('event_type')
            patient_id = message_data.get('patient_id')
            
            logger.info(f"Processing {event_type} for patient {patient_id}")
            
            # Get database session
            db = next(self.get_db())
            
            try:
                if event_type == 'PATIENT_CREATED':
                    return self._handle_patient_created(db, message_data)
                    
                elif event_type == 'PATIENT_UPDATED':
                    return self._handle_patient_updated(db, message_data)
                    
                elif event_type == 'PATIENT_DELETED':
                    return self._handle_patient_deleted(db, message_data)
                    
                else:
                    logger.warning(f"Unknown event type: {event_type}")
                    return True  # Don't requeue unknown events
                    
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error processing patient message: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False  # Requeue message
    
    def _handle_patient_created(self, db, message_data: Dict[str, Any]) -> bool:
        """Handle patient creation events"""
        try:
            patient_id = message_data.get('patient_id')
            patient_data = message_data.get('patient_data', {})
            created_by = message_data.get('created_by', 'patient_service')
            
            logger.info(f"Handling patient creation for patient {patient_id}")
            logger.debug(f"Patient data: {patient_data}")
            
            # Convert patient data to scheduler's RefPatient format using simplified mapper
            mapped_patient_data = self.map_patient_create(patient_data)
            
            if not mapped_patient_data:
                logger.error(f"Failed to map patient data for patient {patient_id}")
                logger.debug(f"Source data: {patient_data}")
                return False
            
            logger.debug(f"Mapped patient data: {mapped_patient_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_patient import RefPatientCreate
            try:
                ref_patient_data = RefPatientCreate(**mapped_patient_data)
            except Exception as e:
                logger.error(f"Failed to create RefPatientCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_patient_data}")
                return False
            
            # Create or update patient in local database using idempotent operation
            ref_patient = self.create_or_update_ref_patient(
                db=db,
                patient=ref_patient_data,
                user=created_by
            )
            
            if ref_patient:
                logger.info(f"Successfully synchronized patient {patient_id} creation")
                return True
            else:
                logger.error(f"Failed to create/update ref_patient for patient {patient_id}")
                return False
            
        except Exception as e:
            logger.error(f"Error handling patient creation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def _handle_patient_updated(self, db, message_data: Dict[str, Any]) -> bool:
        """Handle patient update events"""
        try:
            patient_id = message_data.get('patient_id')
            old_data = message_data.get('old_data', {})
            new_data = message_data.get('new_data', {})
            changes = message_data.get('changes', {})
            modified_by = message_data.get('modified_by', 'patient_service')
            
            logger.info(f"Handling patient update for patient {patient_id}")
            logger.debug(f"Changes: {changes}")
            
            # Convert new patient data to scheduler's RefPatient format using simplified mapper
            mapped_update_data = self.map_patient_update(new_data)
            
            if not mapped_update_data:
                logger.error(f"Failed to map patient update data for patient {patient_id}")
                logger.debug(f"Source update data: {new_data}")
                return False
            
            logger.debug(f"Mapped update data: {mapped_update_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_patient import RefPatientUpdate
            try:
                ref_patient_update = RefPatientUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefPatientUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return False
            
            # Update patient in local database using idempotent operation
            ref_patient = self.update_ref_patient_idempotent(
                db=db,
                patient_id=patient_id,
                patient=ref_patient_update,
                user=modified_by
            )
            
            if ref_patient:
                logger.info(f"Successfully synchronized patient {patient_id} update")
                
                # Check if changes affect scheduling
                scheduling_affecting_changes = [
                    'IsActive', 'StartDate', 'EndDate', 'UpdateBit'
                ]
                
                if any(field in changes for field in scheduling_affecting_changes):
                    logger.info(f"Patient {patient_id} scheduling-relevant changes detected: {list(changes.keys())}")
                
                return True
            else:
                # Patient doesn't exist in scheduler DB 
                # For UPDATE messages, this is unexpected - patient should exist
                # Log this and return success to avoid reprocessing
                logger.warning(f"Patient {patient_id} not found for update - skipping message")
                logger.warning("Patient should be created by PATIENT_CREATED message first")
                return True  # Return True to acknowledge message and avoid requeue
            
        except Exception as e:
            logger.error(f"Error handling patient update: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def _handle_patient_deleted(self, db, message_data: Dict[str, Any]) -> bool:
        """Handle patient deletion events"""
        try:
            patient_id = message_data.get('patient_id')
            deleted_by = message_data.get('deleted_by', 'patient_service')
            
            logger.info(f"Handling patient deletion for patient {patient_id}")
            
            # Soft delete patient in local database using idempotent operation
            ref_patient = self.soft_delete_ref_patient_idempotent(
                db=db,
                patient_id=patient_id,
                user_id=deleted_by
            )
            
            logger.info(f"Successfully synchronized patient {patient_id} deletion")
            return True
            
        except Exception as e:
            logger.error(f"Error handling patient deletion: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def close(self):
        """Close connections"""
        if self.client:
            self.client.close()
            logger.info("Scheduler patient consumer connections closed")


# Usage
if __name__ == "__main__":
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    consumer = PatientConsumer()
    
    try:
        consumer.start_consuming()
    except KeyboardInterrupt:
        logger.info("Shutting down patient consumer...")
    finally:
        consumer.close()
