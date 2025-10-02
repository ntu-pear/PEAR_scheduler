from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
import logging
import math
from ..models.ref_activity_preference_model import RefActivityPreference
from ..models.processed_events_model import ProcessedEvent
from ..schemas.ref_activity_preference import RefActivityPreferenceCreate, RefActivityPreferenceUpdate, RefActivityPreferenceDelete
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

def create_ref_activity_preference(
    db: Session,
    preference: RefActivityPreferenceCreate,
    correlation_id: str,
    created_by: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityPreference], bool]:
    """
    Create a new activity preference with idempotency protection.
    
    Args:
        db: Database session
        preference: Activity preference data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the preference
        skip_duplicate_check: If True, bypass idempotency check (for sync events)
        
    Returns:
        Tuple of (RefActivityPreference or None, was_duplicate: bool)
        
    Raises:
        ValueError: If preference with same combination already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        existing = db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == preference.CentreActivityPreferenceID
        ).first()
        
        if existing:
            if existing.IsDeleted == "1":
                logger.info(f"Reactivating soft-deleted preference {preference.CentreActivityPreferenceID}")
                existing.IsDeleted = "0"
                existing.PatientID = preference.PatientID
                existing.CentreActivityID = preference.CentreActivityID
                existing.IsLike = preference.IsLike
                existing.UpdatedDateTime = preference.UpdatedDateTime
                existing.ModifiedById = created_by
                db.flush()
                return existing
            else:
                raise ValueError(f"Activity preference with CentreActivityPreferenceID {preference.CentreActivityPreferenceID} already exists.")
        
        logger.info(f"Creating new activity preference {preference.CentreActivityPreferenceID}")
        
        new_preference = RefActivityPreference(
            CentreActivityPreferenceID=preference.CentreActivityPreferenceID,
            PatientID=preference.PatientID,
            CentreActivityID=preference.CentreActivityID,
            IsLike=preference.IsLike,
            IsDeleted=preference.IsDeleted or "0",
            CreatedDateTime=preference.CreatedDateTime,
            UpdatedDateTime=preference.UpdatedDateTime,
            CreatedById=created_by,
            ModifiedById=created_by
        )
        
        db.add(new_preference)
        db.flush()
        return new_preference
    
    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity preference {preference.CentreActivityPreferenceID} (sync event)")
            result = create_operation()
            was_duplicate = False
            
            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ACTIVITY_PREFERENCE_CREATED",
                    aggregate_id=str(preference.CentreActivityPreferenceID),
                    processed_by=f"scheduler_service_{created_by}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ACTIVITY_PREFERENCE_CREATED",
                aggregate_id=str(preference.CentreActivityPreferenceID),
                processed_by=f"scheduler_service_{created_by}",
                operation=create_operation
            )
        
        if was_duplicate:
            existing_preference = db.query(RefActivityPreference).filter(
                RefActivityPreference.CentreActivityPreferenceID == preference.CentreActivityPreferenceID
            ).first()
            logger.info(f"Duplicate create event for activity preference {preference.CentreActivityPreferenceID}, returning existing")
            return existing_preference, True
        
        db.commit()
        logger.info(f"Successfully created activity preference {preference.CentreActivityPreferenceID}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating activity preference {preference.CentreActivityPreferenceID}: {str(e)}")
        raise

def update_ref_activity_preference(
    db: Session,
    preference_id: int,
    preference_update: RefActivityPreferenceUpdate,
    correlation_id: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityPreference], bool]:
    """
    Update an existing activity preference with idempotency protection.
    
    Args:
        db: Database session
        preference_id: CentreActivityPreferenceID of preference to update
        preference_update: Fields to update (includes UpdatedDateTime and ModifiedById)
        correlation_id: Correlation ID from outbox service for deduplication
        skip_duplicate_check: If True, bypass idempotency check (for sync events)
        
    Returns:
        Tuple of (RefActivityPreference or None, was_duplicate: bool)
        None if preference not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        db_preference = db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == preference_id,
            RefActivityPreference.IsDeleted == "0"
        ).first()
        
        if not db_preference:
            logger.warning(f"Activity preference {preference_id} not found for update")
            return None
        
        logger.debug(f"Updating activity preference {preference_id}")
        
        update_data = preference_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_preference, field) and field != 'CentreActivityPreferenceID':
                setattr(db_preference, field, value)
        
        db.flush()
        return db_preference
    
    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity preference {preference_id} (sync event)")
            result = update_operation()
            was_duplicate = False
            
            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ACTIVITY_PREFERENCE_UPDATED",
                    aggregate_id=str(preference_id),
                    processed_by=f"scheduler_service_{preference_update.ModifiedById}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ACTIVITY_PREFERENCE_UPDATED",
                aggregate_id=str(preference_id),
                processed_by=f"scheduler_service_{preference_update.ModifiedById}",
                operation=update_operation
            )
        
        if was_duplicate:
            existing_preference = db.query(RefActivityPreference).filter(
                RefActivityPreference.CentreActivityPreferenceID == preference_id,
                RefActivityPreference.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for activity preference {preference_id}, returning current state")
            return existing_preference, True
        
        if result is None:
            logger.warning(f"Activity preference {preference_id} not found for update")
            db.commit()
            return None, False
        
        db.commit()
        logger.debug(f"Successfully updated activity preference {preference_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating activity preference {preference_id}: {str(e)}")
        raise

def delete_ref_activity_preference(
    db: Session,
    preference_id: int,
    preference_delete: RefActivityPreferenceDelete,
    correlation_id: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityPreference], bool]:
    """
    Soft delete an activity preference with idempotency protection.
    
    Args:
        db: Database session
        preference_id: CentreActivityPreferenceID of preference to delete
        preference_delete: Delete data including timestamp and user info
        correlation_id: Correlation ID from outbox service for deduplication
        skip_duplicate_check: If True, bypass idempotency check (for sync events)
        
    Returns:
        Tuple of (RefActivityPreference or None, was_duplicate: bool)
        None if preference not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        db_preference = db.query(RefActivityPreference).filter(
            RefActivityPreference.CentreActivityPreferenceID == preference_id
        ).first()
        
        if not db_preference:
            logger.warning(f"Activity preference {preference_id} not found for deletion")
            return None
        
        if db_preference.IsDeleted == "1":
            logger.info(f"Activity preference {preference_id} already deleted")
            return db_preference
        
        logger.info(f"Soft deleting activity preference {preference_id}")
        
        db_preference.IsDeleted = "1"
        db_preference.ModifiedById = preference_delete.ModifiedById
        db_preference.UpdatedDateTime = preference_delete.UpdatedDateTime
        
        db.flush()
        return db_preference
    
    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity preference {preference_id} (sync event)")
            result = delete_operation()
            was_duplicate = False
            
            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ACTIVITY_PREFERENCE_DELETED",
                    aggregate_id=str(preference_id),
                    processed_by=f"scheduler_service_{preference_delete.ModifiedById}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ACTIVITY_PREFERENCE_DELETED",
                aggregate_id=str(preference_id),
                processed_by=f"scheduler_service_{preference_delete.ModifiedById}",
                operation=delete_operation
            )
        
        if was_duplicate:
            existing_preference = db.query(RefActivityPreference).filter(
                RefActivityPreference.CentreActivityPreferenceID == preference_id
            ).first()
            logger.info(f"Duplicate delete event for activity preference {preference_id}, returning current state")
            return existing_preference, True
        
        if result is None:
            logger.warning(f"Activity preference {preference_id} not found for deletion")
            db.commit()
            return None, False
        
        db.commit()
        logger.info(f"Successfully deleted activity preference {preference_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting activity preference {preference_id}: {str(e)}")
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
