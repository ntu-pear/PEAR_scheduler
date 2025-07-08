from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..models.ref_activity_model import RefActivity
from ..schemas.ref_activity import RefActivityCreate, RefActivityUpdate
from datetime import datetime
import math
from fastapi import HTTPException
from typing import Optional

def create_or_update_ref_activity(db: Session, activity: RefActivityCreate, user: str):
    """
    Idempotent create/update for message queue usage
    Creates if doesn't exist, updates if exists
    """
    current_time = datetime.utcnow()
    
    # Check if activity already exists
    existing_activity = db.query(RefActivity).filter(RefActivity.Id == activity.Id).first()
    
    if existing_activity:
        # Update existing activity
        for key, value in activity.model_dump(exclude={'Id'}).items():
            if hasattr(existing_activity, key):
                setattr(existing_activity, key, value)
        
        existing_activity.UpdatedDateTime = current_time
        existing_activity.ModifiedById = user
        
        db.commit()
        db.refresh(existing_activity)
        return existing_activity
    
    else:
        # Create new activity using MERGE for true upsert
        query = text("""
            MERGE [REF_ACTIVITY] AS target
            USING (VALUES (
                :Id, :ActivityTitle, :ActivityDesc, :StartDate, :EndDate, :IsDeleted,
                :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById
            )) AS source (
                Id, ActivityTitle, ActivityDesc, StartDate, EndDate, IsDeleted,
                CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById
            )
            ON target.Id = source.Id
            WHEN MATCHED THEN
                UPDATE SET 
                    ActivityTitle = source.ActivityTitle,
                    ActivityDesc = source.ActivityDesc,
                    StartDate = source.StartDate,
                    EndDate = source.EndDate,
                    UpdatedDateTime = source.UpdatedDateTime,
                    ModifiedById = source.ModifiedById,
                    IsDeleted = source.IsDeleted
            WHEN NOT MATCHED THEN
                INSERT (Id, ActivityTitle, ActivityDesc, StartDate, EndDate, IsDeleted,
                       CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById)
                VALUES (source.Id, source.ActivityTitle, source.ActivityDesc,
                       source.StartDate, source.EndDate, source.IsDeleted,
                       source.CreatedDateTime, source.UpdatedDateTime, source.CreatedById,
                       source.ModifiedById);
        """)
        
        params = {
            "Id": activity.Id,
            "ActivityTitle": activity.Title,
            "ActivityDesc": activity.Desc,
            "StartDate": activity.StartDate,
            "EndDate": activity.EndDate,
            "IsDeleted": activity.IsDeleted or "0",
            "CreatedDateTime": current_time,
            "UpdatedDateTime": current_time,
            "CreatedById": user,
            "ModifiedById": user,
        }
        
        db.execute(query, params)
        db.commit()
        
        # Return the created/updated activity
        return db.query(RefActivity).filter(RefActivity.Id == activity.Id).first()

def update_ref_activity_idempotent(db: Session, activity_id: int, activity: RefActivityUpdate, user: str):
    """
    Idempotent update - won't fail if activity doesn't exist
    """
    db_activity = db.query(RefActivity).filter(
        RefActivity.Id == activity_id, 
        RefActivity.IsDeleted == "0"
    ).first()
    
    if not db_activity:
        # Activity doesn't exist - this is OK for idempotent operations
        return None
    
    # Update fields
    for key, value in activity.model_dump(exclude_unset=True).items():
        if hasattr(db_activity, key):
            if key == "Title":
                setattr(db_activity, "ActivityTitle", value)
            elif key == "Desc":
                setattr(db_activity, "ActivityDesc", value)
            else:
                setattr(db_activity, key, value)
    
    db_activity.UpdatedDateTime = datetime.utcnow()
    db_activity.ModifiedById = user
    
    db.commit()
    db.refresh(db_activity)
    
    return db_activity

def soft_delete_ref_activity_idempotent(db: Session, activity_id: int, user_id: str):
    """
    Idempotent soft delete - won't fail if activity doesn't exist or already deleted
    """
    db_activity = db.query(RefActivity).filter(RefActivity.Id == activity_id).first()
    
    if not db_activity:
        # Activity doesn't exist - idempotent operation should succeed
        return None
    
    if db_activity.IsDeleted == "1":
        # Already deleted - idempotent operation should succeed
        return db_activity
    
    # Perform soft delete
    db_activity.IsDeleted = "1"
    db_activity.UpdatedDateTime = datetime.utcnow()
    db_activity.ModifiedById = user_id
    
    db.commit()
    db.refresh(db_activity)
    
    return db_activity

def get_ref_activities(db: Session, pageNo: int = 0, pageSize: int = 10, 
                      title: Optional[str] = None, start_date: Optional[datetime] = None):
    """Get activities with pagination and filtering"""
    offset = pageNo * pageSize
    query = db.query(RefActivity).filter(RefActivity.IsDeleted == "0")

    # Apply title filter if provided
    if title:
        query = query.filter(RefActivity.ActivityTitle.ilike(f"%{title}%"))

    # Apply start date filter if provided
    if start_date:
        query = query.filter(RefActivity.StartDate >= start_date)

    # Apply the same filters to count query
    count_query = db.query(func.count(RefActivity.Id)).filter(RefActivity.IsDeleted == "0")
    
    if title:
        count_query = count_query.filter(RefActivity.ActivityTitle.ilike(f"%{title}%"))
    if start_date:
        count_query = count_query.filter(RefActivity.StartDate >= start_date)
    
    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_activities = query.order_by(RefActivity.ActivityTitle.asc()).offset(offset).limit(pageSize).all()

    return db_activities, totalRecords, totalPages

def get_ref_activity_by_id(db: Session, activity_id: int):
    """Get activity by ID"""
    return db.query(RefActivity).filter(
        RefActivity.Id == activity_id,
        RefActivity.IsDeleted == "0"
    ).first()
