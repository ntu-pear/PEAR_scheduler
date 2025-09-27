from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
import logging
import math
from ..models.ref_patient_medication_model import RefPatientMedication
from ..models.processed_events_model import ProcessedEvent
from ..schemas.ref_patient_medication import RefPatientMedicationCreate, RefPatientMedicationUpdate, RefPatientMedicationDelete
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

def create_ref_patient_medication(
    db: Session,
    medication: RefPatientMedicationCreate,
    correlation_id: str,
    created_by: str
) -> Tuple[RefPatientMedication, bool]:
    """
    Create a new patient medication with idempotency protection.
    
    Args:
        db: Database session
        medication: Medication data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the medication
        
    Returns:
        Tuple of (RefPatientMedication, was_duplicate: bool)
        
    Raises:
        ValueError: If medication with same ID already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        # Check if medication already exists - this is a business rule violation for CREATE
        existing = db.query(RefPatientMedication).filter(RefPatientMedication.MedicationID == medication.MedicationID).first()
        if existing:
            raise ValueError(f"Patient medication with ID {medication.MedicationID} already exists. Use update operation instead.")
        
        logger.info(f"Creating new patient medication {medication.MedicationID} for patient {medication.PatientID}")
        
        # Use raw SQL for IDENTITY INSERT to handle specific ID
        query = text("""
            SET IDENTITY_INSERT [REF_PATIENT_MEDICATION] ON;
            
            INSERT INTO [REF_PATIENT_MEDICATION] (
                MedicationID, PatientID, PrescriptionName, Dosage, AdministerTime, Instruction,
                StartDateTime, EndDateTime, PrescriptionRemarks, IsDeleted,
                CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById
            ) VALUES (
                :MedicationID, :PatientID, :PrescriptionName, :Dosage, :AdministerTime, :Instruction,
                :StartDateTime, :EndDateTime, :PrescriptionRemarks, :IsDeleted,
                :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById
            );
            
            SET IDENTITY_INSERT [REF_PATIENT_MEDICATION] OFF;
        """)
        
        params = {
            "MedicationID": medication.MedicationID,
            "PatientID": medication.PatientID,
            "PrescriptionName": medication.PrescriptionName,
            "Dosage": medication.Dosage,
            "AdministerTime": medication.AdministerTime,
            "Instruction": medication.Instruction,
            "StartDateTime": medication.StartDate,
            "EndDateTime": medication.EndDate,
            "PrescriptionRemarks": medication.PrescriptionRemarks,
            "IsDeleted": medication.IsDeleted or "0",
            "CreatedDateTime": medication.CreatedDateTime,
            "UpdatedDateTime": medication.UpdatedDateTime,
            "CreatedById": created_by,
            "ModifiedById": created_by,
        }
        
        db.execute(query, params)
        db.flush()
        
        # Return the created medication
        created_medication = db.query(RefPatientMedication).filter(RefPatientMedication.MedicationID == medication.MedicationID).first()
        if not created_medication:
            raise Exception(f"Failed to create patient medication {medication.MedicationID}")
            
        return created_medication
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="PATIENT_MEDICATION_CREATED",
            aggregate_id=str(medication.MedicationID),
            processed_by=f"scheduler_service_{created_by}",
            operation=create_operation
        )
        
        if was_duplicate:
            # Return existing medication for duplicate events
            existing_medication = db.query(RefPatientMedication).filter(RefPatientMedication.MedicationID == medication.MedicationID).first()
            logger.info(f"Duplicate create event for patient medication {medication.MedicationID}, returning existing")
            return existing_medication, True
        
        db.commit()
        logger.info(f"Successfully created patient medication {medication.MedicationID}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating patient medication {medication.MedicationID}: {str(e)}")
        raise

def update_ref_patient_medication(
    db: Session,
    medication_id: int,
    medication_update: RefPatientMedicationUpdate,
    correlation_id: str
) -> Tuple[Optional[RefPatientMedication], bool]:
    """
    Update an existing patient medication with idempotency protection.
    
    Args:
        db: Database session
        medication_id: ID of medication to update
        medication_update: Fields to update (includes UpdatedDateTime and ModifiedById)
        correlation_id: Correlation ID from outbox service for deduplication
        
    Returns:
        Tuple of (RefPatientMedication or None, was_duplicate: bool)
        None if medication not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        # Find the medication to update
        db_medication = db.query(RefPatientMedication).filter(
            RefPatientMedication.MedicationID == medication_id,
            RefPatientMedication.IsDeleted == "0"
        ).first()
        
        if not db_medication:
            logger.warning(f"Patient medication {medication_id} not found for update")
            return None
        
        logger.debug(f"Updating patient medication {medication_id}")
        
        # Update only the fields that were provided
        update_data = medication_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_medication, field) and field != 'MedicationID':  # Never update ID
                setattr(db_medication, field, value)
        
        db.flush()
        return db_medication
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="PATIENT_MEDICATION_UPDATED",
            aggregate_id=str(medication_id),
            processed_by=f"scheduler_service_{medication_update.ModifiedById}",
            operation=update_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_medication = db.query(RefPatientMedication).filter(
                RefPatientMedication.MedicationID == medication_id,
                RefPatientMedication.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for patient medication {medication_id}, returning current state")
            return existing_medication, True
        
        if result is None:
            logger.warning(f"Patient medication {medication_id} not found for update")
            db.commit()  # Commit the idempotency record even if medication not found
            return None, False
        
        db.commit()
        logger.debug(f"Successfully updated patient medication {medication_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating patient medication {medication_id}: {str(e)}")
        raise

def delete_ref_patient_medication(
    db: Session,
    medication_id: int,
    medication_delete: RefPatientMedicationDelete,
    correlation_id: str
) -> Tuple[Optional[RefPatientMedication], bool]:
    """
    Soft delete a patient medication with idempotency protection.
    
    Args:
        db: Database session
        medication_id: ID of medication to delete
        medication_delete: Delete data including timestamp and user info
        correlation_id: Correlation ID from outbox service for deduplication
        
    Returns:
        Tuple of (RefPatientMedication or None, was_duplicate: bool)
        None if medication not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        # Find the medication to delete
        db_medication = db.query(RefPatientMedication).filter(RefPatientMedication.MedicationID == medication_id).first()
        
        if not db_medication:
            logger.warning(f"Patient medication {medication_id} not found for deletion")
            return None
        
        if db_medication.IsDeleted == "1":
            logger.info(f"Patient medication {medication_id} already deleted")
            return db_medication
        
        logger.info(f"Soft deleting patient medication {medication_id}")
        
        # Perform soft delete using schema data
        db_medication.IsDeleted = "1"
        db_medication.ModifiedById = medication_delete.ModifiedById
        db_medication.UpdatedDateTime = medication_delete.UpdatedDateTime
        
        db.flush()
        return db_medication
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="PATIENT_MEDICATION_DELETED",
            aggregate_id=str(medication_id),
            processed_by=f"scheduler_service_{medication_delete.ModifiedById}",
            operation=delete_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_medication = db.query(RefPatientMedication).filter(RefPatientMedication.MedicationID == medication_id).first()
            logger.info(f"Duplicate delete event for patient medication {medication_id}, returning current state")
            return existing_medication, True
        
        if result is None:
            logger.warning(f"Patient medication {medication_id} not found for deletion")
            db.commit()  # Commit the idempotency record even if medication not found
            return None, False
        
        db.commit()
        logger.info(f"Successfully deleted patient medication {medication_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting patient medication {medication_id}: {str(e)}")
        raise

def get_ref_patient_medication_by_id(db: Session, medication_id: int) -> Optional[RefPatientMedication]:
    """
    Get a single patient medication by ID.
    
    Args:
        db: Database session
        medication_id: Medication ID to find
        
    Returns:
        RefPatientMedication if found, None otherwise
    """
    return db.query(RefPatientMedication).filter(
        RefPatientMedication.MedicationID == medication_id,
        RefPatientMedication.IsDeleted == "0"
    ).first()

def get_idempotency_stats(db: Session) -> dict:
    """Get statistics about processed events for monitoring."""
    return IdempotencyService.get_processing_stats(db)

def cleanup_old_processed_events(db: Session, older_than_days: int = 30) -> int:
    """Clean up old processed events - should be run periodically."""
    return IdempotencyService.cleanup_old_events(db, older_than_days)

def is_event_already_processed(db: Session, correlation_id: str) -> bool:
    """Check if a specific correlation_id was already processed."""
    return IdempotencyService.is_already_processed(db, correlation_id)