from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
import logging
import math
from ..models.ref_activity_exclusion_model import RefActivityExclusion
from ..models.processed_events_model import ProcessedEvent
from ..schemas.ref_activity_exclusion import RefActivityExclusionCreate, RefActivityExclusionUpdate, RefActivityExclusionDelete
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

def create_ref_activity_exclusion(
    db: Session,
    exclusion: RefActivityExclusionCreate,
    correlation_id: str,
    created_by: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityExclusion], bool]:
    """
    Create a new activity exclusion with idempotency protection.
    
    Args:
        db: Database session
        exclusion: Activity exclusion data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the exclusion
        skip_duplicate_check: If True, bypass idempotency check (for sync events)
        
    Returns:
        Tuple of (RefActivityExclusion or None, was_duplicate: bool)
        
    Raises:
        ValueError: If exclusion with same combination already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        if hasattr(exclusion, 'ActivityExclusionID') and exclusion.ActivityExclusionID:
            existing = db.query(RefActivityExclusion).filter(
                RefActivityExclusion.ActivityExclusionID == exclusion.ActivityExclusionID
            ).first()
            
            if existing:
                if existing.IsDeleted == "1":
                    logger.info(f"Reactivating soft-deleted exclusion {exclusion.ActivityExclusionID}")
                    existing.IsDeleted = "0"
                    existing.PatientID = exclusion.PatientID
                    existing.CentreActivityID = exclusion.CentreActivityID
                    existing.StartDateTime = exclusion.StartDateTime
                    existing.EndDateTime = exclusion.EndDateTime
                    existing.ExclusionRemarks = exclusion.ExclusionRemarks
                    existing.UpdatedDateTime = exclusion.UpdatedDateTime
                    existing.ModifiedById = created_by
                    db.flush()
                    return existing
                else:
                    raise ValueError(f"Activity exclusion with ActivityExclusionID {exclusion.ActivityExclusionID} already exists.")
        else:
            existing = db.query(RefActivityExclusion).filter(
                RefActivityExclusion.PatientID == exclusion.PatientID,
                RefActivityExclusion.CentreActivityID == exclusion.CentreActivityID,
                RefActivityExclusion.IsDeleted == "0"
            ).first()
            
            if existing:
                logger.info(f"Found existing exclusion for Patient {exclusion.PatientID}, Activity {exclusion.CentreActivityID}")
                existing.StartDateTime = exclusion.StartDateTime
                existing.EndDateTime = exclusion.EndDateTime
                existing.ExclusionRemarks = exclusion.ExclusionRemarks
                existing.UpdatedDateTime = exclusion.UpdatedDateTime
                existing.ModifiedById = created_by
                db.flush()
                return existing
        
        logger.info(f"Creating new activity exclusion for Patient {exclusion.PatientID}, Activity {exclusion.CentreActivityID}")
        
        new_exclusion = RefActivityExclusion(
            PatientID=exclusion.PatientID,
            CentreActivityID=exclusion.CentreActivityID,
            StartDateTime=exclusion.StartDateTime,
            EndDateTime=exclusion.EndDateTime,
            ExclusionRemarks=exclusion.ExclusionRemarks,
            IsDeleted=exclusion.IsDeleted or "0",
            CreatedDateTime=exclusion.CreatedDateTime,
            UpdatedDateTime=exclusion.UpdatedDateTime,
            CreatedById=created_by,
            ModifiedById=created_by
        )
        
        if hasattr(exclusion, 'ActivityExclusionID') and exclusion.ActivityExclusionID:
            new_exclusion.ActivityExclusionID = exclusion.ActivityExclusionID
        
        db.add(new_exclusion)
        db.flush()
        return new_exclusion
    
    aggregate_key = str(exclusion.ActivityExclusionID) if hasattr(exclusion, 'ActivityExclusionID') and exclusion.ActivityExclusionID else f"{exclusion.PatientID}_{exclusion.CentreActivityID}"
    
    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity exclusion {aggregate_key} (sync event)")
            result = create_operation()
            was_duplicate = False
            
            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ACTIVITY_EXCLUSION_CREATED",
                    aggregate_id=aggregate_key,
                    processed_by=f"scheduler_service_{created_by}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ACTIVITY_EXCLUSION_CREATED",
                aggregate_id=aggregate_key,
                processed_by=f"scheduler_service_{created_by}",
                operation=create_operation
            )
        
        if was_duplicate:
            if hasattr(exclusion, 'ActivityExclusionID') and exclusion.ActivityExclusionID:
                existing_exclusion = db.query(RefActivityExclusion).filter(
                    RefActivityExclusion.ActivityExclusionID == exclusion.ActivityExclusionID
                ).first()
            else:
                existing_exclusion = db.query(RefActivityExclusion).filter(
                    RefActivityExclusion.PatientID == exclusion.PatientID,
                    RefActivityExclusion.CentreActivityID == exclusion.CentreActivityID,
                    RefActivityExclusion.IsDeleted == "0"
                ).first()
            logger.info(f"Duplicate create event for activity exclusion {aggregate_key}, returning existing")
            return existing_exclusion, True
        
        db.commit()
        logger.info(f"Successfully created activity exclusion {aggregate_key}")
        return result, False
        
    except Exception as e:
        db.rollback()
        error_msg = str(e)
        
        if "FOREIGN KEY constraint" in error_msg:
            if "REF_PATIENT" in error_msg:
                logger.warning(f"Patient does not exist in scheduler database for exclusion {aggregate_key}")
            elif "REF_ACTIVITY" in error_msg:
                logger.warning(f"Activity does not exist in scheduler database for exclusion {aggregate_key}")
        
        logger.error(f"Error creating activity exclusion {aggregate_key}: {error_msg}")
        raise

def update_ref_activity_exclusion(
    db: Session,
    exclusion_id: int,
    exclusion_update: RefActivityExclusionUpdate,
    correlation_id: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityExclusion], bool]:
    """
    Update an existing activity exclusion with idempotency protection.
    
    Args:
        db: Database session
        exclusion_id: ActivityExclusionID of exclusion to update
        exclusion_update: Fields to update (includes UpdatedDateTime and ModifiedById)
        correlation_id: Correlation ID from outbox service for deduplication
        skip_duplicate_check: If True, bypass idempotency check (for sync events)
        
    Returns:
        Tuple of (RefActivityExclusion or None, was_duplicate: bool)
        None if exclusion not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        db_exclusion = db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == exclusion_id
        ).first()
        
        if not db_exclusion:
            logger.warning(f"Activity exclusion {exclusion_id} not found for update")
            return None
        
        logger.debug(f"Updating activity exclusion {exclusion_id}")
        
        update_data = exclusion_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_exclusion, field) and field != 'ActivityExclusionID':
                setattr(db_exclusion, field, value)
        
        db.flush()
        return db_exclusion
    
    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity exclusion {exclusion_id} (sync event)")
            result = update_operation()
            was_duplicate = False
            
            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ACTIVITY_EXCLUSION_UPDATED",
                    aggregate_id=str(exclusion_id),
                    processed_by=f"scheduler_service_{exclusion_update.ModifiedById}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ACTIVITY_EXCLUSION_UPDATED",
                aggregate_id=str(exclusion_id),
                processed_by=f"scheduler_service_{exclusion_update.ModifiedById}",
                operation=update_operation
            )
        
        if was_duplicate:
            existing_exclusion = db.query(RefActivityExclusion).filter(
                RefActivityExclusion.ActivityExclusionID == exclusion_id,
                RefActivityExclusion.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for activity exclusion {exclusion_id}, returning current state")
            return existing_exclusion, True
        
        if result is None:
            logger.warning(f"Activity exclusion {exclusion_id} not found for update")
            db.commit()
            return None, False
        
        db.commit()
        logger.debug(f"Successfully updated activity exclusion {exclusion_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating activity exclusion {exclusion_id}: {str(e)}")
        raise

def delete_ref_activity_exclusion(
    db: Session,
    exclusion_id: int,
    exclusion_delete: RefActivityExclusionDelete,
    correlation_id: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityExclusion], bool]:
    """
    Soft delete an activity exclusion with idempotency protection.
    
    Args:
        db: Database session
        exclusion_id: ActivityExclusionID of exclusion to delete
        exclusion_delete: Delete data including timestamp and user info
        correlation_id: Correlation ID from outbox service for deduplication
        skip_duplicate_check: If True, bypass idempotency check (for sync events)
        
    Returns:
        Tuple of (RefActivityExclusion or None, was_duplicate: bool)
        None if exclusion not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        db_exclusion = db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == exclusion_id
        ).first()
        
        if not db_exclusion:
            logger.warning(f"Activity exclusion {exclusion_id} not found for deletion")
            return None
        
        if db_exclusion.IsDeleted == "1":
            logger.info(f"Activity exclusion {exclusion_id} already deleted")
            return db_exclusion
        
        logger.info(f"Soft deleting activity exclusion {exclusion_id}")
        
        db_exclusion.IsDeleted = "1"
        db_exclusion.ModifiedById = exclusion_delete.ModifiedById
        db_exclusion.UpdatedDateTime = exclusion_delete.UpdatedDateTime
        
        db.flush()
        return db_exclusion
    
    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity exclusion {exclusion_id} (sync event)")
            result = delete_operation()
            was_duplicate = False
            
            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ACTIVITY_EXCLUSION_DELETED",
                    aggregate_id=str(exclusion_id),
                    processed_by=f"scheduler_service_{exclusion_delete.ModifiedById}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ACTIVITY_EXCLUSION_DELETED",
                aggregate_id=str(exclusion_id),
                processed_by=f"scheduler_service_{exclusion_delete.ModifiedById}",
                operation=delete_operation
            )
        
        if was_duplicate:
            existing_exclusion = db.query(RefActivityExclusion).filter(
                RefActivityExclusion.ActivityExclusionID == exclusion_id
            ).first()
            logger.info(f"Duplicate delete event for activity exclusion {exclusion_id}, returning current state")
            return existing_exclusion, True
        
        if result is None:
            logger.warning(f"Activity exclusion {exclusion_id} not found for deletion")
            db.commit()
            return None, False
        
        db.commit()
        logger.info(f"Successfully deleted activity exclusion {exclusion_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting activity exclusion {exclusion_id}: {str(e)}")
        raise

def get_idempotency_stats(db: Session) -> dict:
    """Get statistics about processed events for monitoring."""
    return IdempotencyService.get_processing_stats(db)

def cleanup_old_processed_events(db: Session, older_than_days: int = 30) -> int:
    """Clean up old processed events - should be run periodically."""
    return IdempotencyService.cleanup_old_events(db, older_than_days)

def is_event_already_processed(db: Session, correlation_id: str) -> bool:
    """Check if a specific correlation_id was already processed."""
    return IdempotencyService.is_already_processed(db, correlation_id)
