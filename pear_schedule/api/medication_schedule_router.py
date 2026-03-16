import logging
import traceback
import datetime
import pandas as pd
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pear_schedule.schemas.medication_schedule import MedicationScheduleUpdate
from pear_schedule.db_utils.writer import MedicationScheduleWrite
from pear_schedule.api.utils import MedicationAlreadyAdministeredException, MedicationScheduleNotFoundException

from pear_schedule.db_utils.views import TodayMedicationScheduleView
from pear_schedule.scheduler.medicationScheduling import medicationScheduler

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Medication Schedule"])

@router.get("/get/")
def get_medication_schedule(request: Request):
    try:
        medicationSchedules = medicationScheduler.generateTodayMedSchedule()
        if not MedicationScheduleWrite.write(schedules=medicationSchedules):
            raise HTTPException(status_code=500, detail="Failed to write medication schedules to the database")
        medication_schedules: pd.DataFrame = TodayMedicationScheduleView.get_data()
        return JSONResponse(status_code=200, content=jsonable_encoder(medication_schedules.to_dict(orient="records")))
    except Exception as e:
        logger.info(str(e))
        logger.info(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"An error occurred while fetching medication schedules: {str(e)}")

@router.put("/update/")
def update_medication_schedule(
    request: Request,
    medication_schedule: MedicationScheduleUpdate
):
    try:
        timestamp: datetime = MedicationScheduleWrite.update(medication_schedule)
        return {
            "message": "Medication schedule updated successfully",
            "timestamp": timestamp
        }
    except MedicationAlreadyAdministeredException:
        raise HTTPException(status_code=400, detail="Medication has already been administered. No further updates are allowed")
    except MedicationScheduleNotFoundException:
        raise HTTPException(status_code=404, detail="Medication schedule to be updated is not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error has occurred while updating medication schedule: {str(e)}")
