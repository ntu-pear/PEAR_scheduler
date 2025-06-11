from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..models.ref_activity_routine_model import RefActivityRoutine
from ..schemas.ref_activity_routine import RefActivityRoutineCreate, RefActivityRoutineUpdate
from datetime import datetime
import math
from fastapi import HTTPException
from typing import Optional

def create_or_update_ref_activity_routine(db: Session, routine: RefActivityRoutineCreate, user: str):
    """
    Idempotent create/update for message queue usage
    Creates if doesn't exist, updates if exists
    """
    current_time = datetime.utcnow()
    
    # For routines, we'll check by PatientId and ActivityId combination
    existing_routine = db.query(RefActivityRoutine).filter(
        RefActivityRoutine.PatientId == routine.PatientId,
        RefActivityRoutine.ActivityId == routine.ActivityId,
        RefActivityRoutine.IsDeleted == "0"
    ).first()
    
    if existing_routine:
        # Update existing routine
        for key, value in routine.model_dump(exclude={'PatientId', 'ActivityId'}).items():
            if hasattr(existing_routine, key):
                setattr(existing_routine, key, value)
        
        existing_routine.UpdatedDateTime = current_time
        existing_routine.ModifiedById = user
        
        db.commit()
        db.refresh(existing_routine)
        return existing_routine
    
    else:
        # Create new routine
        new_routine = RefActivityRoutine(
            PatientId=routine.PatientId,
            ActivityId=routine.ActivityId,
            IncludeInSchedule=routine.IncludeInSchedule,
            RoutineIssues=routine.RoutineIssues,
            RoutineTimeSlots=routine.RoutineTimeSlots,
            IsDeleted=routine.IsDeleted or "0",
            CreatedDateTime=current_time,
            UpdatedDateTime=current_time,
            CreatedById=user,
            ModifiedById=user
        )
        
        db.add(new_routine)
        db.commit()
        db.refresh(new_routine)
        
        return new_routine

def update_ref_activity_routine_idempotent(db: Session, routine_id: int, routine: RefActivityRoutineUpdate, user: str):
    """
    Idempotent update - won't fail if routine doesn't exist
    """
    db_routine = db.query(RefActivityRoutine).filter(
        RefActivityRoutine.Id == routine_id, 
        RefActivityRoutine.IsDeleted == "0"
    ).first()
    
    if not db_routine:
        # Routine doesn't exist - this is OK for idempotent operations
        return None
    
    # Update fields
    for key, value in routine.model_dump(exclude_unset=True).items():
        if hasattr(db_routine, key):
            setattr(db_routine, key, value)
    
    db_routine.UpdatedDateTime = datetime.utcnow()
    db_routine.ModifiedById = user
    
    db.commit()
    db.refresh(db_routine)
    
    return db_routine

def soft_delete_ref_activity_routine_idempotent(db: Session, routine_id: int, user_id: str):
    """
    Idempotent soft delete - won't fail if routine doesn't exist or already deleted
    """
    db_routine = db.query(RefActivityRoutine).filter(RefActivityRoutine.Id == routine_id).first()
    
    if not db_routine:
        # Routine doesn't exist - idempotent operation should succeed
        return None
    
    if db_routine.IsDeleted == "1":
        # Already deleted - idempotent operation should succeed
        return db_routine
    
    # Perform soft delete
    db_routine.IsDeleted = "1"
    db_routine.UpdatedDateTime = datetime.utcnow()
    db_routine.ModifiedById = user_id
    
    db.commit()
    db.refresh(db_routine)
    
    return db_routine

def get_ref_activity_routines(db: Session, pageNo: int = 0, pageSize: int = 10, 
                             patient_id: Optional[int] = None, activity_id: Optional[int] = None,
                             include_in_schedule: Optional[str] = None):
    """Get activity routines with pagination and filtering"""
    offset = pageNo * pageSize
    query = db.query(RefActivityRoutine).filter(RefActivityRoutine.IsDeleted == "0")

    # Apply patient filter if provided
    if patient_id:
        query = query.filter(RefActivityRoutine.PatientId == patient_id)

    # Apply activity filter if provided
    if activity_id:
        query = query.filter(RefActivityRoutine.ActivityId == activity_id)

    # Apply include_in_schedule filter if provided
    if include_in_schedule in ["0", "1"]:
        query = query.filter(RefActivityRoutine.IncludeInSchedule == include_in_schedule)

    # Apply the same filters to count query
    count_query = db.query(func.count(RefActivityRoutine.Id)).filter(RefActivityRoutine.IsDeleted == "0")
    
    if patient_id:
        count_query = count_query.filter(RefActivityRoutine.PatientId == patient_id)
    if activity_id:
        count_query = count_query.filter(RefActivityRoutine.ActivityId == activity_id)
    if include_in_schedule in ["0", "1"]:
        count_query = count_query.filter(RefActivityRoutine.IncludeInSchedule == include_in_schedule)
    
    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_routines = query.order_by(RefActivityRoutine.PatientId.asc()).offset(offset).limit(pageSize).all()

    return db_routines, totalRecords, totalPages

def get_ref_activity_routine_by_id(db: Session, routine_id: int):
    """Get activity routine by ID"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.Id == routine_id,
        RefActivityRoutine.IsDeleted == "0"
    ).first()

def get_routine_by_patient_and_activity(db: Session, patient_id: int, activity_id: int):
    """Get routine for a specific patient and activity"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.PatientId == patient_id,
        RefActivityRoutine.ActivityId == activity_id,
        RefActivityRoutine.IsDeleted == "0"
    ).first()

def get_patient_scheduled_routines(db: Session, patient_id: int):
    """Get all routines included in schedule for a patient"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.PatientId == patient_id,
        RefActivityRoutine.IncludeInSchedule == "1",
        RefActivityRoutine.IsDeleted == "0"
    ).all()

def get_patient_excluded_routines(db: Session, patient_id: int):
    """Get all routines excluded from schedule for a patient"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.PatientId == patient_id,
        RefActivityRoutine.IncludeInSchedule == "0",
        RefActivityRoutine.IsDeleted == "0"
    ).all()

def get_activity_routines_by_time_slot(db: Session, time_slot: str):
    """Get all routines for a specific time slot"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.RoutineTimeSlots.ilike(f"%{time_slot}%"),
        RefActivityRoutine.IncludeInSchedule == "1",
        RefActivityRoutine.IsDeleted == "0"
    ).all()
