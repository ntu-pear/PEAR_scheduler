from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple, List
import logging
import math
from ..models.ref_activity_recommendation_model import RefActivityRecommendation
from ..models.processed_events_model import ProcessedEvent
from ..schemas.ref_activity_recommendation import RefActivityRecommendationCreate, RefActivityRecommendationUpdate, RefActivityRecommendationDelete
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

def create_ref_activity_recommendation(
    db: Session,
    recommendation: RefActivityRecommendationCreate,
    correlation_id: str,
    created_by: str
) -> Tuple[Optional[RefActivityRecommendation], bool]:
    """
    Create a new activity recommendation with idempotency protection.
    
    Args:
        db: Database session
        recommendation: Activity recommendation data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the recommendation
        
    Returns:
        Tuple of (RefActivityRecommendation or None, was_duplicate: bool)
        
    Raises:
        ValueError: If recommendation with same combination already exists (business logic error)
        Exception: For database or other errors
    """
    
    def create_operation():
        # Check if recommendation already exists - this is a business rule for CREATE
        # We use the CentreActivityRecommendationID from the activity service as unique identifier
        existing = db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == recommendation.CentreActivityRecommendationID
        ).first()
        
        if existing:
            if existing.IsDeleted == "1":
                # Reactivate soft-deleted recommendation
                logger.info(f"Reactivating soft-deleted recommendation {recommendation.CentreActivityRecommendationID}")
                existing.IsDeleted = "0"
                existing.PatientID = recommendation.PatientID
                existing.CentreActivityID = recommendation.CentreActivityID
                existing.DoctorID = recommendation.DoctorID
                existing.DoctorRecommendation = recommendation.DoctorRecommendation
                existing.DoctorRemarks = recommendation.DoctorRemarks
                existing.UpdatedDateTime = recommendation.UpdatedDateTime
                existing.ModifiedById = created_by
                db.flush()
                return existing
            else:
                raise ValueError(f"Activity recommendation with CentreActivityRecommendationID {recommendation.CentreActivityRecommendationID} already exists.")
        
        logger.info(f"Creating new activity recommendation {recommendation.CentreActivityRecommendationID}")
        
        # Create new recommendation
        new_recommendation = RefActivityRecommendation(
            CentreActivityRecommendationID=recommendation.CentreActivityRecommendationID,
            PatientID=recommendation.PatientID,
            CentreActivityID=recommendation.CentreActivityID,
            DoctorID=recommendation.DoctorID,
            DoctorRecommendation=recommendation.DoctorRecommendation,
            DoctorRemarks=recommendation.DoctorRemarks,
            IsDeleted=recommendation.IsDeleted or "0",
            CreatedDateTime=recommendation.CreatedDateTime,
            UpdatedDateTime=recommendation.UpdatedDateTime,
            CreatedById=created_by,
            ModifiedById=created_by
        )
        
        db.add(new_recommendation)
        db.flush()
        
        return new_recommendation
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_RECOMMENDATION_CREATED",
            aggregate_id=str(recommendation.CentreActivityRecommendationID),
            processed_by=f"scheduler_service_{created_by}",
            operation=create_operation
        )
        
        if was_duplicate:
            # Return existing recommendation for duplicate events
            existing_recommendation = db.query(RefActivityRecommendation).filter(
                RefActivityRecommendation.CentreActivityRecommendationID == recommendation.CentreActivityRecommendationID
            ).first()
            logger.info(f"Duplicate create event for activity recommendation {recommendation.CentreActivityRecommendationID}, returning existing")
            return existing_recommendation, True
        
        db.commit()
        logger.info(f"Successfully created activity recommendation {recommendation.CentreActivityRecommendationID}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating activity recommendation {recommendation.CentreActivityRecommendationID}: {str(e)}")
        raise

