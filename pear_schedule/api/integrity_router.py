from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from pear_schedule.database import get_db
from pear_schedule.models.ref_activity_exclusion_model import RefActivityExclusion
from pear_schedule.models.ref_activity_model import RefActivity
from pear_schedule.models.ref_activity_preference_model import RefActivityPreference
from pear_schedule.models.ref_activity_recommendation_model import (
    RefActivityRecommendation,
)
from pear_schedule.models.ref_centre_activity_model import RefCentreActivity
from pear_schedule.models.ref_patient_allocation_model import RefPatientAllocation
from pear_schedule.models.ref_patient_medication_model import RefPatientMedication
from pear_schedule.models.ref_patient_model import RefPatient

router = APIRouter(tags=["Integrity"])


@router.get("/ref-activity")
async def get_ref_activity_integrity(
    hours_back: int = Query(1, ge=1, le=168, description="Hours to look back"),
    limit: int = Query(1000, ge=1, le=5000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db)
):
    """
    Returns reference activity IDs and their last updated timestamps.
    This data should match the authoritative Activity Service.
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        ref_activities = db.query(RefActivity).filter(
            RefActivity.UpdatedDateTime >= cutoff_time
        ).order_by(RefActivity.ActivityID).limit(limit).offset(offset).all()
        
        records = []
        for activity in ref_activities:
            records.append({
                "ActivityID": activity.ActivityID,
                "modified_date": activity.UpdatedDateTime.isoformat(),
                "version_timestamp": int(activity.UpdatedDateTime.timestamp() * 1000),
                "record_type": "ref_activity"
            })
        
        total_count = db.query(RefActivity).filter(
            RefActivity.UpdatedDateTime >= cutoff_time
        ).count()
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/ref-activity",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "total_count": total_count,
            "returned_count": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(records)) < total_count,
            "records": records,
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref activity integrity check failed: {str(e)}")


@router.get("/ref-centre-activity")
async def get_ref_centre_activity_integrity(
    hours_back: int = Query(1, ge=1, le=168),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Returns reference centre activity IDs and timestamps.
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        ref_centre_activities = db.query(RefCentreActivity).filter(
            RefCentreActivity.UpdatedDateTime >= cutoff_time
        ).order_by(RefCentreActivity.CentreActivityID).limit(limit).offset(offset).all()
        
        records = []
        for centre_activity in ref_centre_activities:
            records.append({
                "CentreActivityID": centre_activity.CentreActivityID,
                "ActivityID": centre_activity.ActivityID,
                "modified_date": centre_activity.UpdatedDateTime.isoformat(),
                "version_timestamp": int(centre_activity.UpdatedDateTime.timestamp() * 1000),
                "record_type": "ref_centre_activity"
            })
        
        total_count = db.query(RefCentreActivity).filter(
            RefCentreActivity.UpdatedDateTime >= cutoff_time
        ).count()
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/ref-centre-activity",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "total_count": total_count,
            "returned_count": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(records)) < total_count,
            "records": records,
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref centre activity integrity check failed: {str(e)}")


@router.get("/ref-centre-activity-preference")
async def get_ref_centre_activity_preference_integrity(
    hours_back: int = Query(1, ge=1, le=168),
    patient_id: Optional[int] = Query(None, description="Filter by specific patient"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Returns reference centre activity preference IDs and timestamps.
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = db.query(RefActivityPreference).filter(
            RefActivityPreference.UpdatedDateTime >= cutoff_time
        )
        
        if patient_id:
            query = query.filter(RefActivityPreference.PatientID == patient_id)
        
        ref_preferences = query.order_by(
            RefActivityPreference.CentreActivityPreferenceID
        ).limit(limit).offset(offset).all()
        
        records = []
        for preference in ref_preferences:
            records.append({
                "CentreActivityPreferenceID": preference.CentreActivityPreferenceID,
                "CentreActivityID": preference.CentreActivityID,
                "PatientID": preference.PatientID,
                "modified_date": preference.UpdatedDateTime.isoformat(),
                "version_timestamp": int(preference.UpdatedDateTime.timestamp() * 1000),
                "record_type": "ref_centre_activity_preference"
            })
        
        count_query = db.query(RefActivityPreference).filter(
            RefActivityPreference.UpdatedDateTime >= cutoff_time
        )
        if patient_id:
            count_query = count_query.filter(RefActivityPreference.PatientID == patient_id)
        total_count = count_query.count()
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/ref-centre-activity-preference",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "patient_filter": patient_id,
            "total_count": total_count,
            "returned_count": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(records)) < total_count,
            "records": records,
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref centre activity preference integrity check failed: {str(e)}")


@router.get("/ref-centre-activity-recommendation")
async def get_ref_centre_activity_recommendation_integrity(
    hours_back: int = Query(1, ge=1, le=168),
    patient_id: Optional[int] = Query(None),
    doctor_id: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Returns reference centre activity recommendation IDs and timestamps.
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.UpdatedDateTime >= cutoff_time
        )
        
        if patient_id:
            query = query.filter(RefActivityRecommendation.PatientID == patient_id)
        if doctor_id:
            query = query.filter(RefActivityRecommendation.DoctorID == doctor_id)
        
        ref_recommendations = query.order_by(
            RefActivityRecommendation.CentreActivityRecommendationID
        ).limit(limit).offset(offset).all()
        
        records = []
        for recommendation in ref_recommendations:
            records.append({
                "CentreActivityRecommendationID": recommendation.CentreActivityRecommendationID,
                "CentreActivityID": recommendation.CentreActivityID,
                "PatientID": recommendation.PatientID,
                "DoctorID": recommendation.DoctorID,
                "modified_date": recommendation.UpdatedDateTime.isoformat(),
                "version_timestamp": int(recommendation.UpdatedDateTime.timestamp() * 1000),
                "record_type": "ref_centre_activity_recommendation"
            })
        
        count_query = db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.UpdatedDateTime >= cutoff_time
        )
        if patient_id:
            count_query = count_query.filter(RefActivityRecommendation.PatientID == patient_id)
        if doctor_id:
            count_query = count_query.filter(RefActivityRecommendation.DoctorID == doctor_id)
        total_count = count_query.count()
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/ref-centre-activity-recommendation",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "patient_filter": patient_id,
            "doctor_filter": doctor_id,
            "total_count": total_count,
            "returned_count": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(records)) < total_count,
            "records": records,
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref centre activity recommendation integrity check failed: {str(e)}")


@router.get("/ref-centre-activity-exclusion")
async def get_ref_centre_activity_exclusion_integrity(
    hours_back: int = Query(1, ge=1, le=168),
    patient_id: Optional[int] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Returns reference centre activity exclusion IDs and timestamps.
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = db.query(RefActivityExclusion).filter(
            RefActivityExclusion.UpdatedDateTime >= cutoff_time
        )
        
        if patient_id:
            query = query.filter(RefActivityExclusion.PatientID == patient_id)
        
        ref_exclusions = query.order_by(
            RefActivityExclusion.ActivityExclusionID
        ).limit(limit).offset(offset).all()
        
        records = []
        for exclusion in ref_exclusions:
            records.append({
                "ActivityExclusionID": exclusion.ActivityExclusionID,
                "CentreActivityID": exclusion.CentreActivityID,
                "PatientID": exclusion.PatientID,
                "modified_date": exclusion.UpdatedDateTime.isoformat(),
                "version_timestamp": int(exclusion.UpdatedDateTime.timestamp() * 1000),
                "record_type": "ref_centre_activity_exclusion"
            })
        
        count_query = db.query(RefActivityExclusion).filter(
            RefActivityExclusion.UpdatedDateTime >= cutoff_time
        )
        if patient_id:
            count_query = count_query.filter(RefActivityExclusion.PatientID == patient_id)
        total_count = count_query.count()
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/ref-centre-activity-exclusion",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "patient_filter": patient_id,
            "total_count": total_count,
            "returned_count": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(records)) < total_count,
            "records": records,
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref centre activity exclusion integrity check failed: {str(e)}")


@router.get("/ref-patient")
async def get_ref_patient_integrity(
    hours_back: int = Query(1, ge=1, le=168),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Returns reference patient IDs and timestamps.
    This data should match the authoritative Patient Service.
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        ref_patients = db.query(RefPatient).filter(
            RefPatient.UpdatedDateTime >= cutoff_time
        ).order_by(RefPatient.PatientID).limit(limit).offset(offset).all()
        
        records = []
        for patient in ref_patients:
            records.append({
                "PatientID": patient.PatientID,
                "modified_date": patient.UpdatedDateTime.isoformat(),
                "version_timestamp": int(patient.UpdatedDateTime.timestamp() * 1000),
                "record_type": "ref_patient"
            })
        
        total_count = db.query(RefPatient).filter(
            RefPatient.UpdatedDateTime >= cutoff_time
        ).count()
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/ref-patient",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "total_count": total_count,
            "returned_count": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(records)) < total_count,
            "records": records,
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref patient integrity check failed: {str(e)}")


@router.get("/ref-patient-medication")
async def get_ref_patient_medication_integrity(
    hours_back: int = Query(1, ge=1, le=168),
    patient_id: Optional[int] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Returns reference patient medication IDs and timestamps.
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = db.query(RefPatientMedication).filter(
            RefPatientMedication.UpdatedDateTime >= cutoff_time
        )
        
        if patient_id:
            query = query.filter(RefPatientMedication.PatientID == patient_id)
        
        ref_medications = query.order_by(
            RefPatientMedication.MedicationID
        ).limit(limit).offset(offset).all()
        
        records = []
        for medication in ref_medications:
            records.append({
                "MedicationID": medication.MedicationID,
                "PatientID": medication.PatientID,
                "modified_date": medication.UpdatedDateTime.isoformat(),
                "version_timestamp": int(medication.UpdatedDateTime.timestamp() * 1000),
                "record_type": "ref_patient_medication"
            })
        
        count_query = db.query(RefPatientMedication).filter(
            RefPatientMedication.UpdatedDateTime >= cutoff_time
        )
        if patient_id:
            count_query = count_query.filter(RefPatientMedication.PatientID == patient_id)
        total_count = count_query.count()
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/ref-patient-medication",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "patient_filter": patient_id,
            "total_count": total_count,
            "returned_count": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(records)) < total_count,
            "records": records,
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref medication integrity check failed: {str(e)}")

@router.get("/ref-patient-allocation")
async def get_ref_patient_allocation_integrity(
    hours_back: int = Query(1, ge=1, le=168),
    patient_id: Optional[int] = Query(None, description="Filter by specific patient"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Returns reference patient allocation IDs and timestamps.
    This data should match the authoritative Patient Service.
    """
    try:
        
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = db.query(RefPatientAllocation).filter(
            RefPatientAllocation.modified_date >= cutoff_time
        )
        
        if patient_id:
            query = query.filter(RefPatientAllocation.patientId == patient_id)
        
        ref_allocations = query.order_by(
            RefPatientAllocation.id
        ).limit(limit).offset(offset).all()
        
        records = []
        for allocation in ref_allocations:
            records.append({
                "PatientAllocationID": allocation.id,
                "PatientID": allocation.patientId,
                "modified_date": allocation.modified_date.isoformat(),
                "version_timestamp": int(allocation.modified_date.timestamp() * 1000),
                "record_type": "ref_patient_allocation"
            })
        
        count_query = db.query(RefPatientAllocation).filter(
            RefPatientAllocation.modified_date >= cutoff_time
        )
        if patient_id:
            count_query = count_query.filter(RefPatientAllocation.patientId == patient_id)
        total_count = count_query.count()
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/ref-patient-allocation",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "patient_filter": patient_id,
            "total_count": total_count,
            "returned_count": len(records),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(records)) < total_count,
            "records": records,
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref patient allocation integrity check failed: {str(e)}")

