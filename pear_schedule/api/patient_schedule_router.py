"""
One patient's saved schedule. The token is always checked with the user service.
Supervisors and admins see any patient, caregivers the patients allocated to them,
guardians their own patients (asked from patient service). Read-only.
"""

import datetime
import logging
import os
from typing import Optional, Set
from urllib.parse import quote

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from pear_schedule.api.auth_util import oauth2_scheme
from pear_schedule.api.token_verifier import Verdict, VerifiedUser, verify_token
from pear_schedule.db_utils.views import CaregiverAllocatedView, WeeklyScheduleView

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Scheduler"])

ANY_PATIENT = {"SUPERVISOR", "ADMIN"}
PATIENT_SERVICE_ENV = "PATIENT_SERVICE_URL"
REQUEST_TIMEOUT_SECONDS = 3.0
PAGE_SIZE = 100
MAX_PAGES = 20


def require_verified_user(token: str = Depends(oauth2_scheme)) -> VerifiedUser:
    try:
        verdict, user = verify_token(token)
    except Exception:
        logger.exception("Token check failed")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if verdict == Verdict.REJECTED:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if verdict != Verdict.VALID or user is None:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    return user


def caregiver_patients(user_id: str) -> Set[int]:
    """Patients this caregiver is allocated to, as caregiver or temp caregiver."""
    df = CaregiverAllocatedView.get_data()
    mine = (df["caregiverId"].astype(str) == user_id) | (df["tempCaregiverId"].astype(str) == user_id)
    return {int(p) for p in df.loc[mine, "patientId"]}


def guardian_patients(user_id: str, token: str) -> Set[int]:
    """Patients this guardian looks after, from patient service. Raises 503 if it can't tell."""
    base = os.getenv(PATIENT_SERVICE_ENV, "").rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="Patient service not configured")

    out: Set[int] = set()
    for page in range(MAX_PAGES):
        try:
            res = requests.get(
                f"{base}/api/v1/patients/by-guardian/{quote(user_id, safe='')}",
                params={"pageNo": page, "pageSize": PAGE_SIZE},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            res.raise_for_status()
            body = res.json()
            out.update(int(p["id"]) for p in body.get("data", []))
        except Exception:
            logger.exception("Guardian patient lookup failed")
            raise HTTPException(status_code=503, detail="Patient service unavailable")
        if page + 1 >= int(body.get("totalPages", 0)):
            break
    return out


def can_view(user: VerifiedUser, patient_id: int, token: str) -> bool:
    if user.roleName in ANY_PATIENT:
        return True
    if user.roleName == "CAREGIVER":
        return patient_id in caregiver_patients(user.userId)
    if user.roleName == "GUARDIAN":
        return patient_id in guardian_patients(user.userId, token)
    return False


@router.get("/{patient_id}/")
def get_patient_schedule(patient_id: int, date: Optional[datetime.date] = None,
                         token: str = Depends(oauth2_scheme)):
    user = require_verified_user(token)
    if not can_view(user, patient_id, token):
        raise HTTPException(status_code=403, detail="You can't view this patient's schedule")
    logger.info(f"Patient {patient_id} schedule opened by {user.userId} ({user.roleName})")

    # any day in the week to get, this week if not given
    at = datetime.datetime.combine(date, datetime.time(12)) if date else None
    try:
        df = WeeklyScheduleView.get_data(at=at, patient_id=patient_id)
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail="Could not read the schedule, check the scheduler logs")
    df.pop("ScheduleID")
    if len(df) == 0:
        return JSONResponse(jsonable_encoder({"Status": "404", "Message": "No schedule found", "Data": ""}))
    return JSONResponse(jsonable_encoder({
        "Status": "200",
        "Message": "Schedule retrieved successfully",
        "Data": df.to_dict(orient="records"),
    }))
