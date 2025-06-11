from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..models.ref_activity_recommendation_model import RefActivityRecommendation
from ..schemas.ref_activity_recommendation import RefActivityRecommendationCreate, RefActivityRecommendationUpdate
from datetime import datetime
import math
from fastapi import HTTPException
from typing import Optional

def create_or_update_ref_activity_recommendation(db: Session, recommendation: RefActivityRecommendationCreate, user: str):
    """
    Idempotent create/update for message queue usage
    Creates if doesn't exist, updates if exists
    """
    current_time = datetime.utcnow()
    
    # For recommendations, we'll check by PatientId, ActivityId, and DoctorId combination
    existing_recommendation = db.query(RefActivityRecommendation).filter(
        RefActivityRecommendation.PatientId == recommendation.PatientId,
        RefActivityRecommendation.ActivityId == recommendation.ActivityId,
        RefActivityRecommendation.DoctorId == recommendation.DoctorId,
        RefActivityRecommendation.IsDeleted == "0"
    ).first()
    
    if existing_recommendation:
        # Update existing recommendation
        for key, value in recommendation.model_dump(exclude={'PatientId', 'ActivityId', 'DoctorId'}).items():
            if hasattr(existing_recommendation, key):
                setattr(existing_recommendation, key, value)
        
        existing_recommendation.UpdatedDateTime = current_time
        existing_recommendation.ModifiedById = user
        
        db.commit()
        db.refresh(existing_recommendation)
        return existing_recommendation
    
    else:
        # Create new recommendation
        new_recommendation = RefActivityRecommendation(
            PatientId=recommendation.PatientId,
            ActivityId=recommendation.ActivityId,
            DoctorId=recommendation.DoctorId,
            DoctorRecommendation=recommendation.DoctorRecommendation,
            DoctorRemarks=recommendation.DoctorRemarks,
            IsDeleted=recommendation.IsDeleted or "0",
            CreatedDateTime=current_time,
            UpdatedDateTime=current_time,
            CreatedById=user,
            ModifiedById=user
        )
        
        db.add(new_recommendation)
        db.commit()
        db.refresh(new_recommendation)
        
        return new_recommendation

def update_ref_activity_recommendation_idempotent(db: Session, recommendation_id: int, recommendation: RefActivityRecommendationUpdate, user: str):
    """
    Idempotent update - won't fail if recommendation doesn't exist
    """
    db_recommendation = db.query(RefActivityRecommendation).filter(
        RefActivityRecommendation.Id == recommendation_id, 
        RefActivityRecommendation.IsDeleted == "0"
    ).first()
    
    if not db_recommendation:
        # Recommendation doesn't exist - this is OK for idempotent operations
        return None
    
    # Update fields
    for key, value in recommendation.model_dump(exclude_unset=True).items():
        if hasattr(db_recommendation, key):
            setattr(db_recommendation, key, value)
    
    db_recommendation.UpdatedDateTime = datetime.utcnow()
    db_recommendation.ModifiedById = user
    
    db.commit()
    db.refresh(db_recommendation)
    
    return db_recommendation

def soft_delete_ref_activity_recommendation_idempotent(db: Session, recommendation_id: int, user_id: str):
    """
    Idempotent soft delete - won't fail if recommendation doesn't exist or already deleted
    """
    db_recommendation = db.query(RefActivityRecommendation).filter(RefActivityRecommendation.Id == recommendation_id).first()
    
    if not db_recommendation:
        # Recommendation doesn't exist - idempotent operation should succeed
        return None
    
    if db_recommendation.IsDeleted == "1":
        # Already deleted - idempotent operation should succeed
        return db_recommendation
    
    # Perform soft delete
    db_recommendation.IsDeleted = "1"
    db_recommendation.UpdatedDateTime = datetime.utcnow()
    db_recommendation.ModifiedById = user_id
    
    db.commit()
    db.refresh(db_recommendation)
    
    return db_recommendation

def get_ref_activity_recommendations(db: Session, pageNo: int = 0, pageSize: int = 10, 
                                    patient_id: Optional[int] = None, activity_id: Optional[int] = None,
                                    doctor_id: Optional[str] = None, is_recommended: Optional[str] = None):
    """Get activity recommendations with pagination and filtering"""
    offset = pageNo * pageSize
    query = db.query(RefActivityRecommendation).filter(RefActivityRecommendation.IsDeleted == "0")

    # Apply patient filter if provided
    if patient_id:
        query = query.filter(RefActivityRecommendation.PatientId == patient_id)

    # Apply activity filter if provided
    if activity_id:
        query = query.filter(RefActivityRecommendation.ActivityId == activity_id)

    # Apply doctor filter if provided
    if doctor_id:
        query = query.filter(RefActivityRecommendation.DoctorId == doctor_id)

    # Apply is_recommended filter if provided
    if is_recommended in ["0", "1"]:
        query = query.filter(RefActivityRecommendation.DoctorRecommendation == is_recommended)

    # Apply the same filters to count query
    count_query = db.query(func.count(RefActivityRecommendation.Id)).filter(RefActivityRecommendation.IsDeleted == "0")
    
    if patient_id:
        count_query = count_query.filter(RefActivityRecommendation.PatientId == patient_id)
    if activity_id:
        count_query = count_query.filter(RefActivityRecommendation.ActivityId == activity_id)
    if doctor_id:
        count_query = count_query.filter(RefActivityRecommendation.DoctorId == doctor_id)
    if is_recommended in ["0", "1"]:
        count_query = count_query.filter(RefActivityRecommendation.DoctorRecommendation == is_recommended)
    
    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_recommendations = query.order_by(RefActivityRecommendation.PatientId.asc()).offset(offset).limit(pageSize).all()

    return db_recommendations, totalRecords, totalPages

def get_ref_activity_recommendation_by_id(db: Session, recommendation_id: int):
    """Get activity recommendation by ID"""
    return db.query(RefActivityRecommendation).filter(
        RefActivityRecommendation.Id == recommendation_id,
        RefActivityRecommendation.IsDeleted == "0"
    ).first()

def get_recommendations_by_patient_and_activity(db: Session, patient_id: int, activity_id: int):
    """Get recommendations for a specific patient and activity"""
    return db.query(RefActivityRecommendation).filter(
        RefActivityRecommendation.PatientId == patient_id,
        RefActivityRecommendation.ActivityId == activity_id,
        RefActivityRecommendation.IsDeleted == "0"
    ).all()

def get_doctor_recommendations_for_patient(db: Session, patient_id: int, doctor_id: str):
    """Get all recommendations by a doctor for a specific patient"""
    return db.query(RefActivityRecommendation).filter(
        RefActivityRecommendation.PatientId == patient_id,
        RefActivityRecommendation.DoctorId == doctor_id,
        RefActivityRecommendation.DoctorRecommendation == "1",
        RefActivityRecommendation.IsDeleted == "0"
    ).all()

def get_recommended_activities_for_patient(db: Session, patient_id: int):
    """Get all recommended activities for a patient"""
    return db.query(RefActivityRecommendation).filter(
        RefActivityRecommendation.PatientId == patient_id,
        RefActivityRecommendation.DoctorRecommendation == "1",
        RefActivityRecommendation.IsDeleted == "0"
    ).all()
