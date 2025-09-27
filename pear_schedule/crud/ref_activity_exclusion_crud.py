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
    created_by: str
) -> Tuple[Optional[RefActivityExclusion], bool]:
    """
    Create a new activity exclusion with idempotency protection.
    
    Args:
        db: Database session
        exclusion: Activity exclusion data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the exclusion
        
    Returns:
        Tuple of (RefActivityExclusion or None, was_duplicate: bool)
        
    Raises:
        ValueError: If exclusion with same combination already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        # For exclusions, we need to handle the fact that we might not have an ActivityExclusionID
        # from the activity service. Check if one is provided, otherwise create based on combination
        if hasattr(exclusion, 'ActivityExclusionID') and exclusion.ActivityExclusionID:
            # Check by ActivityExclusionID if provided
            existing = db.query(RefActivityExclusion).filter(
                RefActivityExclusion.ActivityExclusionID == exclusion.ActivityExclusionID
            ).first()
            
            if existing:
                if existing.IsDeleted == "1":
                    # Reactivate soft-deleted exclusion
                    logger.info(f"Reactivating soft-deleted exclusion {exclusion.ActivityExclusionID}")
                    existing.IsDeleted = "0"
                    existing.PatientID = exclusion.PatientID
                    existing.ActivityID = exclusion.ActivityID
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
            # Check by PatientID and ActivityID combination if no ActivityExclusionID provided
            existing = db.query(RefActivityExclusion).filter(
                RefActivityExclusion.PatientID == exclusion.PatientID,
                RefActivityExclusion.ActivityID == exclusion.ActivityID,
                RefActivityExclusion.IsDeleted == "0"
            ).first()
            
            if existing:
                # For combination-based duplicates, we could update instead of error
                logger.info(f"Found existing exclusion for Patient {exclusion.PatientID}, Activity {exclusion.ActivityID}")
                # Update the existing record
                existing.StartDateTime = exclusion.StartDateTime
                existing.EndDateTime = exclusion.EndDateTime
                existing.ExclusionRemarks = exclusion.ExclusionRemarks
                existing.UpdatedDateTime = exclusion.UpdatedDateTime
                existing.ModifiedById = created_by
                db.flush()
                return existing
        
        logger.info(f"Creating new activity exclusion for Patient {exclusion.PatientID}, Activity {exclusion.ActivityID}")
        
        # Create new exclusion
        new_exclusion = RefActivityExclusion(
            PatientID=exclusion.PatientID,
            ActivityID=exclusion.ActivityID,
            StartDateTime=exclusion.StartDateTime,
            EndDateTime=exclusion.EndDateTime,
            ExclusionRemarks=exclusion.ExclusionRemarks,
            IsDeleted=exclusion.IsDeleted or "0",
            CreatedDateTime=exclusion.CreatedDateTime,
            UpdatedDateTime=exclusion.UpdatedDateTime,
            CreatedById=created_by,
            ModifiedById=created_by
        )
        
        # Set ActivityExclusionID if provided
        if hasattr(exclusion, 'ActivityExclusionID') and exclusion.ActivityExclusionID:
            new_exclusion.ActivityExclusionID = exclusion.ActivityExclusionID
        
        db.add(new_exclusion)
        db.flush()
        
        db.add(new_exclusion)
        db.flush()
        return new_exclusion
    
    # Use IdempotencyService for deduplication
    try:
        # Use a combination key if no ActivityExclusionID provided
        aggregate_key = str(exclusion.ActivityExclusionID) if hasattr(exclusion, 'ActivityExclusionID') and exclusion.ActivityExclusionID else f"{exclusion.PatientID}_{exclusion.ActivityID}"
        
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_EXCLUSION_CREATED",
            aggregate_id=aggregate_key,
            processed_by=f"scheduler_service_{created_by}",
            operation=create_operation
        )
        
        if was_duplicate:
            # Return existing exclusion for duplicate events
            if hasattr(exclusion, 'ActivityExclusionID') and exclusion.ActivityExclusionID:
                existing_exclusion = db.query(RefActivityExclusion).filter(
                    RefActivityExclusion.ActivityExclusionID == exclusion.ActivityExclusionID
                ).first()
            else:
                existing_exclusion = db.query(RefActivityExclusion).filter(
                    RefActivityExclusion.PatientID == exclusion.PatientID,
                    RefActivityExclusion.ActivityID == exclusion.ActivityID,
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
        
        # Check for foreign key constraint violations
        if "FOREIGN KEY constraint" in error_msg:
            if "REF_PATIENT" in error_msg:
                logger.warning(f"Patient does not exist in scheduler database for exclusion {aggregate_key}")
                # This is not necessarily an error - patient sync might be pending
            elif "REF_ACTIVITY" in error_msg:
                logger.warning(f"Activity does not exist in scheduler database for exclusion {aggregate_key}")
                # This is not necessarily an error - activity sync might be pending
        
        logger.error(f"Error creating activity exclusion {aggregate_key}: {error_msg}")
        raise

def update_ref_activity_exclusion(
    db: Session,
    exclusion_id: int,
    exclusion_update: RefActivityExclusionUpdate,
    correlation_id: str
) -> Tuple[Optional[RefActivityExclusion], bool]:
    """
    Update an existing activity exclusion with idempotency protection.
    
    Args:
        db: Database session
        exclusion_id: ActivityExclusionID of exclusion to update
        exclusion_update: Fields to update (includes UpdatedDateTime and ModifiedById)
        correlation_id: Correlation ID from outbox service for deduplication
        
    Returns:
        Tuple of (RefActivityExclusion or None, was_duplicate: bool)
        None if exclusion not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        # Find the exclusion to update
        db_exclusion = db.query(RefActivityExclusion).filter(
            RefActivityExclusion.ActivityExclusionID == exclusion_id,
            RefActivityExclusion.IsDeleted == "0"
        ).first()
        
        if not db_exclusion:
            logger.warning(f"Activity exclusion {exclusion_id} not found for update")
            return None
        
        logger.debug(f"Updating activity exclusion {exclusion_id}")
        
        # Update only the fields that were provided
        update_data = exclusion_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_exclusion, field) and field != 'ActivityExclusionID':  # Never update ID
                setattr(db_exclusion, field, value)
        
        db.flush()
        return db_exclusion
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_EXCLUSION_UPDATED",
            aggregate_id=str(exclusion_id),
            processed_by=f"scheduler_service_{exclusion_update.ModifiedById}",
            operation=update_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_exclusion = db.query(RefActivityExclusion).filter(
                RefActivityExclusion.ActivityExclusionID == exclusion_id,
                RefActivityExclusion.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for activity exclusion {exclusion_id}, returning current state")
            return existing_exclusion, True
        
        if result is None:
            logger.warning(f"Activity exclusion {exclusion_id} not found for update")
            db.commit()  # Commit the idempotency record even if exclusion not found
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
    correlation_id: str
) -> Tuple[Optional[RefActivityExclusion], bool]:
    """
    Soft delete an activity exclusion with idempotency protection.
    
    Args:
        db: Database session
        exclusion_id: ActivityExclusionID of exclusion to delete
        exclusion_delete: Delete data including timestamp and user info
        correlation_id: Correlation ID from outbox service for deduplication
        
    Returns:
        Tuple of (RefActivityExclusion or None, was_duplicate: bool)
        None if exclusion not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        # Find the exclusion to delete using ActivityExclusionID
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
        
        # Perform soft delete using schema data
        db_exclusion.IsDeleted = "1"
        db_exclusion.ModifiedById = exclusion_delete.ModifiedById
        db_exclusion.UpdatedDateTime = exclusion_delete.UpdatedDateTime
        
        db.flush()
        return db_exclusion
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_EXCLUSION_DELETED",
            aggregate_id=str(exclusion_id),
            processed_by=f"scheduler_service_{exclusion_delete.ModifiedById}",
            operation=delete_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_exclusion = db.query(RefActivityExclusion).filter(
                RefActivityExclusion.ActivityExclusionID == exclusion_id
            ).first()
            logger.info(f"Duplicate delete event for activity exclusion {exclusion_id}, returning current state")
            return existing_exclusion, True
        
        if result is None:
            logger.warning(f"Activity exclusion {exclusion_id} not found for deletion")
            db.commit()  # Commit the idempotency record even if exclusion not found
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
