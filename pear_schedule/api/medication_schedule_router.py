import logging
import traceback
import datetime
import pandas as pd
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pear_schedule.schemas.medication_schedule import MedicationScheduleUpdate
from pear_schedule.db_utils.writer import MedicationScheduleWrite
from pear_schedule.api.utils import (
    MedicationAlreadyAdministeredException,
    MedicationScheduleNotFoundException,
    PatientServiceUnavailableException,
)
from pear_schedule.api.auth_util import JWTPayload, get_current_user, get_role_name, is_supervisor, oauth2_scheme
from pear_schedule.services.patientsvc_util import record_administration

from pear_schedule.db_utils.views import TodayMedicationScheduleView
from pear_schedule.scheduler.medicationScheduling import medicationScheduler

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Medication Schedule"])

DOSE_MARKER_ROLES = {"CAREGIVER", "SUPERVISOR"}


def require_supervisor(current_user: JWTPayload = Depends(get_current_user)) -> JWTPayload:
    if not is_supervisor(current_user):
        raise HTTPException(status_code=403, detail="Only supervisors can access the medication schedule")
    return current_user


@router.get("/get/", dependencies=[Depends(require_supervisor)])
def get_medication_schedule(request: Request):
    try:
        medicationSchedules = medicationScheduler.generateTodayMedSchedule()
        if not medicationSchedules: 
            return JSONResponse(status_code=200, content=jsonable_encoder({"message": "No medication schedules to be returned"}))
        if not MedicationScheduleWrite.write(schedules=medicationSchedules):
            raise HTTPException(status_code=500, detail="Failed to write medication schedules to the database")
        medication_schedules: pd.DataFrame = TodayMedicationScheduleView.get_data()
        return JSONResponse(status_code=200, content=jsonable_encoder(medication_schedules.to_dict(orient="records")))
    except Exception as e:
        logger.info(str(e))
        logger.info(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"An error occurred while fetching medication schedules: {str(e)}")

def require_dose_marker(current_user: JWTPayload = Depends(get_current_user)) -> JWTPayload:
    if get_role_name(current_user) not in DOSE_MARKER_ROLES:
        raise HTTPException(status_code=403, detail="Only caregivers and supervisors can mark a dose as given")
    return current_user


@router.put("/update/")
def update_medication_schedule(
    request: Request,
    medication_schedule: MedicationScheduleUpdate,
    current_user: JWTPayload = Depends(require_dose_marker),
    token: str = Depends(oauth2_scheme),
):
    # who gave the dose comes from the token, never the body
    medication_schedule = medication_schedule.model_copy(update={"AdministeredBy": current_user.userId})

    def record_in_patient(medication_id: int) -> None:
        if medication_schedule.Status == "1":
            record_administration(token, medication_id, medication_schedule.AdministerDate, medication_schedule.AdministerTime)

    try:
        timestamp: datetime = MedicationScheduleWrite.update(medication_schedule, before_commit=record_in_patient)
        return {
            "message": "Medication schedule updated successfully",
            "timestamp": timestamp
        }
    except MedicationAlreadyAdministeredException:
        raise HTTPException(status_code=400, detail="Medication has already been administered. No further updates are allowed")
    except MedicationScheduleNotFoundException:
        raise HTTPException(status_code=404, detail="Medication schedule to be updated is not found")
    except PatientServiceUnavailableException:
        raise HTTPException(status_code=503, detail="Could not record the dose in patient service. Nothing was changed; please try again")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error has occurred while updating medication schedule: {str(e)}")
