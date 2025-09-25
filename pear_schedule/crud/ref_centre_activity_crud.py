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
        centre_activity: Centre Activity data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the activity
        
    Returns:
        Tuple of (RefCentreActivity, was_duplicate: bool)
        
    Raises:
        ValueError: If activity with same ID already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        # Check if centre activity already exists - this is a business rule violation for CREATE
        existing = db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == centre_activity.CentreActivityID).first()
        if existing:
            raise ValueError(f"Centre Activity with ID {centre_activity.CentreActivityID} already exists. Use update operation instead.")
        
        logger.info(f"Creating new centre activity {centre_activity.CentreActivityID}")
        
        # Use raw SQL for IDENTITY INSERT to handle specific ID
        query = text("""
            SET IDENTITY_INSERT [REF_CENTRE_ACTIVITY] ON;
            
            INSERT INTO [REF_CENTRE_ACTIVITY] (
                CentreActivityID, ActivityID, IsDeleted, IsCompulsory, IsFixed, IsGroup, StartDate, EndDate, MinDuration, MaxDuration, MinPeopleReq, FixedTimeSlots, CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById
            ) VALUES (
                :CentreActivityID, :ActivityID, :IsDeleted, :IsCompulsory, :IsFixed, :IsGroup, :StartDate, :EndDate, :MinDuration, :MaxDuration, :MinPeopleReq, :FixedTimeSlots, :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById
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
        
        # Return the created activity
        created_activity = db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == centre_activity.CentreActivityID).first()
        if not created_activity:
            raise Exception(f"Failed to create activity {created_activity.Id}")
            
        return created_activity
    
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
            # Return existing activity for duplicate events
            existing_activity = db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == centre_activity.CentreActivityID).first()
            logger.info(f"Duplicate create event for centre activity {centre_activity.CentreActivityID}, returning existing")
            return existing_activity, True
        
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
        updated_by: User/service updating the activity
        
    Returns:
        Tuple of (RefCentreActivity or None, was_duplicate: bool)
        None if activity not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        # Find the centre activity to update
        db_activity = db.query(RefCentreActivity).filter(
            RefCentreActivity.CentreActivityID == centre_activity_id,
            RefCentreActivity.IsDeleted == "0"
        ).first()
        
        if not db_activity:
            logger.warning(f"Centre Activity {centre_activity_id} not found for update")
            return None
        
        logger.debug(f"Updating activity {centre_activity_id}")
        
        # Update only the fields that were provided
        update_data = centre_activity_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_activity, field) and field != 'Id':  # Never update ID
                # Handle field name mappings
                setattr(db_activity, field, value)
                    
        # Always update the modification timestamp
        from datetime import datetime
        db_activity.UpdatedDateTime = datetime.utcnow()
        db_activity.ModifiedById = updated_by
        
        db.flush()
        return db_activity
    
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
            existing_activity = db.query(RefCentreActivity).filter(
                RefCentreActivity.CentreActivityID == centre_activity_id,
                RefCentreActivity.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for centre activity {centre_activity_id}, returning current state")
            return existing_activity, True
        
        if result is None:
            logger.warning(f"Centre Activity {centre_activity_id} not found for update")
            db.commit()  # Commit the idempotency record even if activity not found
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
    Soft delete an centre activity with idempotency protection.
    
    Args:
        db: Database session
        centre_activity_id: ID of centre activity to delete
        correlation_id: Correlation ID from outbox service for deduplication
        deleted_by: User/service deleting the activity
        
    Returns:
        Tuple of (RefCentreActivity or None, was_duplicate: bool)
        None if activity not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        # Find the activity to delete
        db_activity = db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == centre_activity_id).first()
        
        if not db_activity:
            logger.warning(f"Centre Activity {centre_activity_id} not found for deletion")
            return None
        
        if db_activity.IsDeleted == "1":
            logger.info(f"Centre Activity {centre_activity_id} already deleted")
            return db_activity
        
        logger.info(f"Soft deleting centre activity {centre_activity_id}")
        
        # Perform soft delete
        from datetime import datetime
        db_activity.IsDeleted = "1"
        db_activity.UpdatedDateTime = datetime.utcnow()
        db_activity.ModifiedById = deleted_by
        
        db.flush()
        return db_activity
    
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
            existing_activity = db.query(RefCentreActivity).filter(RefCentreActivity.CentreActivityID == centre_activity_id).first()
            logger.info(f"Duplicate delete event for centre activity {centre_activity_id}, returning current state")
            return existing_activity, True
        
        if result is None:
            logger.warning(f"Activity {centre_activity_id} not found for deletion")
            db.commit()  # Commit the idempotency record even if activity not found
            return None, False
        
        db.commit()
        logger.info(f"Successfully deleted activity {centre_activity_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting activity {centre_activity_id}: {str(e)}")
        raise

def get_ref_centre_activity_by_id(db: Session, centre_activity_id: int) -> Optional[RefCentreActivity]:
    """
    Get a single activity by ID.
    
    Args:
        db: Database session
        activity_id: Activity ID to find
        
    Returns:
        RefActivity if found, None otherwise
    """
    return db.query(RefCentreActivity).filter(
        RefCentreActivity.CentreActivityID == centre_activity_id,
        RefCentreActivity.IsDeleted == "0"
    ).first()


def get_ref_centre_activities(
    db: Session,
    page_no: int = 0,
    page_size: int = 10,
    is_deleted: Optional[str] = "0"
) -> Tuple[List[RefCentreActivity], int, int]:
    """
    Get paginated list of centre activities with optional filters.
    
    Args:
        db: Database session
        page_no: Page number (0-based)
        page_size: Number of items per page
        is_deleted: Optional deletion status filter ("0" for active, "1" for deleted)
        
    Returns:
        Tuple of (activities_list, total_records, total_pages)
    """
    # Base query
    query = db.query(RefCentreActivity)
    
    # Apply deletion filter (default to active activities only)
    if is_deleted is not None:
        query = query.filter(RefCentreActivity.IsDeleted == is_deleted)
    
    # Count total records with same filters
    count_query = db.query(func.count(RefCentreActivity.CentreActivityID))
    
    if is_deleted is not None:
        count_query = count_query.filter(RefCentreActivity.IsDeleted == is_deleted)
    
    total_records = count_query.scalar()
    total_pages = math.ceil(total_records / page_size) if page_size > 0 else 1
    
    # Apply pagination and get results
    offset = page_no * page_size
    activities = query.order_by(RefCentreActivity.CentreActivityID.asc()).offset(offset).limit(page_size).all()
    
    return activities, total_records, total_pages


def check_activity_exists(db: Session, centre_activity_id: int) -> bool:
    """
    Check if an activity exists (including deleted ones).
    
    Args:
        db: Database session
        centre_activity_id: Centre Activity ID to check
        
    Returns:
        True if activity exists, False otherwise
    """
    count = db.query(func.count(RefCentreActivity.CentreActivityID)).filter(
        RefCentreActivity.CentreActivityID == centre_activity_id
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
