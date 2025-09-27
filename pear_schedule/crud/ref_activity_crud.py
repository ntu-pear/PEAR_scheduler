from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
import logging
import math
from ..models.ref_activity_model import RefActivity
from ..models.processed_events_model import ProcessedEvent
from ..schemas.ref_activity import RefActivityCreate, RefActivityUpdate, RefActivityDelete
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

def create_ref_activity(
    db: Session,
    activity: RefActivityCreate,
    correlation_id: str,
    created_by: str
) -> Tuple[RefActivity, bool]:
    """
    Create a new activity with idempotency protection.
    
    Args:
        db: Database session
        activity: Activity data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the activity
        
    Returns:
        Tuple of (RefActivity, was_duplicate: bool)
        
    Raises:
        ValueError: If activity with same ID already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        # Check if activity already exists - this is a business rule violation for CREATE
        existing = db.query(RefActivity).filter(RefActivity.ActivityID == activity.ActivityID).first()
        if existing:
            raise ValueError(f"Activity with ID {activity.ActivityID} already exists. Use update operation instead.")
        
        logger.info(f"Creating new activity {activity.ActivityID}")
        
        # Use raw SQL for IDENTITY INSERT to handle specific ID
        query = text("""
            SET IDENTITY_INSERT [REF_ACTIVITY] ON;
            
            INSERT INTO [REF_ACTIVITY] (
                ActivityID, ActivityTitle, ActivityDesc, IsDeleted,
                CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById
            ) VALUES (
                :ActivityID, :ActivityTitle, :ActivityDesc, :IsDeleted,
                :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById
            );
            
            SET IDENTITY_INSERT [REF_ACTIVITY] OFF;
        """)
        
        params = {
            "ActivityID": activity.ActivityID,
            "ActivityTitle": activity.ActivityTitle,
            "ActivityDesc": activity.ActivityDesc,
            "IsDeleted": activity.IsDeleted or "0",
            "CreatedDateTime": activity.CreatedDateTime,
            "UpdatedDateTime": activity.UpdatedDateTime,
            "CreatedById": created_by,
            "ModifiedById": created_by,
        }
        
        db.execute(query, params)
        db.flush()
        
        # Return the created activity
        created_activity = db.query(RefActivity).filter(RefActivity.ActivityID == activity.ActivityID).first()
        if not created_activity:
            raise Exception(f"Failed to create activity {activity.ActivityID}")
            
        return created_activity
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_CREATED",
            aggregate_id=str(activity.ActivityID),
            processed_by=f"scheduler_service_{created_by}",
            operation=create_operation
        )
        
        if was_duplicate:
            # Return existing activity for duplicate events
            existing_activity = db.query(RefActivity).filter(RefActivity.ActivityID == activity.ActivityID).first()
            logger.info(f"Duplicate create event for activity {activity.ActivityID}, returning existing")
            return existing_activity, True
        
        db.commit()
        logger.info(f"Successfully created activity {activity.ActivityID}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating activity {activity.ActivityID}: {str(e)}")
        raise

def update_ref_activity(
    db: Session,
    activity_id: int,
    activity_update: RefActivityUpdate,
    correlation_id: str
) -> Tuple[Optional[RefActivity], bool]:
    """
    Update an existing activity with idempotency protection.
    
    Args:
        db: Database session
        activity_id: ID of activity to update
        activity_update: Fields to update (includes UpdatedDateTime and ModifiedById)
        correlation_id: Correlation ID from outbox service for deduplication
        
    Returns:
        Tuple of (RefActivity or None, was_duplicate: bool)
        None if activity not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        # Find the activity to update
        db_activity = db.query(RefActivity).filter(
            RefActivity.ActivityID == activity_id,
            RefActivity.IsDeleted == "0"
        ).first()
        
        if not db_activity:
            logger.warning(f"Activity {activity_id} not found for update")
            return None
        
        logger.debug(f"Updating activity {activity_id}")
        
        # Update only the fields that were provided
        update_data = activity_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_activity, field) and field != 'ActivityID':  # Never update ID
                setattr(db_activity, field, value)
        
        db.flush()
        return db_activity
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_UPDATED",
            aggregate_id=str(activity_id),
            processed_by=f"scheduler_service_{activity_update.ModifiedById}",
            operation=update_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_activity = db.query(RefActivity).filter(
                RefActivity.ActivityID == activity_id,
                RefActivity.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for activity {activity_id}, returning current state")
            return existing_activity, True
        
        if result is None:
            logger.warning(f"Activity {activity_id} not found for update")
            db.commit()  # Commit the idempotency record even if activity not found
            return None, False
        
        db.commit()
        logger.debug(f"Successfully updated activity {activity_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating activity {activity_id}: {str(e)}")
        raise

def delete_ref_activity(
    db: Session,
    activity_id: int,
    activity_delete: RefActivityDelete,
    correlation_id: str
) -> Tuple[Optional[RefActivity], bool]:
    """
    Soft delete an activity with idempotency protection.
    
    Args:
        db: Database session
        activity_id: ID of activity to delete
        activity_delete: Delete data including timestamp and user info
        correlation_id: Correlation ID from outbox service for deduplication
        
    Returns:
        Tuple of (RefActivity or None, was_duplicate: bool)
        None if activity not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        # Find the activity to delete
        db_activity = db.query(RefActivity).filter(RefActivity.ActivityID == activity_id).first()
        
        if not db_activity:
            logger.warning(f"Activity {activity_id} not found for deletion")
            return None
        
        if db_activity.IsDeleted == "1":
            logger.info(f"Activity {activity_id} already deleted")
            return db_activity
        
        logger.info(f"Soft deleting activity {activity_id}")
        
        # Perform soft delete using schema data
        db_activity.IsDeleted = "1"
        db_activity.ModifiedById = activity_delete.ModifiedById
        db_activity.UpdatedDateTime = activity_delete.UpdatedDateTime
        
        db.flush()
        return db_activity
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_DELETED",
            aggregate_id=str(activity_id),
            processed_by=f"scheduler_service_{activity_delete.ModifiedById}",
            operation=delete_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_activity = db.query(RefActivity).filter(RefActivity.ActivityID == activity_id).first()
            logger.info(f"Duplicate delete event for activity {activity_id}, returning current state")
            return existing_activity, True
        
        if result is None:
            logger.warning(f"Activity {activity_id} not found for deletion")
            db.commit()  # Commit the idempotency record even if activity not found
            return None, False
        
        db.commit()
        logger.info(f"Successfully deleted activity {activity_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting activity {activity_id}: {str(e)}")
        raise

def get_ref_activity_by_id(db: Session, activity_id: int) -> Optional[RefActivity]:
    """
    Get a single activity by ID.
    
    Args:
        db: Database session
        activity_id: Activity ID to find
        
    Returns:
        RefActivity if found, None otherwise
    """
    return db.query(RefActivity).filter(
        RefActivity.ActivityID == activity_id,
        RefActivity.IsDeleted == "0"
    ).first()


def get_ref_activities(
    db: Session,
    page_no: int = 0,
    page_size: int = 10,
    title_filter: Optional[str] = None,
    is_deleted: Optional[str] = "0"
) -> Tuple[List[RefActivity], int, int]:
    """
    Get paginated list of activities with optional filters.
    
    Args:
        db: Database session
        page_no: Page number (0-based)
        page_size: Number of items per page
        title_filter: Optional title filter (partial match)
        is_deleted: Optional deletion status filter ("0" for active, "1" for deleted)
        
    Returns:
        Tuple of (activities_list, total_records, total_pages)
    """
    # Base query
    query = db.query(RefActivity)
    
    # Apply deletion filter (default to active activities only)
    if is_deleted is not None:
        query = query.filter(RefActivity.IsDeleted == is_deleted)
    
    # Apply title filter
    if title_filter:
        query = query.filter(RefActivity.ActivityTitle.ilike(f"%{title_filter}%"))
    
    # Count total records with same filters
    count_query = db.query(func.count(RefActivity.ActivityID))
    
    if is_deleted is not None:
        count_query = count_query.filter(RefActivity.IsDeleted == is_deleted)
    if title_filter:
        count_query = count_query.filter(RefActivity.ActivityTitle.ilike(f"%{title_filter}%"))
    
    total_records = count_query.scalar()
    total_pages = math.ceil(total_records / page_size) if page_size > 0 else 1
    
    # Apply pagination and get results
    offset = page_no * page_size
    activities = query.order_by(RefActivity.ActivityTitle.asc()).offset(offset).limit(page_size).all()
    
    return activities, total_records, total_pages


def check_activity_exists(db: Session, activity_id: int) -> bool:
    """
    Check if an activity exists (including deleted ones).
    
    Args:
        db: Database session
        activity_id: Activity ID to check
        
    Returns:
        True if activity exists, False otherwise
    """
    count = db.query(func.count(RefActivity.ActivityID)).filter(
        RefActivity.ActivityID == activity_id
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
