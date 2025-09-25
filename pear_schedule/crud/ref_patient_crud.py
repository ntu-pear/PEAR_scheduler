from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
import logging
import math
from ..models import RefPatient
from ..models.processed_events_model import ProcessedEvent
from ..schemas.ref_patient import RefPatientCreate, RefPatientUpdate
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

def create_ref_patient(
    db: Session,
    patient: RefPatientCreate,
    correlation_id: str,
    created_by: str
) -> Tuple[RefPatient, bool]:
    """
    Create a new patient with idempotency protection.
    
    Args:
        db: Database session
        patient: Patient data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the patient
        
    Returns:
        Tuple of (RefPatient, was_duplicate: bool)
        
    Raises:
        ValueError: If patient with same ID already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        # Check if patient already exists - this is a business rule violation for CREATE
        existing = db.query(RefPatient).filter(RefPatient.PatientID == patient.PatientID).first()
        if existing:
            raise ValueError(f"Patient with ID {patient.PatientID} already exists. Use update operation instead.")
        
        logger.info(f"Creating new patient {patient.PatientID}")
        
        # Use raw SQL for IDENTITY INSERT to handle specific ID
        query = text("""
            SET IDENTITY_INSERT [REF_PATIENT] ON;
            
            INSERT INTO [REF_PATIENT] (
                PatientID, Name, PreferredName, UpdateBit, StartDate, EndDate, IsActive, IsDeleted,
                CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById
            ) VALUES (
                :PatientID, :Name, :PreferredName, :UpdateBit, :StartDate, :EndDate, :IsActive, :IsDeleted,
                :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById
            );
            
            SET IDENTITY_INSERT [REF_PATIENT] OFF;
        """)
        
        params = {
            "PatientID": patient.PatientID,
            "Name": patient.Name,
            "PreferredName": patient.PreferredName,
            "UpdateBit": patient.UpdateBit,
            "StartDate": patient.StartDate,
            "EndDate": patient.EndDate,
            "IsActive": patient.IsActive,
            "IsDeleted": patient.IsDeleted or "0",
            "CreatedDateTime": patient.CreatedDateTime,
            "UpdatedDateTime": patient.UpdatedDateTime,
            "CreatedById": created_by,
            "ModifiedById": created_by,
        }
        
        db.execute(query, params)
        db.flush()
        
        # Return the created patient
        created_patient = db.query(RefPatient).filter(RefPatient.PatientID == patient.PatientID).first()
        if not created_patient:
            raise Exception(f"Failed to create patient {patient.PatientID}")
            
        return created_patient
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="PATIENT_CREATED",
            aggregate_id=str(patient.PatientID),
            processed_by=f"scheduler_service_{created_by}",
            operation=create_operation
        )
        
        if was_duplicate:
            # Return existing patient for duplicate events
            existing_patient = db.query(RefPatient).filter(RefPatient.PatientID == patient.PatientID).first()
            logger.info(f"Duplicate create event for patient {patient.PatientID}, returning existing")
            return existing_patient, True
        
        db.commit()
        logger.info(f"Successfully created patient {patient.PatientID}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating patient {patient.PatientID}: {str(e)}")
        raise

def update_ref_patient(
    db: Session,
    patient_id: str,
    patient_update: RefPatientUpdate,
    correlation_id: str,
    updated_by: str
) -> Tuple[Optional[RefPatient], bool]:
    """
    Update an existing patient with idempotency protection.
    
    Args:
        db: Database session
        patient_id: ID of patient to update
        patient_update: Fields to update
        correlation_id: Correlation ID from outbox service for deduplication
        updated_by: User/service updating the patient
        
    Returns:
        Tuple of (RefPatient or None, was_duplicate: bool)
        None if patient not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        # Find the patient to update
        db_patient = db.query(RefPatient).filter(
            RefPatient.PatientID == patient_id,
            RefPatient.IsDeleted == "0"
        ).first()
        
        if not db_patient:
            logger.warning(f"Patient {patient_id} not found for update")
            return None
        
        logger.debug(f"Updating patient {patient_id}")
        
        # Update only the fields that were provided
        update_data = patient_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_patient, field) and field != 'Id':  # Never update ID
                setattr(db_patient, field, value)
        
        db.flush()
        return db_patient
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="PATIENT_UPDATED",
            aggregate_id=patient_id,
            processed_by=f"scheduler_service_{updated_by}",
            operation=update_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_patient = db.query(RefPatient).filter(
                RefPatient.PatientID == patient_id,
                RefPatient.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for patient {patient_id}, returning current state")
            return existing_patient, True
        
        if result is None:
            logger.warning(f"Patient {patient_id} not found for update")
            db.commit()  # Commit the idempotency record even if patient not found
            return None, False
        
        db.commit()
        logger.debug(f"Successfully updated patient {patient_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating patient {patient_id}: {str(e)}")
        raise

def delete_ref_patient(
    db: Session,
    patient_id: str,
    correlation_id: str,
    deleted_by: str
) -> Tuple[Optional[RefPatient], bool]:
    """
    Soft delete a patient with idempotency protection.
    
    Args:
        db: Database session
        patient_id: ID of patient to delete
        correlation_id: Correlation ID from outbox service for deduplication
        deleted_by: User/service deleting the patient
        
    Returns:
        Tuple of (RefPatient or None, was_duplicate: bool)
        None if patient not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        # Find the patient to delete
        db_patient = db.query(RefPatient).filter(RefPatient.PatientID == patient_id).first()
        
        if not db_patient:
            logger.warning(f"Patient {patient_id} not found for deletion")
            return None
        
        if db_patient.IsDeleted == "1":
            logger.info(f"Patient {patient_id} already deleted")
            return db_patient
        
        logger.info(f"Soft deleting patient {patient_id}")
        
        # Perform soft delete
        db_patient.IsDeleted = "1"
        db.flush()
        return db_patient
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="PATIENT_DELETED",
            aggregate_id=patient_id,
            processed_by=f"scheduler_service_{deleted_by}",
            operation=delete_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_patient = db.query(RefPatient).filter(RefPatient.PatientID == patient_id).first()
            logger.info(f"Duplicate delete event for patient {patient_id}, returning current state")
            return existing_patient, True
        
        if result is None:
            logger.warning(f"Patient {patient_id} not found for deletion")
            db.commit()  # Commit the idempotency record even if patient not found
            return None, False
        
        db.commit()
        logger.info(f"Successfully deleted patient {patient_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting patient {patient_id}: {str(e)}")
        raise

def get_ref_patient_by_id(db: Session, patient_id: str) -> Optional[RefPatient]:
    """
    Get a single patient by ID.
    
    Args:
        db: Database session
        patient_id: Patient ID to find
        
    Returns:
        RefPatient if found, None otherwise
    """
    return db.query(RefPatient).filter(
        RefPatient.PatientID == patient_id,
        RefPatient.IsDeleted == "0"
    ).first()


def get_ref_patients(
    db: Session,
    page_no: int = 0,
    page_size: int = 10,
    name_filter: Optional[str] = None,
    is_active: Optional[str] = None
) -> Tuple[List[RefPatient], int, int]:
    """
    Get paginated list of patients with optional filters.
    
    Args:
        db: Database session
        page_no: Page number (0-based)
        page_size: Number of items per page
        name_filter: Optional name filter (partial match)
        is_active: Optional active status filter ("0" or "1")
        
    Returns:
        Tuple of (patients_list, total_records, total_pages)
    """
    # Base query - only active (non-deleted) patients
    query = db.query(RefPatient).filter(RefPatient.IsDeleted == "0")
    
    # Apply filters
    if name_filter:
        query = query.filter(RefPatient.Name.ilike(f"%{name_filter}%"))
    
    if is_active in ["0", "1"]:
        query = query.filter(RefPatient.IsActive == is_active)
    
    # Count total records with same filters
    count_query = db.query(func.count(RefPatient.PatientID)).filter(RefPatient.IsDeleted == "0")
    
    if name_filter:
        count_query = count_query.filter(RefPatient.Name.ilike(f"%{name_filter}%"))
    if is_active in ["0", "1"]:
        count_query = count_query.filter(RefPatient.IsActive == is_active)
    
    total_records = count_query.scalar()
    total_pages = math.ceil(total_records / page_size) if page_size > 0 else 1
    
    # Apply pagination and get results
    offset = page_no * page_size
    patients = query.order_by(RefPatient.Name.asc()).offset(offset).limit(page_size).all()
    
    return patients, total_records, total_pages


def check_patient_exists(db: Session, patient_id: str) -> bool:
    """
    Check if a patient exists (including deleted ones).
    
    Args:
        db: Database session
        patient_id: Patient ID to check
        
    Returns:
        True if patient exists, False otherwise
    """
    count = db.query(func.count(RefPatient.PatientID)).filter(
        RefPatient.PatientID == patient_id
    ).scalar()
    
    return count > 0

def get_idempotency_stats(db: Session) -> dict:
    """Get statistics about processed events for monitoring."""
    return IdempotencyService.get_processing_stats(db)


def cleanup_old_processed_events(db: Session, older_than_days: int = 30) -> int:
    """Clean up old processed events - should be run periodically."""
    return IdempotencyService.cleanup_old_events(db, older_than_days)


def is_event_already_processed(db: Session, correlation_id: str) -> bool:
    """Check if a specific correlation_id was already processed."""
    return IdempotencyService.is_already_processed(db, correlation_id)
