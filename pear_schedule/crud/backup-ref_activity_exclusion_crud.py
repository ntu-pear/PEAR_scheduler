import math
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from pear_schedule.services.idempotency_service import IdempotencyService

from ..models.ref_activity_exclusion_model import RefActivityExclusion
from ..schemas.ref_activity_exclusion import (
    RefActivityExclusionCreate,
    RefActivityExclusionUpdate,
)


def create_or_update_ref_activity_exclusion(
    db: Session, 
    exclusion: RefActivityExclusionCreate, 
    user: str):
    """
    Idempotent create/update for message queue usage
    Creates if doesn't exist, updates if exists
    """
    current_time = datetime.utcnow()
    
    # For exclusions, we'll check by PatientId and ActivityId combination
    # since there may not be a unique Id provided
    existing_exclusion = db.query(RefActivityExclusion).filter(
        RefActivityExclusion.PatientID == exclusion.PatientId,
        RefActivityExclusion.ActivityID == exclusion.ActivityId,
        RefActivityExclusion.IsDeleted == "0"
    ).first()
    
    if existing_exclusion:
        # Update existing exclusion
        for key, value in exclusion.model_dump(exclude={'PatientId', 'ActivityId'}).items():
            if hasattr(existing_exclusion, key):
                setattr(existing_exclusion, key, value)
        
        existing_exclusion.UpdatedDateTime = current_time
        existing_exclusion.ModifiedById = user
        
        db.commit()
        db.refresh(existing_exclusion)
        return existing_exclusion
    
    else:
        # Create new exclusion
        new_exclusion = RefActivityExclusion(
            PatientID=exclusion.PatientId,
            ActivityID=exclusion.ActivityId,
            StartDateTime=exclusion.StartDate,
            EndDateTime=exclusion.EndDate,
            ExclusionRemarks=exclusion.ExclusionRemarks,
            IsDeleted=exclusion.IsDeleted or "0",
            CreatedDateTime=current_time,
            UpdatedDateTime=current_time,
            CreatedById=user,
            ModifiedById=user
        )
        
        db.add(new_exclusion)
        db.commit()
        db.refresh(new_exclusion)
        
        return new_exclusion

def update_ref_activity_exclusion_idempotent(db: Session, exclusion_id: int, exclusion: RefActivityExclusionUpdate, user: str):
    """
    Idempotent update - won't fail if exclusion doesn't exist
    """
    db_exclusion = db.query(RefActivityExclusion).filter(
        RefActivityExclusion.Id == exclusion_id, 
        RefActivityExclusion.IsDeleted == "0"
    ).first()
    
    if not db_exclusion:
        # Exclusion doesn't exist - this is OK for idempotent operations
        return None
    
    # Update fields
    for key, value in exclusion.model_dump(exclude_unset=True).items():
        if hasattr(db_exclusion, key):
            setattr(db_exclusion, key, value)
    
    db_exclusion.UpdatedDateTime = datetime.utcnow()
    db_exclusion.ModifiedById = user
    
    db.commit()
    db.refresh(db_exclusion)
    
    return db_exclusion

def soft_delete_ref_activity_exclusion_idempotent(db: Session, exclusion_id: int, user_id: str):
    """
    Idempotent soft delete - won't fail if exclusion doesn't exist or already deleted
    """
    db_exclusion = db.query(RefActivityExclusion).filter(RefActivityExclusion.Id == exclusion_id).first()
    
    if not db_exclusion:
        # Exclusion doesn't exist - idempotent operation should succeed
        return None
    
    if db_exclusion.IsDeleted == "1":
        # Already deleted - idempotent operation should succeed
        return db_exclusion
    
    # Perform soft delete
    db_exclusion.IsDeleted = "1"
    db_exclusion.UpdatedDateTime = datetime.utcnow()
    db_exclusion.ModifiedById = user_id
    
    db.commit()
    db.refresh(db_exclusion)
    
    return db_exclusion

def get_ref_activity_exclusions(db: Session, pageNo: int = 0, pageSize: int = 10, 
                               patient_id: Optional[int] = None, activity_id: Optional[int] = None):
    """Get activity exclusions with pagination and filtering"""
    offset = pageNo * pageSize
    query = db.query(RefActivityExclusion).filter(RefActivityExclusion.IsDeleted == "0")

    # Apply patient filter if provided
    if patient_id:
        query = query.filter(RefActivityExclusion.PatientId == patient_id)

    # Apply activity filter if provided
    if activity_id:
        query = query.filter(RefActivityExclusion.ActivityId == activity_id)

    # Apply the same filters to count query
    count_query = db.query(func.count(RefActivityExclusion.Id)).filter(RefActivityExclusion.IsDeleted == "0")
    
    if patient_id:
        count_query = count_query.filter(RefActivityExclusion.PatientId == patient_id)
    if activity_id:
        count_query = count_query.filter(RefActivityExclusion.ActivityId == activity_id)
    
    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_exclusions = query.order_by(RefActivityExclusion.StartDate.asc()).offset(offset).limit(pageSize).all()

    return db_exclusions, totalRecords, totalPages

def get_ref_activity_exclusion_by_id(db: Session, exclusion_id: int):
    """Get activity exclusion by ID"""
    return db.query(RefActivityExclusion).filter(
        RefActivityExclusion.Id == exclusion_id,
        RefActivityExclusion.IsDeleted == "0"
    ).first()

def get_exclusions_by_patient_and_activity(db: Session, patient_id: int, activity_id: int):
    """Get exclusions for a specific patient and activity"""
    return db.query(RefActivityExclusion).filter(
        RefActivityExclusion.PatientId == patient_id,
        RefActivityExclusion.ActivityId == activity_id,
        RefActivityExclusion.IsDeleted == "0"
    ).all()

def get_idempotency_stats(db: Session) -> dict:
    """Get statistics about processed events for monitoring."""
    return IdempotencyService.get_processing_stats(db)


def cleanup_old_processed_events(db: Session, older_than_days: int = 30) -> int:
    """Clean up old processed events - should be run periodically."""
    return IdempotencyService.cleanup_old_events(db, older_than_days)


def is_event_already_processed(db: Session, correlation_id: str) -> bool:
    """Check if a specific correlation_id was already processed."""
    return IdempotencyService.is_already_processed(db, correlation_id)