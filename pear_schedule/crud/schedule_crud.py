from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..models.schedule_model import Schedule
from ..schemas.schedule import ScheduleCreate, ScheduleUpdate
from datetime import datetime, timedelta
from ..logger.logger_utils import log_crud_action, ActionType, serialize_data
import math
from fastapi import HTTPException
from typing import Optional

def get_schedule(db: Session, schedule_id: int):
    """Get a single schedule by ID"""
    db_schedule = (
        db.query(Schedule)
        .filter(Schedule.Id == schedule_id, Schedule.IsDeleted == "0")
        .first()
    )
    return db_schedule

def get_schedules(db: Session, pageNo: int = 0, pageSize: int = 10, 
                 patient_id: Optional[int] = None, start_date: Optional[datetime] = None,
                 end_date: Optional[datetime] = None):
    """Get schedules with pagination and filtering"""
    offset = pageNo * pageSize
    query = db.query(Schedule).filter(Schedule.IsDeleted == "0")

    # Apply patient filter if provided
    if patient_id:
        query = query.filter(Schedule.PatientId == patient_id)

    # Apply date range filters if provided
    if start_date:
        query = query.filter(Schedule.EndDate >= start_date)
    
    if end_date:
        query = query.filter(Schedule.StartDate <= end_date)

    # Apply the same filters to count query
    count_query = db.query(func.count()).select_from(Schedule).filter(Schedule.IsDeleted == "0")
    
    if patient_id:
        count_query = count_query.filter(Schedule.PatientId == patient_id)
    if start_date:
        count_query = count_query.filter(Schedule.EndDate >= start_date)
    if end_date:
        count_query = count_query.filter(Schedule.StartDate <= end_date)
    
    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_schedules = query.order_by(Schedule.StartDate.desc()).offset(offset).limit(pageSize).all()

    return db_schedules, totalRecords, totalPages

def create_schedule(db: Session, schedule: ScheduleCreate, user: str, user_full_name: str):
    """Create a new schedule"""
    
    # Check for overlapping schedules for the same patient
    existing_schedule = (
        db.query(Schedule)
        .filter(
            Schedule.PatientId == schedule.PatientId,
            Schedule.StartDate <= schedule.EndDate,
            Schedule.EndDate >= schedule.StartDate,
            Schedule.IsDeleted == "0"
        )
        .first()
    )
    if existing_schedule:
        raise HTTPException(
            status_code=400, 
            detail="Schedule overlaps with existing schedule for this patient"
        )

    query = text("""
        INSERT INTO [SCHEDULE] (
            [PatientId], [StartDate], [EndDate], [Monday], [Tuesday], [Wednesday], 
            [Thursday], [Friday], [Saturday], [Sunday], [CreatedDateTime], 
            [UpdatedDateTime], [CreatedById], [ModifiedById], [IsDeleted]
        ) VALUES (
            :PatientId, :StartDate, :EndDate, :Monday, :Tuesday, :Wednesday, 
            :Thursday, :Friday, :Saturday, :Sunday, :CreatedDateTime, 
            :UpdatedDateTime, :CreatedById, :ModifiedById, :IsDeleted
        );
    """)

    params = {
        "PatientId": schedule.PatientId,
        "StartDate": schedule.StartDate,
        "EndDate": schedule.EndDate,
        "Monday": schedule.Monday,
        "Tuesday": schedule.Tuesday,
        "Wednesday": schedule.Wednesday,
        "Thursday": schedule.Thursday,
        "Friday": schedule.Friday,
        "Saturday": schedule.Saturday,
        "Sunday": schedule.Sunday,
        "CreatedDateTime": datetime.now(),
        "UpdatedDateTime": datetime.now(),
        "CreatedById": user,
        "ModifiedById": user,
        "IsDeleted": schedule.IsDeleted or "0",
    }

    db.execute(query, params)
    db.commit()

    # Retrieve the newly inserted schedule
    new_schedule = (
        db.query(Schedule)
        .filter(
            Schedule.PatientId == schedule.PatientId,
            Schedule.StartDate == schedule.StartDate,
            Schedule.EndDate == schedule.EndDate
        )
        .order_by(Schedule.Id.desc())
        .first()
    )

    try:
        schedule_data_dict = {
            k: serialize_data(v)
            for k, v in new_schedule.__dict__.items()
            if not k.startswith("_")
        }
    except Exception:
        schedule_data_dict = "{}"

    log_crud_action(
        action=ActionType.CREATE,
        user=user,
        user_full_name=user_full_name,
        message="Created Schedule",
        table="Schedule",
        entity_id=new_schedule.Id,
        original_data=None,
        updated_data=schedule_data_dict,
    )

    return new_schedule

def update_schedule(db: Session, schedule_id: int, schedule: ScheduleUpdate, user: str, user_full_name: str):
    """Update an existing schedule"""
    db_schedule = db.query(Schedule).filter(Schedule.Id == schedule_id, Schedule.IsDeleted == "0").first()
    if not db_schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    try:
        original_data_dict = {
            k: serialize_data(v)
            for k, v in db_schedule.__dict__.items()
            if not k.startswith("_")
        }
    except Exception:
        original_data_dict = "{}"

    # Check for overlapping schedules for the same patient (excluding current schedule)
    existing_schedule = (
        db.query(Schedule)
        .filter(
            Schedule.Id != schedule_id,
            Schedule.PatientId == schedule.PatientId,
            Schedule.StartDate <= schedule.EndDate,
            Schedule.EndDate >= schedule.StartDate,
            Schedule.IsDeleted == "0"
        )
        .first()
    )
    if existing_schedule:
        raise HTTPException(
            status_code=400, 
            detail="Schedule overlaps with existing schedule for this patient"
        )

    # Update fields
    for key, value in schedule.model_dump().items():
        setattr(db_schedule, key, value)
    
    db_schedule.UpdatedDateTime = datetime.now()
    db_schedule.ModifiedById = user

    db.commit()
    db.refresh(db_schedule)

    updated_data_dict = serialize_data(schedule.model_dump())
    log_crud_action(
        action=ActionType.UPDATE,
        user=user,
        user_full_name=user_full_name,
        message="Updated Schedule",
        table="Schedule",
        entity_id=db_schedule.Id,
        original_data=original_data_dict,
        updated_data=updated_data_dict,
    )

    return db_schedule

def delete_schedule(db: Session, schedule_id: int, user_id: str, user_full_name: str):
    """Soft delete a schedule"""
    db_schedule = db.query(Schedule).filter(Schedule.Id == schedule_id).first()
    if not db_schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    try:
        original_data_dict = {
            k: serialize_data(v)
            for k, v in db_schedule.__dict__.items()
            if not k.startswith("_")
        }
    except Exception:
        original_data_dict = "{}"

    setattr(db_schedule, "IsDeleted", "1")
    db_schedule.UpdatedDateTime = datetime.now()
    db_schedule.ModifiedById = user_id
    db.commit()

    log_crud_action(
        action=ActionType.DELETE,
        user=user_id,
        user_full_name=user_full_name,
        message="Deleted Schedule",
        table="Schedule",
        entity_id=db_schedule.Id,
        original_data=original_data_dict,
        updated_data=None,
    )

    return db_schedule
