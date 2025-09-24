from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
import logging
import math
from ..models.ref_patient_medication_model import RefPatientMedication
from ..models.processed_events_model import ProcessedEvent
from ..schemas.ref_patient_medication import RefPatientMedicationCreate, RefPatientMedicationUpdate
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
                MedicationID, PatientID, PrescriptionListValue, Dosage, AdministerTime, Instruction,
                StartDateTime, EndDateTime, PrescriptionRemarks, IsDeleted,
                CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById
            ) VALUES (
                :MedicationID, :PatientID, :PrescriptionListValue, :Dosage, :AdministerTime, :Instruction,
                :StartDateTime, :EndDateTime, :PrescriptionRemarks, :IsDeleted,
                :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById
            );
            
            SET IDENTITY_INSERT [REF_PATIENT_MEDICATION] OFF;
        """)
        
        params = {
            "MedicationID": medication.MedicationID,
            "PatientID": medication.PatientID,
            "PrescriptionListValue": getattr(medication, 'PrescriptionListValue', None),
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
    correlation_id: str,
    updated_by: str
) -> Tuple[Optional[RefPatientMedication], bool]:
    """
    Update an existing patient medication with idempotency protection.
    
    Args:
        db: Database session
        medication_id: ID of medication to update
        medication_update: Fields to update
        correlation_id: Correlation ID from outbox service for deduplication
        updated_by: User/service updating the medication
        
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
            if hasattr(db_medication, field) and field != 'Id':  # Never update ID
                # Handle field name mappings if needed
                if field == "PatientId":
                    setattr(db_medication, "PatientID", value)
                elif field == "PrescriptionListId":
                    setattr(db_medication, "PrescriptionListID", value)
                else:
                    setattr(db_medication, field, value)
        
        # Always update the modification timestamp
        from datetime import datetime
        db_medication.UpdatedDateTime = datetime.utcnow()
        db_medication.ModifiedById = updated_by
        
        db.flush()
        return db_medication
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="PATIENT_MEDICATION_UPDATED",
            aggregate_id=str(medication_id),
            processed_by=f"scheduler_service_{updated_by}",
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
    correlation_id: str,
    deleted_by: str
) -> Tuple[Optional[RefPatientMedication], bool]:
    """
    Soft delete a patient medication with idempotency protection.
    
    Args:
        db: Database session
        medication_id: ID of medication to delete
        correlation_id: Correlation ID from outbox service for deduplication
        deleted_by: User/service deleting the medication
        
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
        
        # Perform soft delete
        from datetime import datetime
        db_medication.IsDeleted = "1"
        db_medication.UpdatedDateTime = datetime.utcnow()
        db_medication.ModifiedById = deleted_by
        
        db.flush()
        return db_medication
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="PATIENT_MEDICATION_DELETED",
            aggregate_id=str(medication_id),
            processed_by=f"scheduler_service_{deleted_by}",
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

def get_ref_patient_medications(
    db: Session,
    page_no: int = 0,
    page_size: int = 10,
    patient_id: Optional[int] = None,
    is_deleted: Optional[str] = "0",
    administer_time_filter: Optional[str] = None
) -> Tuple[List[RefPatientMedication], int, int]:
    """
    Get paginated list of patient medications with optional filters.
    
    Args:
        db: Database session
        page_no: Page number (0-based)
        page_size: Number of items per page
        patient_id: Optional patient ID filter
        is_deleted: Optional deletion status filter ("0" for active, "1" for deleted)
        administer_time_filter: Optional administration time filter
        
    Returns:
        Tuple of (medications_list, total_records, total_pages)
    """
    # Base query
    query = db.query(RefPatientMedication)
    
    # Apply deletion filter (default to active medications only)
    if is_deleted is not None:
        query = query.filter(RefPatientMedication.IsDeleted == is_deleted)
    
    # Apply patient filter
    if patient_id:
        query = query.filter(RefPatientMedication.PatientID == patient_id)
    
    # Apply administration time filter
    if administer_time_filter:
        query = query.filter(RefPatientMedication.AdministerTime.ilike(f"%{administer_time_filter}%"))
    
    # Count total records with same filters
    count_query = db.query(func.count(RefPatientMedication.MedicationID))
    
    if is_deleted is not None:
        count_query = count_query.filter(RefPatientMedication.IsDeleted == is_deleted)
    if patient_id:
        count_query = count_query.filter(RefPatientMedication.PatientID == patient_id)
    if administer_time_filter:
        count_query = count_query.filter(RefPatientMedication.AdministerTime.ilike(f"%{administer_time_filter}%"))
    
    total_records = count_query.scalar()
    total_pages = math.ceil(total_records / page_size) if page_size > 0 else 1
    
    # Apply pagination and get results
    offset = page_no * page_size
    medications = query.order_by(RefPatientMedication.PatientID.asc(), RefPatientMedication.AdministerTime.asc()).offset(offset).limit(page_size).all()
    
    return medications, total_records, total_pages

def get_patient_active_medications(db: Session, patient_id: int) -> List[RefPatientMedication]:
    """
    Get all active medications for a patient.
    
    Args:
        db: Database session
        patient_id: Patient ID
        
    Returns:
        List of active medications for the patient
    """
    from datetime import datetime
    current_date = datetime.utcnow()
    
    return db.query(RefPatientMedication).filter(
        RefPatientMedication.PatientID == patient_id,
        RefPatientMedication.StartDate <= current_date,
        (RefPatientMedication.EndDate.is_(None)) | (RefPatientMedication.EndDate >= current_date),
        RefPatientMedication.IsDeleted == "0"
    ).order_by(RefPatientMedication.AdministerTime.asc()).all()

def get_medications_by_schedule(db: Session, administer_time: str) -> List[RefPatientMedication]:
    """
    Get all active medications scheduled for a specific time.
    
    Args:
        db: Database session
        administer_time: Administration time (e.g., "0800", "1200,1800")
        
    Returns:
        List of medications scheduled for that time
    """
    from datetime import datetime
    current_date = datetime.utcnow()
    
    # Handle both single times and comma-separated multiple times
    time_conditions = []
    if ',' in administer_time:
        # Multiple times - check if any of them match
        times = [t.strip() for t in administer_time.split(',')]
        for time in times:
            time_conditions.append(RefPatientMedication.AdministerTime.like(f"%{time}%"))
    else:
        # Single time
        time_conditions.append(RefPatientMedication.AdministerTime.like(f"%{administer_time}%"))
    
    # Build query with OR conditions for multiple times
    query = db.query(RefPatientMedication).filter(
        RefPatientMedication.StartDate <= current_date,
        (RefPatientMedication.EndDate.is_(None)) | (RefPatientMedication.EndDate >= current_date),
        RefPatientMedication.IsDeleted == "0"
    )
    
    # Add time conditions
    if time_conditions:
        from sqlalchemy import or_
        query = query.filter(or_(*time_conditions))
    
    return query.order_by(RefPatientMedication.PatientID.asc()).all()

def get_medications_ending_soon(db: Session, days: int = 7) -> List[RefPatientMedication]:
    """
    Get medications ending within specified days.
    
    Args:
        db: Database session
        days: Number of days to look ahead
        
    Returns:
        List of medications ending soon
    """
    from datetime import datetime, timedelta
    current_date = datetime.utcnow()
    end_date = current_date + timedelta(days=days)
    
    return db.query(RefPatientMedication).filter(
        RefPatientMedication.EndDate.is_not(None),
        RefPatientMedication.EndDate >= current_date,
        RefPatientMedication.EndDate <= end_date,
        RefPatientMedication.IsDeleted == "0"
    ).order_by(RefPatientMedication.EndDate.asc()).all()

def check_medication_exists(db: Session, medication_id: int) -> bool:
    """
    Check if a patient medication exists (including deleted ones).
    
    Args:
        db: Database session
        medication_id: Medication ID to check
        
    Returns:
        True if medication exists, False otherwise
    """
    count = db.query(func.count(RefPatientMedication.MedicationID)).filter(
        RefPatientMedication.MedicationID == medication_id
    ).scalar()
    
    return count > 0

def get_patient_medication_schedule(db: Session, patient_id: int, date_filter: Optional[str] = None) -> List[RefPatientMedication]:
    """
    Get patient's medication schedule for scheduling purposes.
    
    Args:
        db: Database session
        patient_id: Patient ID
        date_filter: Optional date filter (YYYY-MM-DD format)
        
    Returns:
        List of medications ordered by administration time
    """
    from datetime import datetime
    
    query = db.query(RefPatientMedication).filter(
        RefPatientMedication.PatientID == patient_id,
        RefPatientMedication.IsDeleted == "0"
    )
    
    # Apply date filter if provided
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            query = query.filter(
                RefPatientMedication.StartDate <= filter_date,
                (RefPatientMedication.EndDate.is_(None)) | (RefPatientMedication.EndDate >= filter_date)
            )
        except ValueError:
            logger.warning(f"Invalid date format: {date_filter}")
    else:
        # Default to current active medications
        current_date = datetime.utcnow()
        query = query.filter(
            RefPatientMedication.StartDate <= current_date,
            (RefPatientMedication.EndDate.is_(None)) | (RefPatientMedication.EndDate >= current_date)
        )
    
    return query.order_by(RefPatientMedication.AdministerTime.asc()).all()

def get_idempotency_stats(db: Session) -> dict:
    """Get statistics about processed events for monitoring."""
    return IdempotencyService.get_processing_stats(db)

def cleanup_old_processed_events(db: Session, older_than_days: int = 30) -> int:
    """Clean up old processed events - should be run periodically."""
    return IdempotencyService.cleanup_old_events(db, older_than_days)

def is_event_already_processed(db: Session, correlation_id: str) -> bool:
    """Check if a specific correlation_id was already processed."""
    return IdempotencyService.is_already_processed(db, correlation_id)