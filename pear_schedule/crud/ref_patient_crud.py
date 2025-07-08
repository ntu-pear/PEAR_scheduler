from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..models.ref_patient_model import RefPatient
from ..schemas.ref_patient import RefPatientCreate, RefPatientUpdate
from datetime import datetime
import math
from fastapi import HTTPException, UploadFile
from typing import Optional

def create_or_update_ref_patient(db: Session, patient: RefPatientCreate, user: str):
    """
    Idempotent create/update for message queue usage
    Creates if doesn't exist, updates if exists
    """
    current_time = datetime.utcnow()
    
    # Check if patient already exists
    existing_patient = db.query(RefPatient).filter(RefPatient.Id == patient.Id).first()
    
    if existing_patient:
        # Update existing patient
        for key, value in patient.model_dump(exclude={'Id'}).items():
            if hasattr(existing_patient, key):
                setattr(existing_patient, key, value)
        
        existing_patient.UpdatedDateTime = current_time
        existing_patient.ModifiedById = user
        
        db.commit()
        db.refresh(existing_patient)
        return existing_patient
    
    else:
        # Create new patient using MERGE for true upsert
        query = text("""
            MERGE [REF_PATIENT] AS target
            USING (VALUES (
                :Id, :Name, :PreferredName, :UpdateBit, :StartDate, :EndDate, :IsActive,
                :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById, :IsDeleted
            )) AS source (
                Id, Name, PreferredName, UpdateBit, StartDate, EndDate, IsActive,
                CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById, IsDeleted
            )
            ON target.Id = source.Id
            WHEN MATCHED THEN
                UPDATE SET 
                    Name = source.Name,
                    PreferredName = source.PreferredName,
                    UpdateBit = source.UpdateBit,
                    StartDate = source.StartDate,
                    EndDate = source.EndDate,
                    IsActive = source.IsActive,
                    UpdatedDateTime = source.UpdatedDateTime,
                    ModifiedById = source.ModifiedById,
                    IsDeleted = source.IsDeleted
            WHEN NOT MATCHED THEN
                INSERT (Id, Name, PreferredName, UpdateBit, StartDate, EndDate, IsActive,
                       CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById, IsDeleted)
                VALUES (source.Id, source.Name, source.PreferredName, source.UpdateBit,
                       source.StartDate, source.EndDate, source.IsActive,
                       source.CreatedDateTime, source.UpdatedDateTime, source.CreatedById,
                       source.ModifiedById, source.IsDeleted);
        """)
        
        params = {
            "Id": patient.Id,
            "Name": patient.Name,
            "PreferredName": patient.PreferredName,
            "UpdateBit": patient.UpdateBit,
            "StartDate": patient.StartDate,
            "EndDate": patient.EndDate,
            "IsActive": patient.IsActive,
            "CreatedDateTime": current_time,
            "UpdatedDateTime": current_time,
            "CreatedById": user,
            "ModifiedById": user,
            "IsDeleted": patient.IsDeleted or "0",
        }
        
        db.execute(query, params)
        db.commit()
        
        # Return the created/updated patient
        return db.query(RefPatient).filter(RefPatient.Id == patient.Id).first()

def update_ref_patient_idempotent(db: Session, patient_id: str, patient: RefPatientUpdate, user: str):
    """
    Idempotent update - won't fail if patient doesn't exist
    """
    db_patient = db.query(RefPatient).filter(
        RefPatient.Id == patient_id, 
        RefPatient.IsDeleted == "0"
    ).first()
    
    if not db_patient:
        # Patient doesn't exist - this is OK for idempotent operations
        # TODO: log this or create the patient instead
        return None
    
    # Update fields
    for key, value in patient.model_dump(exclude_unset=True).items():
        if hasattr(db_patient, key):
            setattr(db_patient, key, value)
    
    db_patient.UpdatedDateTime = datetime.utcnow()
    db_patient.ModifiedById = user
    
    db.commit()
    db.refresh(db_patient)
    
    return db_patient

def soft_delete_ref_patient_idempotent(db: Session, patient_id: str, user_id: str):
    """
    Idempotent soft delete - won't fail if patient doesn't exist or already deleted
    """
    db_patient = db.query(RefPatient).filter(RefPatient.Id == patient_id).first()
    
    if not db_patient:
        # Patient doesn't exist - idempotent operation should succeed
        return None
    
    if db_patient.IsDeleted == "1":
        # Already deleted - idempotent operation should succeed
        return db_patient
    
    # Perform soft delete
    db_patient.IsDeleted = "1"
    db_patient.UpdatedDateTime = datetime.utcnow()
    db_patient.ModifiedById = user_id
    
    db.commit()
    db.refresh(db_patient)
    
    return db_patient

def get_ref_patients(db: Session, pageNo: int = 0, pageSize: int = 10, 
                    name: Optional[str] = None, isActive: Optional[str] = None):
    """Fixed variable name and filter logic"""
    offset = pageNo * pageSize
    query = db.query(RefPatient).filter(RefPatient.IsDeleted == "0")

    # Apply name filter if provided
    if name:
        query = query.filter(RefPatient.Name.ilike(f"%{name}%"))

    # Apply exact match for isActive
    if isActive in ["0", "1"]:
        query = query.filter(RefPatient.IsActive == isActive)

    # Apply the same filters to count query
    count_query = db.query(func.count(RefPatient.Id)).filter(RefPatient.IsDeleted == "0")
    
    if name:
        count_query = count_query.filter(RefPatient.Name.ilike(f"%{name}%"))
    if isActive in ["0", "1"]:
        count_query = count_query.filter(RefPatient.IsActive == isActive)
    
    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_patients = query.order_by(RefPatient.Name.asc()).offset(offset).limit(pageSize).all()

    return db_patients, totalRecords, totalPages
