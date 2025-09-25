from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
import logging
import math
from ..models.ref_centre_activity_model import RefCentreActivity
from ..models.processed_events_model import ProcessedEvent
from ..schemas.ref_centre_activity import RefCentreActivityCreate, RefCentreActivityUpdate
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

def create_ref_centre_activity(
    db: Session,
    centre_activity: RefCentreActivityCreate,
    correlation_id: str,
    created_by: str
) -> Tuple[RefCentreActivity, bool]:
    """
    Create a new centre activity with idempotency protection.
    
    Args:
        db: Database session
        centre_activity: Centre activity data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the centre activity
        
    Returns:
        Tuple of (RefCentreActivity, was_duplicate: bool)
        
    Raises:
        ValueError: If centre activity with same ID already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        # Check if centre activity already exists - this is a business rule violation for CREATE
        existing = db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == centre_activity.CentreActivityID
        ).first()
        if existing:
            raise ValueError(f"Centre Activity with ID {centre_activity.CentreActivityID} already exists. Use update operation instead.")
        
        logger.info(f"Creating new centre activity {centre_activity.CentreActivityID}")
        
        # Use raw SQL for IDENTITY INSERT to handle specific ID
        query = text("""
            SET IDENTITY_INSERT [REF_CENTRE_ACTIVITY] ON;
            
            INSERT INTO [REF_CENTRE_ACTIVITY] (
                CentreActivityID, ActivityID, IsDeleted, IsCompulsory, IsFixed, IsGroup,
                StartDate, EndDate, MinDuration, MaxDuration, MinPeopleReq, FixedTimeSlots,
                CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById
            ) VALUES (
                :CentreActivityID, :ActivityID, :IsDeleted, :IsCompulsory, :IsFixed, :IsGroup,
                :StartDate, :EndDate, :MinDuration, :MaxDuration, :MinPeopleReq, :FixedTimeSlots,
                :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById
            );
            
            SET IDENTITY_INSERT [REF_CENTRE_ACTIVITY] OFF;
        """)
        
        params = {
            "CentreActivityID": centre_activity.CentreActivityID,
            "ActivityID": centre_activity.ActivityID,
            "IsDeleted": centre_activity.IsDeleted or "0",
            "IsCompulsory": centre_activity.IsCompulsory or "0",
            "IsFixed": centre_activity.IsFixed or "0",
            "IsGroup": centre_activity.IsGroup or "0",
            "StartDate": centre_activity.StartDate,
            "EndDate": centre_activity.EndDate,
            "MinDuration": centre_activity.MinDuration,
            "MaxDuration": centre_activity.MaxDuration,
            "MinPeopleReq": centre_activity.MinPeopleReq,
            "FixedTimeSlots": centre_activity.FixedTimeSlots,
            "CreatedDateTime": centre_activity.CreatedDateTime,
            "UpdatedDateTime": centre_activity.UpdatedDateTime,
            "CreatedById": created_by,
            "ModifiedById": created_by,
        }
        
        db.execute(query, params)
        db.flush()
        
        # Return the created centre activity
        created_centre_activity = db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == centre_activity.CentreActivityID
        ).first()
        if not created_centre_activity:
            raise Exception(f"Failed to create centre activity {centre_activity.CentreActivityID}")
            
        return created_centre_activity
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="CENTRE_ACTIVITY_CREATED",
            aggregate_id=str(centre_activity.CentreActivityID),
            processed_by=f"scheduler_service_{created_by}",
            operation=create_operation
        )
        
        if was_duplicate:
            # Return existing centre activity for duplicate events
            existing_centre_activity = db.query(RefCentreActivity).filter(
                RefCentreActivity.CentreActivityID == centre_activity.CentreActivityID
            ).first()
            logger.info(f"Duplicate create event for centre activity {centre_activity.CentreActivityID}, returning existing")
            return existing_centre_activity, True
        
        db.commit()
        logger.info(f"Successfully created centre activity {centre_activity.CentreActivityID}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating centre activity {centre_activity.CentreActivityID}: {str(e)}")
        raise

def update_ref_centre_activity(
    db: Session,
    centre_activity_id: int,
    centre_activity_update: RefCentreActivityUpdate,
    correlation_id: str,
    updated_by: str
) -> Tuple[Optional[RefCentreActivity], bool]:
    """
    Update an existing centre activity with idempotency protection.
    
    Args:
        db: Database session
        centre_activity_id: ID of centre activity to update
        centre_activity_update: Fields to update
        correlation_id: Correlation ID from outbox service for deduplication
        updated_by: User/service updating the centre activity
        
    Returns:
        Tuple of (RefCentreActivity or None, was_duplicate: bool)
        None if centre activity not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        # Find the centre activity to update
        db_centre_activity = db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == centre_activity_id,
            RefCentreActivity.IsDeleted == "0"
        ).first()
        
        if not db_centre_activity:
            logger.warning(f"Centre Activity {centre_activity_id} not found for update")
            return None
        
        logger.debug(f"Updating centre activity {centre_activity_id}")
        
        # Update only the fields that were provided
        update_data = centre_activity_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_centre_activity, field) and field != 'CentreActivityID':  # Never update ID
                setattr(db_centre_activity, field, value)
        
        # Always update the modification timestamp
        from datetime import datetime
        db_centre_activity.UpdatedDateTime = datetime.utcnow()
        db_centre_activity.ModifiedById = updated_by
        
        db.flush()
        return db_centre_activity
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="CENTRE_ACTIVITY_UPDATED",
            aggregate_id=str(centre_activity_id),
            processed_by=f"scheduler_service_{updated_by}",
            operation=update_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_centre_activity = db.query(RefCentreActivity).filter(
                RefCentreActivity.CentreActivityID == centre_activity_id,
                RefCentreActivity.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for centre activity {centre_activity_id}, returning current state")
            return existing_centre_activity, True
        
        if result is None:
            logger.warning(f"Centre Activity {centre_activity_id} not found for update")
            db.commit()  # Commit the idempotency record even if centre activity not found
            return None, False
        
        db.commit()
        logger.debug(f"Successfully updated centre activity {centre_activity_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating centre activity {centre_activity_id}: {str(e)}")
        raise

def delete_ref_centre_activity(
    db: Session,
    centre_activity_id: int,
    correlation_id: str,
    deleted_by: str
) -> Tuple[Optional[RefCentreActivity], bool]:
    """
    Soft delete a centre activity with idempotency protection.
    
    Args:
        db: Database session
        centre_activity_id: ID of centre activity to delete
        correlation_id: Correlation ID from outbox service for deduplication
        deleted_by: User/service deleting the centre activity
        
    Returns:
        Tuple of (RefCentreActivity or None, was_duplicate: bool)
        None if centre activity not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        # Find the centre activity to delete
        db_centre_activity = db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == centre_activity_id
        ).first()
        
        if not db_centre_activity:
            logger.warning(f"Centre Activity {centre_activity_id} not found for deletion")
            return None
        
        if db_centre_activity.IsDeleted == "1":
            logger.info(f"Centre Activity {centre_activity_id} already deleted")
            return db_centre_activity
        
        logger.info(f"Soft deleting centre activity {centre_activity_id}")
        
        # Perform soft delete
        from datetime import datetime
        db_centre_activity.IsDeleted = "1"
        db_centre_activity.UpdatedDateTime = datetime.utcnow()
        db_centre_activity.ModifiedById = deleted_by
        
        db.flush()
        return db_centre_activity
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="CENTRE_ACTIVITY_DELETED",
            aggregate_id=str(centre_activity_id),
            processed_by=f"scheduler_service_{deleted_by}",
            operation=delete_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_centre_activity = db.query(RefCentreActivity).filter(
                RefCentreActivity.CentreActivityID == centre_activity_id
            ).first()
            logger.info(f"Duplicate delete event for centre activity {centre_activity_id}, returning current state")
            return existing_centre_activity, True
        
        if result is None:
            logger.warning(f"Centre Activity {centre_activity_id} not found for deletion")
            db.commit()  # Commit the idempotency record even if centre activity not found
            return None, False
        
        db.commit()
        logger.info(f"Successfully deleted centre activity {centre_activity_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting centre activity {centre_activity_id}: {str(e)}")
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
