"""Calls to patient service on behalf of the signed-in user."""

import logging
import os

import requests

from pear_schedule.api.utils import PatientServiceUnavailableException

logger = logging.getLogger(__name__)

PATIENT_SERVICE_ENV = "PATIENT_SERVICE_URL"
REQUEST_TIMEOUT_SECONDS = 5.0


def record_administration(token: str, medication_id: int, administer_date, scheduled_time: str) -> None:
    """Records a given dose in patient service with the caller's token. Patient service is
    idempotent, so a repeat for the same slot is fine. Raises PatientServiceUnavailableException
    on a timeout, a connection error or any non-2xx answer."""
    base = os.getenv(PATIENT_SERVICE_ENV, "").rstrip("/")
    if not base:
        raise PatientServiceUnavailableException("Patient service not configured")
    try:
        res = requests.put(
            f"{base}/api/v1/Medication/administration",
            json={
                "MedicationId": int(medication_id),
                "AdministerDate": administer_date.isoformat(),
                "ScheduledTime": scheduled_time,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logger.warning(f"Patient service unreachable recording medication {medication_id}: {e}")
        raise PatientServiceUnavailableException(str(e)) from e
    if not 200 <= res.status_code < 300:
        logger.warning(f"Patient service answered {res.status_code} recording medication {medication_id}: {res.text[:300]}")
        raise PatientServiceUnavailableException(f"Patient service answered {res.status_code}")


def undo_administration(token: str, medication_id: int, administer_date, scheduled_time: str) -> None:
    """Undoes a given dose in patient service with the caller's token. Patient service treats an
    undo of a dose it has no record of as done, so a retry is fine. Raises
    PatientServiceUnavailableException on a timeout, a connection error or any non-2xx answer."""
    base = os.getenv(PATIENT_SERVICE_ENV, "").rstrip("/")
    if not base:
        raise PatientServiceUnavailableException("Patient service not configured")
    try:
        res = requests.delete(
            f"{base}/api/v1/Medication/administration",
            params={
                "medication_id": int(medication_id),
                "administer_date": administer_date.isoformat(),
                "scheduled_time": scheduled_time,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logger.warning(f"Patient service unreachable undoing medication {medication_id}: {e}")
        raise PatientServiceUnavailableException(str(e)) from e
    if not 200 <= res.status_code < 300:
        logger.warning(f"Patient service answered {res.status_code} undoing medication {medication_id}: {res.text[:300]}")
        raise PatientServiceUnavailableException(f"Patient service answered {res.status_code}")
