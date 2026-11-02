"""Patient medication updates from the patient service."""

import datetime
from unittest.mock import MagicMock

from messaging.mappers.mapper_util import map_patient_medication_create, map_patient_medication_update
from messaging.patient_medication_consumer import PatientMedicationConsumer
from pear_schedule.models.processed_events_model import MessageProcessingResult
from pear_schedule.schemas.ref_patient_medication import RefPatientMedicationCreate

ROW = {"Id": 5, "PatientId": 1, "PrescriptionName": "Aspirin", "AdministerTime": "0900", "Dosage": "1 tablet",
       "Instruction": "", "PrescriptionRemarks": "", "IsDeleted": False,
       "StartDate": "2026-10-01T00:00:00", "EndDate": "2026-12-31T00:00:00",
       "CreatedDateTime": "2026-10-01T00:00:00", "UpdatedDateTime": "2026-10-16T10:00:00", "ModifiedById": "u1"}


def _update(**new_data):
    consumer = PatientMedicationConsumer.__new__(PatientMedicationConsumer)
    consumer.map_patient_medication_update = map_patient_medication_update
    consumer.update_ref_patient_medication = MagicMock(return_value=(object(), False))
    message = {"correlation_id": "c1", "medication_id": 5, "patient_id": 1, "modified_by": "u1",
               "new_data": {**ROW, **new_data}}
    result = consumer._handle_patient_medication_updated(None, message)
    update = consumer.update_ref_patient_medication.call_args.kwargs["medication_update"]
    return result, update.model_dump(exclude_unset=True)


class TestMedicationDates:
    """Date changes used to be dropped: the update schema had StartDate/EndDate, the table has StartDateTime/EndDateTime."""

    def test_new_end_date_reaches_the_update(self):
        result, update = _update(EndDate="2026-10-20T00:00:00")
        assert result == MessageProcessingResult.SUCCESS
        assert update["EndDateTime"] == datetime.datetime(2026, 10, 20)
        assert update["StartDateTime"] == datetime.datetime(2026, 10, 1)

    def test_removed_end_date_clears_it(self):
        _, update = _update(EndDate=None)
        assert "EndDateTime" in update and update["EndDateTime"] is None

    def test_create_still_parses_the_dates(self):
        created = RefPatientMedicationCreate(**map_patient_medication_create(ROW))
        assert created.StartDateTime == datetime.datetime(2026, 10, 1)
        assert created.EndDateTime == datetime.datetime(2026, 12, 31)
