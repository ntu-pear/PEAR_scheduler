"""
scheduler/scheduleUpdater.py - ScheduleRefresher.refresh_schedules.
"""

from unittest.mock import patch

from sqlalchemy import MetaData, Table, Column, Integer, String, create_engine, insert

from pear_schedule.scheduler.scheduleUpdater import ScheduleRefresher
from pear_schedule.utils import DBTABLES
from tests.utils.scheduler_config import make_scheduler_config

DB_TABLES = DBTABLES(
    ACTIVITY_TABLE="REF_ACTIVITY",
    ACTIVITY_EXCLUSION_TABLE="REF_ACTIVITY_EXCLUSION",
    CENTRE_ACTIVITY_TABLE="REF_CENTRE_ACTIVITY",
    CENTRE_ACTIVITY_PREFERENCE_TABLE="REF_ACTIVITY_PREFERENCE",
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE="REF_ACTIVITY_RECOMMENDATION",
    PATIENT_TABLE="REF_PATIENT",
    ROUTINE_TABLE="REF_ACTIVITY_ROUTINE",
    SCHEDULE_TABLE="SCHEDULE",
    MEDICATION_SCHEDULE_TABLE="MEDICATION_SCHEDULE",
    MEDICATION_TABLE="REF_PATIENT_MEDICATION",
    ALLOCATION_TABLE="REF_PATIENT_ALLOCATION",
    CARE_CENTRE_TABLE="REF_CARE_CENTRE",
    ADHOC_TABLE="REF_ADHOC",
)


def _make_patient_schema() -> MetaData:
    schema = MetaData()
    Table(
        "REF_PATIENT", schema,
        Column("PatientID", Integer, primary_key=True),
        Column("UpdateBit", String(1)),
        Column("IsDeleted", String(1)),
        Column("IsActive", String(1)),
    )
    return schema


class TestRefreshSchedules:
    def _config(self):
        return make_scheduler_config(DB_TABLES=DB_TABLES)

    def test_only_non_deleted_flagged_patients_passed_to_update_schedules(self, monkeypatch):
        import pear_schedule.scheduler.scheduleUpdater as scheduleUpdater

        monkeypatch.setattr(ScheduleRefresher, "config", self._config(), raising=False)
        schema = _make_patient_schema()
        monkeypatch.setattr(scheduleUpdater.DB, "schema", schema, raising=False)

        engine = create_engine("sqlite:///:memory:")
        schema.create_all(engine)
        patient_table = schema.tables["REF_PATIENT"]
        with engine.begin() as conn:
            conn.execute(insert(patient_table).values(PatientID=1, UpdateBit="1", IsDeleted="0", IsActive="1"))
            conn.execute(insert(patient_table).values(PatientID=2, UpdateBit="0", IsDeleted="0", IsActive="1"))
            conn.execute(insert(patient_table).values(PatientID=3, UpdateBit="1", IsDeleted="1", IsActive="1"))

        monkeypatch.setattr(scheduleUpdater.DB, "get_engine", lambda: engine, raising=False)

        with patch(
            "pear_schedule.scheduler.scheduleUpdater.PreferredActivityScheduler.update_schedules"
        ) as mock_update:
            ScheduleRefresher.refresh_schedules()

        mock_update.assert_called_once()
        called_patient_ids = list(mock_update.call_args[0][0])
        assert called_patient_ids == [1]

    def test_excludes_inactive_patients(self, monkeypatch):
        """Same idea as the IsDeleted test above, but for IsActive - used to be missing."""
        import pear_schedule.scheduler.scheduleUpdater as scheduleUpdater

        monkeypatch.setattr(ScheduleRefresher, "config", self._config(), raising=False)
        schema = _make_patient_schema()
        monkeypatch.setattr(scheduleUpdater.DB, "schema", schema, raising=False)

        engine = create_engine("sqlite:///:memory:")
        schema.create_all(engine)
        patient_table = schema.tables["REF_PATIENT"]
        with engine.begin() as conn:
            conn.execute(insert(patient_table).values(PatientID=1, UpdateBit="1", IsDeleted="0", IsActive="1"))
            conn.execute(insert(patient_table).values(PatientID=2, UpdateBit="1", IsDeleted="0", IsActive="0"))

        monkeypatch.setattr(scheduleUpdater.DB, "get_engine", lambda: engine, raising=False)

        with patch(
            "pear_schedule.scheduler.scheduleUpdater.PreferredActivityScheduler.update_schedules"
        ) as mock_update:
            ScheduleRefresher.refresh_schedules()

        mock_update.assert_called_once()
        assert list(mock_update.call_args[0][0]) == [1]

    def test_no_flagged_patients_still_calls_update_schedules_with_empty_series(self, monkeypatch):
        import pear_schedule.scheduler.scheduleUpdater as scheduleUpdater

        monkeypatch.setattr(ScheduleRefresher, "config", self._config(), raising=False)
        schema = _make_patient_schema()
        monkeypatch.setattr(scheduleUpdater.DB, "schema", schema, raising=False)

        engine = create_engine("sqlite:///:memory:")
        schema.create_all(engine)
        monkeypatch.setattr(scheduleUpdater.DB, "get_engine", lambda: engine, raising=False)

        with patch(
            "pear_schedule.scheduler.scheduleUpdater.PreferredActivityScheduler.update_schedules"
        ) as mock_update:
            ScheduleRefresher.refresh_schedules()

        mock_update.assert_called_once()
        assert list(mock_update.call_args[0][0]) == []
