from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..models.ref_activity_preference_model import RefActivityPreference
from ..schemas.ref_activity_preference import RefActivityPreferenceCreate, RefActivityPreferenceUpdate
from datetime import datetime
import math
from fastapi import HTTPException
from typing import Optional

def create_or_update_ref_activity_preference(db: Session, preference: RefActivityPreferenceCreate, user: str):
    """
    Idempotent create/update for message queue usage
    Creates if doesn't exist, updates if exists
    """
    current_time = datetime.utcnow()
    
    # For preferences, we'll check by PatientId and ActivityId combination
    # since there may not be a unique Id provided
    existing_preference = db.query(RefActivityPreference).filter(
        RefActivityPreference.PatientId == preference.PatientId,
        RefActivityPreference.ActivityId == preference.ActivityId,
        RefActivityPreference.IsDeleted == "0"
    ).first()
    
    if existing_preference:
        # Update existing preference
        for key, value in preference.model_dump(exclude={'PatientId', 'ActivityId'}).items():
            if hasattr(existing_preference, key):
                setattr(existing_preference, key, value)
        
        existing_preference.UpdatedDateTime = current_time
        existing_preference.ModifiedById = user
        
        db.commit()
        db.refresh(existing_preference)
        return existing_preference
    
    else:
        # Create new preference
        new_preference = RefActivityPreference(
            PatientId=preference.PatientId,
            ActivityId=preference.ActivityId,
            IsLike=preference.IsLike,
            IsDeleted=preference.IsDeleted or "0",
            CreatedDateTime=current_time,
            UpdatedDateTime=current_time,
            CreatedById=user,
            ModifiedById=user
        )
        
        db.add(new_preference)
        db.commit()
        db.refresh(new_preference)
        
        return new_preference

def update_ref_activity_preference_idempotent(db: Session, preference_id: int, preference: RefActivityPreferenceUpdate, user: str):
    """
    Idempotent update - won't fail if preference doesn't exist
    """
    db_preference = db.query(RefActivityPreference).filter(
        RefActivityPreference.Id == preference_id, 
        RefActivityPreference.IsDeleted == "0"
    ).first()
    
    if not db_preference:
        # Preference doesn't exist - this is OK for idempotent operations
        return None
    
    # Update fields
    for key, value in preference.model_dump(exclude_unset=True).items():
        if hasattr(db_preference, key):
            setattr(db_preference, key, value)
    
    db_preference.UpdatedDateTime = datetime.utcnow()
    db_preference.ModifiedById = user
    
    db.commit()
    db.refresh(db_preference)
    
    return db_preference

def soft_delete_ref_activity_preference_idempotent(db: Session, preference_id: int, user_id: str):
    """
    Idempotent soft delete - won't fail if preference doesn't exist or already deleted
    """
    db_preference = db.query(RefActivityPreference).filter(RefActivityPreference.Id == preference_id).first()
    
    if not db_preference:
        # Preference doesn't exist - idempotent operation should succeed
        return None
    
    if db_preference.IsDeleted == "1":
        # Already deleted - idempotent operation should succeed
        return db_preference
    
    # Perform soft delete
    db_preference.IsDeleted = "1"
    db_preference.UpdatedDateTime = datetime.utcnow()
    db_preference.ModifiedById = user_id
    
    db.commit()
    db.refresh(db_preference)
    
    return db_preference

def get_ref_activity_preferences(db: Session, pageNo: int = 0, pageSize: int = 10, 
                                patient_id: Optional[int] = None, activity_id: Optional[int] = None, 
                                is_like: Optional[str] = None):
    """Get activity preferences with pagination and filtering"""
    offset = pageNo * pageSize
    query = db.query(RefActivityPreference).filter(RefActivityPreference.IsDeleted == "0")

    # Apply patient filter if provided
    if patient_id:
        query = query.filter(RefActivityPreference.PatientId == patient_id)

    # Apply activity filter if provided
    if activity_id:
        query = query.filter(RefActivityPreference.ActivityId == activity_id)

    # Apply is_like filter if provided
    if is_like in ["0", "1"]:
        query = query.filter(RefActivityPreference.IsLike == is_like)

    # Apply the same filters to count query
    count_query = db.query(func.count(RefActivityPreference.Id)).filter(RefActivityPreference.IsDeleted == "0")
    
    if patient_id:
        count_query = count_query.filter(RefActivityPreference.PatientId == patient_id)
    if activity_id:
        count_query = count_query.filter(RefActivityPreference.ActivityId == activity_id)
    if is_like in ["0", "1"]:
        count_query = count_query.filter(RefActivityPreference.IsLike == is_like)
    
    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_preferences = query.order_by(RefActivityPreference.PatientId.asc()).offset(offset).limit(pageSize).all()

    return db_preferences, totalRecords, totalPages

def get_ref_activity_preference_by_id(db: Session, preference_id: int):
    """Get activity preference by ID"""
    return db.query(RefActivityPreference).filter(
        RefActivityPreference.Id == preference_id,
        RefActivityPreference.IsDeleted == "0"
    ).first()

def get_preferences_by_patient_and_activity(db: Session, patient_id: int, activity_id: int):
    """Get preferences for a specific patient and activity"""
    return db.query(RefActivityPreference).filter(
        RefActivityPreference.PatientId == patient_id,
        RefActivityPreference.ActivityId == activity_id,
        RefActivityPreference.IsDeleted == "0"
    ).first()

def get_patient_liked_activities(db: Session, patient_id: int):
    """Get all activities liked by a patient"""
    return db.query(RefActivityPreference).filter(
        RefActivityPreference.PatientId == patient_id,
        RefActivityPreference.IsLike == "1",
        RefActivityPreference.IsDeleted == "0"
    ).all()

def get_patient_disliked_activities(db: Session, patient_id: int):
    """Get all activities disliked by a patient"""
    return db.query(RefActivityPreference).filter(
        RefActivityPreference.PatientId == patient_id,
        RefActivityPreference.IsLike == "0",
        RefActivityPreference.IsDeleted == "0"
    ).all()
