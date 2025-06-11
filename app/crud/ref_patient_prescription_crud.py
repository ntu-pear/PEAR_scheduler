from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..models.ref_patient_prescription_model import RefPatientPrescription
from ..schemas.ref_patient_prescription import RefPatientPrescriptionCreate, RefPatientPrescriptionUpdate
from datetime import datetime, timedelta
import math
from fastapi import HTTPException
from typing import Optional

def create_or_update_ref_patient_prescription(db: Session, prescription: RefPatientPrescriptionCreate, user: str, user_full_name: str):
    """
    Idempotent create/update for message queue usage
    Creates if doesn't exist, updates if exists
    """
    current_time = datetime.utcnow()
    
    # Check if prescription already exists by ID if provided
    existing_prescription = None
    if hasattr(prescription, 'Id') and prescription.Id:
        existing_prescription = db.query(RefPatientPrescription).filter(RefPatientPrescription.Id == prescription.Id).first()
    
    if existing_prescription:
        # Update existing prescription
        for key, value in prescription.model_dump(exclude={'Id'}).items():
            if hasattr(existing_prescription, key):
                setattr(existing_prescription, key, value)
        
        existing_prescription.UpdatedDateTime = current_time
        existing_prescription.ModifiedById = user
        
        db.commit()
        db.refresh(existing_prescription)
        return existing_prescription
    
    else:
        # Create new prescription
        new_prescription = RefPatientPrescription(
            PatientId=prescription.PatientId,
            PrescriptionListValue=prescription.PrescriptionListValue,
            Dosage=prescription.Dosage,
            FrequencyPerDay=prescription.FrequencyPerDay,
            Instruction=prescription.Instruction,
            StartDate=prescription.StartDate,
            EndDate=prescription.EndDate,
            IsAfterMeal=prescription.IsAfterMeal,
            PrescriptionRemarks=prescription.PrescriptionRemarks,
            Status=prescription.Status,
            IsDeleted=prescription.IsDeleted or "0",
            CreatedDateTime=current_time,
            UpdatedDateTime=current_time,
            CreatedById=user,
            ModifiedById=user
        )
        
        db.add(new_prescription)
        db.commit()
        db.refresh(new_prescription)
        
        return new_prescription

def update_ref_patient_prescription_idempotent(db: Session, prescription_id: int, prescription: RefPatientPrescriptionUpdate, user: str):
    """
    Idempotent update - won't fail if prescription doesn't exist
    """
    db_prescription = db.query(RefPatientPrescription).filter(
        RefPatientPrescription.Id == prescription_id, 
        RefPatientPrescription.IsDeleted == "0"
    ).first()
    
    if not db_prescription:
        # Prescription doesn't exist - this is OK for idempotent operations
        return None
    
    # Update fields
    for key, value in prescription.model_dump(exclude_unset=True).items():
        if hasattr(db_prescription, key):
            setattr(db_prescription, key, value)
    
    db_prescription.UpdatedDateTime = datetime.utcnow()
    db_prescription.ModifiedById = user
    
    db.commit()
    db.refresh(db_prescription)
    
    return db_prescription

def soft_delete_ref_patient_prescription_idempotent(db: Session, prescription_id: int, user_id: str):
    """
    Idempotent soft delete - won't fail if prescription doesn't exist or already deleted
    """
    db_prescription = db.query(RefPatientPrescription).filter(RefPatientPrescription.Id == prescription_id).first()
    
    if not db_prescription:
        # Prescription doesn't exist - idempotent operation should succeed
        return None
    
    if db_prescription.IsDeleted == "1":
        # Already deleted - idempotent operation should succeed
        return db_prescription
    
    # Perform soft delete
    db_prescription.IsDeleted = "1"
    db_prescription.UpdatedDateTime = datetime.utcnow()
    db_prescription.ModifiedById = user_id
    
    db.commit()
    db.refresh(db_prescription)
    
    return db_prescription