def update_ref_activity_recommendation(
    db: Session,
    recommendation_id: int,
    recommendation_update: RefActivityRecommendationUpdate,
    correlation_id: str
) -> Tuple[Optional[RefActivityRecommendation], bool]:
    """
    Update an existing activity recommendation with idempotency protection.
    
    Args:
        db: Database session
        recommendation_id: CentreActivityRecommendationID of recommendation to update
        recommendation_update: Fields to update (includes UpdatedDateTime and ModifiedById)
        correlation_id: Correlation ID from outbox service for deduplication
        
    Returns:
        Tuple of (RefActivityRecommendation or None, was_duplicate: bool)
        None if recommendation not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def update_operation():
        # Find the recommendation to update using CentreActivityRecommendationID
        db_recommendation = db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == recommendation_id,
            RefActivityRecommendation.IsDeleted == "0"
        ).first()
        
        if not db_recommendation:
            logger.warning(f"Activity recommendation {recommendation_id} not found for update")
            return None
        
        logger.debug(f"Updating activity recommendation {recommendation_id}")
        
        # Update only the fields that were provided
        update_data = recommendation_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_recommendation, field) and field != 'CentreActivityRecommendationID':  # Never update ID
                setattr(db_recommendation, field, value)
        
        db.flush()
        return db_recommendation
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_RECOMMENDATION_UPDATED",
            aggregate_id=str(recommendation_id),
            processed_by=f"scheduler_service_{recommendation_update.ModifiedById}",
            operation=update_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_recommendation = db.query(RefActivityRecommendation).filter(
                RefActivityRecommendation.CentreActivityRecommendationID == recommendation_id,
                RefActivityRecommendation.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for activity recommendation {recommendation_id}, returning current state")
            return existing_recommendation, True
        
        if result is None:
            logger.warning(f"Activity recommendation {recommendation_id} not found for update")
            db.commit()  # Commit the idempotency record even if recommendation not found
            return None, False
        
        db.commit()
        logger.debug(f"Successfully updated activity recommendation {recommendation_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating activity recommendation {recommendation_id}: {str(e)}")
        raise

def delete_ref_activity_recommendation(
    db: Session,
    recommendation_id: int,
    recommendation_delete: RefActivityRecommendationDelete,
    correlation_id: str
) -> Tuple[Optional[RefActivityRecommendation], bool]:
    """
    Soft delete an activity recommendation with idempotency protection.
    
    Args:
        db: Database session
        recommendation_id: CentreActivityRecommendationID of recommendation to delete
        recommendation_delete: Delete data including timestamp and user info
        correlation_id: Correlation ID from outbox service for deduplication
        
    Returns:
        Tuple of (RefActivityRecommendation or None, was_duplicate: bool)
        None if recommendation not found
        
    Raises:
        Exception: For database or other errors
    """
    
    def delete_operation():
        # Find the recommendation to delete using CentreActivityRecommendationID
        db_recommendation = db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.CentreActivityRecommendationID == recommendation_id
        ).first()
        
        if not db_recommendation:
            logger.warning(f"Activity recommendation {recommendation_id} not found for deletion")
            return None
        
        if db_recommendation.IsDeleted == "1":
            logger.info(f"Activity recommendation {recommendation_id} already deleted")
            return db_recommendation
        
        logger.info(f"Soft deleting activity recommendation {recommendation_id}")
        
        # Perform soft delete using schema data
        db_recommendation.IsDeleted = "1"
        db_recommendation.ModifiedById = recommendation_delete.ModifiedById
        db_recommendation.UpdatedDateTime = recommendation_delete.UpdatedDateTime
        
        db.flush()
        return db_recommendation
    
    # Use IdempotencyService for deduplication
    try:
        result, was_duplicate = IdempotencyService.process_idempotent(
            db=db,
            correlation_id=correlation_id,
            event_type="ACTIVITY_RECOMMENDATION_DELETED",
            aggregate_id=str(recommendation_id),
            processed_by=f"scheduler_service_{recommendation_delete.ModifiedById}",
            operation=delete_operation
        )
        
        if was_duplicate:
            # Return current state for duplicate events
            existing_recommendation = db.query(RefActivityRecommendation).filter(
                RefActivityRecommendation.CentreActivityRecommendationID == recommendation_id
            ).first()
            logger.info(f"Duplicate delete event for activity recommendation {recommendation_id}, returning current state")
            return existing_recommendation, True
        
        if result is None:
            logger.warning(f"Activity recommendation {recommendation_id} not found for deletion")
            db.commit()  # Commit the idempotency record even if recommendation not found
            return None, False
        
        db.commit()
        logger.info(f"Successfully deleted activity recommendation {recommendation_id}")
        return result, False
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting activity recommendation {recommendation_id}: {str(e)}")
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