@router.get("/summary")
async def get_ref_integrity_summary(
    hours_back: int = Query(1, ge=1, le=168),
    db: Session = Depends(get_db)
):
    """
    Returns a summary of all reference record counts for the specified time window.
    Useful for high-level drift detection and monitoring.
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        # Count records in each reference table using SQLAlchemy models
        activity_count = db.query(RefActivity).filter(
            RefActivity.UpdatedDateTime >= cutoff_time
        ).count()
        
        centre_activity_count = db.query(RefCentreActivity).filter(
            RefCentreActivity.UpdatedDateTime >= cutoff_time
        ).count()
        
        preference_count = db.query(RefActivityPreference).filter(
            RefActivityPreference.UpdatedDateTime >= cutoff_time
        ).count()
        
        recommendation_count = db.query(RefActivityRecommendation).filter(
            RefActivityRecommendation.UpdatedDateTime >= cutoff_time
        ).count()
        
        exclusion_count = db.query(RefActivityExclusion).filter(
            RefActivityExclusion.UpdatedDateTime >= cutoff_time
        ).count()
        
        patient_count = db.query(RefPatient).filter(
            RefPatient.UpdatedDateTime >= cutoff_time
        ).count()
        
        medication_count = db.query(RefPatientMedication).filter(
            RefPatientMedication.UpdatedDateTime >= cutoff_time
        ).count()
        
        allocation_count = db.query(RefPatientAllocation).filter(
            RefPatientAllocation.modified_date >= cutoff_time
        ).count()
        
        total = (activity_count + centre_activity_count + preference_count + 
                recommendation_count + exclusion_count + patient_count + medication_count + allocation_count)
        
        return {
            "service": "scheduler",
            "endpoint": "/integrity/summary",
            "window_hours": hours_back,
            "cutoff_time": cutoff_time.isoformat(),
            "record_counts": {
                "ref_activity": activity_count,
                "ref_centre_activity": centre_activity_count,
                "ref_centre_activity_preference": preference_count,
                "ref_centre_activity_recommendation": recommendation_count,
                "ref_centre_activity_exclusion": exclusion_count,
                "ref_patient": patient_count,
                "ref_patient_medication": medication_count,
                "ref_patient_allocation": allocation_count,
                "total": total
            },
            "generated_at": datetime.now().isoformat(),
            "note": "eventual_consistent_copies"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ref integrity summary failed: {str(e)}")


@router.get("/health")
async def ref_integrity_health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint to verify ref integrity system is working.
    """
    try:
        # Test database connectivity by querying a simple count
        db.query(RefActivity).limit(1).first()
        
        # Check if we have recent reference data
        cutoff_time = datetime.now() - timedelta(hours=24)
        recent_activity = db.query(RefActivity).filter(
            RefActivity.UpdatedDateTime >= cutoff_time
        ).first()
        
        return {
            "status": "healthy",
            "service": "scheduler",
            "database_connected": True,
            "recent_ref_data_available": recent_activity is not None,
            "timestamp": datetime.now().isoformat(),
            "note": "eventual_consistent_service"
        }
        
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ref integrity health check failed: {str(e)}")


# ============================================================================
# FIELD MAPPING CONFIGURATION FOR DEPLOYMENT
# ============================================================================

"""
This configuration shows how the reconciler maps fields between services:

Activity Service (Authoritative) -> Scheduler Service (Eventual)
- id -> ActivityID
- modified_date -> UpdatedDateTime

Centre Activity:
- id -> CentreActivityID
- activity_id -> ActivityID
- modified_date -> UpdatedDateTime

Patient Service (Authoritative) -> Scheduler Service (Eventual)
- id -> PatientID
- modifiedDate -> UpdatedDateTime

Patient Medication:
- Id -> MedicationID
- PatientId -> PatientID
- UpdatedDateTime -> UpdatedDateTime (same field name)

The reconciler service handles these mappings automatically using the
FIELD_MAPPINGS configuration defined in reconciler_service.py
"""
