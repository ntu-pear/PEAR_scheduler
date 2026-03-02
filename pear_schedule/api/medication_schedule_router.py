import logging
import datetime
import pandas as pd
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pear_schedule.api.utils import MedicationScheduleUpdate

from pear_schedule.db_utils.views import ExistingMedicationScheduleView

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Medication Schedule"])

@router.get("/MedicationSchedule")
def getMedicationSchedule(request: Request):
    try:
        medication_schedules: pd.DataFrame = ExistingMedicationScheduleView.get_data(filter_by_date=True)
        return JSONResponse(status_code=200, content=jsonable_encoder(medication_schedules.to_dict(orient="records")))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while fetching medication schedules: {str(e)}")

@router.put("/MedicationSchedule/update/{medication_schedule_id}")
def updateMedicationSchedule(
    request: Request,
    medication_schedule_id: int,
    medication_schedule: MedicationScheduleUpdate
):
    # data can be accessed with the dot operator
    pass