def get_ref_patient_prescriptions(db: Session, pageNo: int = 0, pageSize: int = 10, 
                                 patient_id: Optional[int] = None, status: Optional[str] = None,
                                 prescription_value: Optional[str] = None, is_active: Optional[bool] = None):
    """Get patient prescriptions with pagination and filtering"""
    offset = pageNo * pageSize
    query = db.query(RefPatientPrescription).filter(RefPatientPrescription.IsDeleted == "0")

    # Apply patient filter if provided
    if patient_id:
        query = query.filter(RefPatientPrescription.PatientId == patient_id)

    # Apply status filter if provided
    if status:
        query = query.filter(RefPatientPrescription.Status == status)

    # Apply prescription value filter if provided
    if prescription_value:
        query = query.filter(RefPatientPrescription.PrescriptionListValue.ilike(f"%{prescription_value}%"))

    # Apply active filter (prescriptions that haven't ended or have no end date)
    if is_active is not None:
        current_date = datetime.utcnow()
        if is_active:
            query = query.filter(
                (RefPatientPrescription.EndDate.is_(None)) | 
                (RefPatientPrescription.EndDate >= current_date)
            )
        else:
            query = query.filter(
                (RefPatientPrescription.EndDate.is_not(None)) & 
                (RefPatientPrescription.EndDate < current_date)
            )

    # Apply the same filters to count query
    count_query = db.query(func.count(RefPatientPrescription.Id)).filter(RefPatientPrescription.IsDeleted == "0")
    
    if patient_id:
        count_query = count_query.filter(RefPatientPrescription.PatientId == patient_id)
    if status:
        count_query = count_query.filter(RefPatientPrescription.Status == status)
    if prescription_value:
        count_query = count_query.filter(RefPatientPrescription.PrescriptionListValue.ilike(f"%{prescription_value}%"))
    if is_active is not None:
        current_date = datetime.utcnow()
        if is_active:
            count_query = count_query.filter(
                (RefPatientPrescription.EndDate.is_(None)) | 
                (RefPatientPrescription.EndDate >= current_date)
            )
        else:
            count_query = count_query.filter(
                (RefPatientPrescription.EndDate.is_not(None)) & 
                (RefPatientPrescription.EndDate < current_date)
            )
    
    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_prescriptions = query.order_by(RefPatientPrescription.StartDate.desc()).offset(offset).limit(pageSize).all()

    return db_prescriptions, totalRecords, totalPages

def get_ref_patient_prescription_by_id(db: Session, prescription_id: int):
    """Get patient prescription by ID"""
    return db.query(RefPatientPrescription).filter(
        RefPatientPrescription.Id == prescription_id,
        RefPatientPrescription.IsDeleted == "0"
    ).first()

def get_patient_active_prescriptions(db: Session, patient_id: int):
    """Get all active prescriptions for a patient"""
    current_date = datetime.utcnow()
    return db.query(RefPatientPrescription).filter(
        RefPatientPrescription.PatientId == patient_id,
        RefPatientPrescription.StartDate <= current_date,
        (RefPatientPrescription.EndDate.is_(None)) | (RefPatientPrescription.EndDate >= current_date),
        RefPatientPrescription.IsDeleted == "0"
    ).all()

def get_patient_prescriptions_by_status(db: Session, patient_id: int, status: str):
    """Get patient prescriptions by status"""
    return db.query(RefPatientPrescription).filter(
        RefPatientPrescription.PatientId == patient_id,
        RefPatientPrescription.Status == status,
        RefPatientPrescription.IsDeleted == "0"
    ).all()

def get_prescriptions_ending_soon(db: Session, days: int = 7):
    """Get prescriptions ending within specified days"""
    end_date = datetime.utcnow() + timedelta(days=days)
    current_date = datetime.utcnow()
    
    return db.query(RefPatientPrescription).filter(
        RefPatientPrescription.EndDate.is_not(None),
        RefPatientPrescription.EndDate >= current_date,
        RefPatientPrescription.EndDate <= end_date,
        RefPatientPrescription.IsDeleted == "0"
    ).all()

def get_patient_medication_schedule(db: Session, patient_id: int, is_after_meal: Optional[str] = None):
    """Get patient's medication schedule"""
    query = db.query(RefPatientPrescription).filter(
        RefPatientPrescription.PatientId == patient_id,
        RefPatientPrescription.IsDeleted == "0"
    )
    
    if is_after_meal in ["0", "1"]:
        query = query.filter(RefPatientPrescription.IsAfterMeal == is_after_meal)
    
    return query.order_by(RefPatientPrescription.FrequencyPerDay.desc()).all()
