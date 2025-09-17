import logging
from typing import Dict, Any
from datetime import datetime

from .rabbitmq_client import RabbitMQClient

logger = logging.getLogger(__name__)

class PatientPrescriptionConsumer:
    """
    Consumer for patient prescription events from patient.updates exchange
    Updates the scheduler's local REF_PATIENT_PRESCRIPTION table
    """
    
    def __init__(self):
        self.client = RabbitMQClient("scheduler-patient-prescription-consumer")
        self.patient_queues = [
            "scheduler.patient.prescription.created",
            "scheduler.patient.prescription.updated",
            "scheduler.patient.prescription.deleted"
        ]
        
        # Import here to avoid circular imports
        from pear_schedule.crud.ref_patient_prescription_crud import (
            create_or_update_ref_patient_prescription,
            update_ref_patient_prescription_idempotent,
            soft_delete_ref_patient_prescription_idempotent
        )
        from pear_schedule.database import get_db
        from messaging.mappers.mapper_util import (
            map_patient_prescription_create,
            map_patient_prescription_update
        )
        
        self.create_or_update_ref_patient_prescription = create_or_update_ref_patient_prescription
        self.update_ref_patient_prescription_idempotent = update_ref_patient_prescription_idempotent
        self.soft_delete_ref_patient_prescription_idempotent = soft_delete_ref_patient_prescription_idempotent
        self.get_db = get_db
        
        self.map_patient_prescription_create = map_patient_prescription_create
        self.map_patient_prescription_update = map_patient_prescription_update
    
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
                self.client.consume(queue_name, self.handle_patient_prescription_message)
                logger.info(f"Set up consumer for scheduler queue: {queue_name}")
            
            logger.info("Scheduler patient prescription consumer setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduler patient prescription consumer: {str(e)}")
            raise
    
    def start_consuming(self):
        """Start consuming messages"""
        try:
            self.setup_consumer()
            logger.info("Starting scheduler patient prescription consumer...")
            self.client.start_consuming()
        except Exception as e:
            logger.error(f"Error starting scheduler patient prescription consumer: {str(e)}")
            raise
    
    def handle_patient_prescription_message(self, message: Dict[str, Any]) -> bool:
        """
        Handle incoming patient prescription messages from patient.updates exchange
        Returns True if message was processed successfully
        """
        try:
            # Log the full message for debugging
            logger.info(f"Received message: {message}")
            
            # Extract message data
            message_data = message.get('data', {})
            event_type = message_data.get('event_type')
            patient_prescription_id = message_data.get('patient_prescription_id')
            
            logger.info(f"Processing {event_type} for patient prescription {patient_prescription_id}")
            
            # Get database session
            db = next(self.get_db())
            
            try:
                if event_type == 'PATIENT_PRESCRIPTION_CREATED':
                    return self._handle_patient_prescription_created(db, message_data)
                    
                elif event_type == 'PATIENT_PRESCRIPTION_UPDATED':
                    return self._handle_patient_prescription_updated(db, message_data)
                    
                elif event_type == 'PATIENT_PRESCRIPTION_DELETED':
                    return self._handle_patient_prescription_deleted(db, message_data)
                    
                else:
                    logger.warning(f"Unknown event type: {event_type}")
                    return True  # Don't requeue unknown events
                    
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error processing patient prescription message: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False  # Requeue message
    
    def _handle_patient_prescription_created(self, db, message_data: Dict[str, Any]) -> bool:
        """Handle patient prescription creation events"""
        try:
            patient_prescription_id = message_data.get('patient_prescription_id')
            patient_prescription_data = message_data.get('patient_prescription_data', {})
            created_by = message_data.get('created_by', 'patient_service')
            
            logger.info(f"Handling patient prescription creation for patient prescription {patient_prescription_id}")
            logger.debug(f"Patient prescription data: {patient_prescription_data}")
            
            # Convert patient prescription data to scheduler's RefPatientPrescription format using simplified mapper
            mapped_patient_prescription_data = self.map_patient_prescription_create(patient_prescription_data)
            
            if not mapped_patient_prescription_data:
                logger.error(f"Failed to map patient prescription data for patient prescription {patient_prescription_id}")
                logger.debug(f"Source data: {patient_prescription_data}")
                return False
            
            logger.debug(f"Mapped patient prescription data: {mapped_patient_prescription_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_patient_prescription import RefPatientPrescriptionCreate
            try:
                ref_patient_prescription_data = RefPatientPrescriptionCreate(**mapped_patient_prescription_data)
            except Exception as e:
                logger.error(f"Failed to create RefPatientPrescriptionCreate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_patient_prescription_data}")
                return False
            
            # Create or update patient prescription in local database using idempotent operation
            ref_patient_prescription = self.create_or_update_ref_patient_prescription(
                db=db,
                prescription=ref_patient_prescription_data,
                user=created_by,
                user_full_name=created_by # TODO: Check if it's created_by or another field
            )
            
            if ref_patient_prescription:
                logger.info(f"Successfully synchronized patient prescription {patient_prescription_id} creation")
                return True
            else:
                logger.error(f"Failed to create/update ref_patient_prescription for patient prescription {patient_prescription_id}")
                return False
            
        except Exception as e:
            logger.error(f"Error handling patient prescription creation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def _handle_patient_prescription_updated(self, db, message_data: Dict[str, Any]) -> bool:
        """Handle patient prescription update events"""
        try:
            patient_prescription_id = message_data.get('patient_prescription_id')
            old_data = message_data.get('old_data', {})
            new_data = message_data.get('new_data', {})
            # changes = message_data.get('changes', {})
            modified_by = message_data.get('modified_by', 'patient_service')
            
            logger.info(f"Handling patient prescription update for patient prescription {patient_prescription_id}")
            # logger.debug(f"Changes: {changes}")
            
            # Convert new patient prescription data to scheduler's RefPatientPrescription format using simplified mapper
            mapped_update_data = self.map_patient_prescription_update(new_data)
            
            if not mapped_update_data:
                logger.error(f"Failed to map patient prescription update data for patient prescription {patient_prescription_id}")
                logger.debug(f"Source update data: {new_data}")
                return False
            
            logger.debug(f"Mapped update data: {mapped_update_data}")
            
            # Convert to Pydantic schema for CRUD function
            from pear_schedule.schemas.ref_patient_prescription import RefPatientPrescriptionUpdate
            try:
                ref_patient_prescription_update = RefPatientPrescriptionUpdate(**mapped_update_data)
            except Exception as e:
                logger.error(f"Failed to create RefPatientPrescriptionUpdate schema: {str(e)}")
                logger.error(f"Mapped data: {mapped_update_data}")
                return False
            
            # Update patient prescription in local database using idempotent operation
            ref_patient_prescription = self.update_ref_patient_prescription_idempotent(
                db=db,
                prescription_id=patient_prescription_id,
                prescription=ref_patient_prescription_update,
                user=modified_by
            )
            
            if ref_patient_prescription:
                logger.info(f"Successfully synchronized patient prescription {patient_prescription_id} update")
                
                # TODO: Skip scheduling checks for now

                # # Check if changes affect scheduling
                # scheduling_affecting_changes = [
                #     'IsActive', 'StartDate', 'EndDate', 'UpdateBit'
                # ]
                
                # if any(field in changes for field in scheduling_affecting_changes):
                #     logger.info(f"Patient prescription {patient_prescription_id} scheduling-relevant changes detected: {list(changes.keys())}")
                
                return True
            else:
                # Patient prescription doesn't exist in scheduler DB 
                # For UPDATE messages, this is unexpected - patient prescription should exist
                # Log this and return success to avoid reprocessing
                logger.warning(f"Patient prescription id {patient_prescription_id} not found for update - skipping message")
                logger.warning("Patient prescription should be created by PATIENT_PRESCRIPTION_CREATED message first")
                return True  # Return True to acknowledge message and avoid requeue
            
        except Exception as e:
            logger.error(f"Error handling patient prescription update: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def _handle_patient_prescription_deleted(self, db, message_data: Dict[str, Any]) -> bool:
        """Handle patient prescription deletion events"""
        try:
            patient_prescription_id = message_data.get('patient_prescription_id')
            deleted_by = message_data.get('deleted_by', 'patient_service')
            
            logger.info(f"Handling patient prescription deletion for patient prescription {patient_prescription_id}")
            
            # Soft delete patient prescription in local database using idempotent operation
            ref_patient_prescription = self.soft_delete_ref_patient_prescription_idempotent(
                db=db,
                prescription_id=patient_prescription_id,
                user_id=deleted_by
            )
            
            logger.info(f"Successfully synchronized patient prescription {patient_prescription_id} deletion")
            return True
            
        except Exception as e:
            logger.error(f"Error handling patient prescription deletion: {str(e)}")
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
    
    consumer = PatientPrescriptionConsumer()
    
    try:
        consumer.start_consuming()
    except KeyboardInterrupt:
        logger.info("Shutting down patient consumer...")
    finally:
        consumer.close()
