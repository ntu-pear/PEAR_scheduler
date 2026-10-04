"""
MedicationScheduleWrite's flush step (daily MEDICATION_SCHEDULE table). DB is mocked.
"""

import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
from sqlalchemy.dialects import mssql
from sqlalchemy.sql.dml import Delete

from pear_schedule.db_utils import writer as writer_module
from pear_schedule.db_utils.writer import (
    MedicationScheduleWrite,
    _expired_medication_rows,
    _group_medication_log,
)

TODAY = datetime.date(2026, 10, 7)  # Wednesday
DATE_FORMAT = "%Y-%m-%d"


def _row(med_id, date, time="0900", status="0", given_at=None, given_by=None, schedule_id=5):
    return {
        "MedicationID": med_id,
        "ScheduleID": schedule_id,
        "AdministerDate": date,
        "AdministerTime": time,
        "AssignedTo": "cg1",
        "Status": status,
        "ActualAdministerTime": given_at,
        "AdministeredBy": given_by,
    }


def _rows(*rows):
    df = pd.DataFrame(list(rows))
    # like read_sql: datetime column only when some dose has been given, else plain None
    if df["ActualAdministerTime"].notna().any():
        df["ActualAdministerTime"] = pd.to_datetime(df["ActualAdministerTime"])
    return df


class TestExpiredMedicationRows:
    def test_keeps_only_rows_before_today(self):
        df = _rows(_row(1, "2026-10-05"), _row(2, "2026-10-06"), _row(3, "2026-10-07"))
        assert _expired_medication_rows(df, TODAY)["MedicationID"].tolist() == [1, 2]

    def test_accepts_date_objects(self):
        df = _rows(_row(1, datetime.date(2026, 10, 6)), _row(2, datetime.date(2026, 10, 7)))
        assert _expired_medication_rows(df, TODAY)["MedicationID"].tolist() == [1]


class TestGroupMedicationLog:
    def test_each_row_logged_under_its_own_date(self):
        # used to put every row under the most common date
        df = _rows(_row(1, "2026-10-05"), _row(2, "2026-10-06"), _row(3, "2026-10-06"))
        grouped = _group_medication_log(df, DATE_FORMAT)
        assert {d: [r["MedicationID"] for r in recs] for d, recs in grouped[5].items()} == {
            "2026-10-05": [1],
            "2026-10-06": [2, 3],
        }

    def test_groups_by_schedule(self):
        df = _rows(_row(1, "2026-10-06", schedule_id=5), _row(2, "2026-10-06", schedule_id=6))
        assert set(_group_medication_log(df, DATE_FORMAT)) == {5, 6}

    def test_given_dose_is_json_serialisable(self):
        # Timestamp / NaT / numpy ints used to crash json.dumps
        df = _rows(
            _row(np.int64(1), "2026-10-06", status="1", given_at="2026-10-06 09:02", given_by="cg1"),
            _row(np.int64(2), "2026-10-06"),
        )
        recs = json.loads(json.dumps(_group_medication_log(df, DATE_FORMAT)))["5"]["2026-10-06"]
        assert recs[0]["Status"] == "1"
        assert recs[0]["ActualAdministerTime"].startswith("2026-10-06T09:02")
        assert recs[1]["ActualAdministerTime"] is None


def _freeze_today(monkeypatch):
    class FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime.combine(TODAY, datetime.time(10, 0))

    monkeypatch.setattr(
        writer_module, "datetime",
        SimpleNamespace(datetime=FixedDatetime, timedelta=datetime.timedelta, date=datetime.date),
    )


def _flush(monkeypatch, existing, deleted_course_rows, altered_rows):
    """Runs __checkAndFlush with the DB mocked. Returns (session, schedule row)."""
    _freeze_today(monkeypatch)
    monkeypatch.setattr(MedicationScheduleWrite, "config", {"STD_DATE_FORMAT": DATE_FORMAT}, raising=False)

    deleted = deleted_course_rows.copy()
    deleted["MedicationCourseDeleted"] = True
    monkeypatch.setattr(writer_module.DeletedMedicationView, "get_data", lambda *a, **k: deleted)

    altered = altered_rows.copy()
    altered["CurrentAdministerTimes"] = "1000"
    reads = iter([existing, altered])
    monkeypatch.setattr(writer_module.pd, "read_sql", lambda *a, **k: next(reads))
    monkeypatch.setattr(writer_module, "flag_modified", lambda *a, **k: None)

    schedule = SimpleNamespace(MedicationLog=None)
    session = MagicMock()
    session.get.return_value = schedule
    session.execute.return_value.all.return_value = []

    MedicationScheduleWrite._MedicationScheduleWrite__checkAndFlush(MagicMock(), session)
    return session, schedule


def _sql(stmt):
    return str(stmt.compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))


def _executed(session):
    return [c.args[0] for c in session.execute.call_args_list]


class TestCheckAndFlush:
    def test_past_rows_are_logged_before_delete(self, monkeypatch):
        # past rows used to be deleted without being logged, today's were logged instead
        existing = _rows(
            _row(1, "2026-10-06", status="1", given_at="2026-10-06 09:02", given_by="cg1"),
            _row(2, "2026-10-07"),
        )
        empty = existing.iloc[0:0]
        _, schedule = _flush(monkeypatch, existing, empty, empty)

        log = json.loads(schedule.MedicationLog)
        assert list(log) == ["2026-10-06"]
        assert log["2026-10-06"][0]["MedicationID"] == 1
        assert log["2026-10-06"][0]["Status"] == "1"
        assert log["2026-10-06"][0]["LoggedReason"] == "Expired"

    def test_todays_rows_are_not_logged(self, monkeypatch):
        existing = _rows(_row(2, "2026-10-07"))
        empty = existing.iloc[0:0]
        session, schedule = _flush(monkeypatch, existing, empty, empty)
        assert schedule.MedicationLog is None
        session.get.assert_not_called()

    def test_deleted_course_delete_only_removes_pending_rows(self, monkeypatch):
        existing = _rows(_row(3, "2026-10-07"))
        empty = existing.iloc[0:0]
        session, _ = _flush(monkeypatch, existing, existing, empty)

        course_deletes = [s for s in _executed(session) if isinstance(s, Delete) and "IN (3)" in _sql(s)]
        assert len(course_deletes) == 1
        assert "[MEDICATION_SCHEDULE].[Status] = '0'" in _sql(course_deletes[0])

    def test_given_dose_of_deleted_course_is_not_logged_as_deleted(self, monkeypatch):
        given = _row(3, "2026-10-07", status="1", given_at="2026-10-07 09:01")
        pending = _row(3, "2026-10-07", time="1400")
        existing = _rows(given, pending)
        _, schedule = _flush(monkeypatch, existing, existing, existing.iloc[0:0])

        recs = json.loads(schedule.MedicationLog)["2026-10-07"]
        assert [(r["AdministerTime"], r["LoggedReason"]) for r in recs] == [("1400", "Medication course deleted")]

    def test_changed_time_query_skips_given_doses(self, monkeypatch):
        existing = _rows(_row(4, "2026-10-07"))
        empty = existing.iloc[0:0]
        session, _ = _flush(monkeypatch, existing, empty, empty)

        selects = [s for s in _executed(session) if "STRING_SPLIT" in _sql(s).upper()]
        assert len(selects) == 1
        assert "[MEDICATION_SCHEDULE].[Status] = '0'" in _sql(selects[0])


def _put(monkeypatch, doses, rowcounts):
    """Runs MedicationScheduleWrite.update with the DB mocked. Returns (result or exception, session)."""
    monkeypatch.setattr(writer_module.DB, "get_engine", lambda: MagicMock())
    session = MagicMock()
    lookup = MagicMock()
    lookup.all.return_value = [SimpleNamespace(MedicationID=m, ScheduleID=5) for m in doses]
    session.execute.side_effect = [lookup] + [SimpleNamespace(rowcount=n) for n in rowcounts]
    session_cm = MagicMock()
    session_cm.__enter__.return_value = session
    monkeypatch.setattr(writer_module, "Session", lambda **k: session_cm)

    data = SimpleNamespace(
        PatientID=1, PrescriptionName="Paracetamol", AdministerDate=TODAY,
        AdministerTime="0900", Status="1", AdministeredBy="cg1",
    )
    try:
        return MedicationScheduleWrite.update(data), session
    except Exception as e:
        return e, session


class TestMarkAdministered:
    def test_lookup_goes_straight_to_the_dose_row(self, monkeypatch):
        # used to look up the medication with scalar_one(), which failed with two courses of
        # the same drug, then the schedule with scalar_one(), which failed with two schedules
        _, session = _put(monkeypatch, doses=[1], rowcounts=[1])
        sql = _sql(_executed(session)[0])
        assert "FROM [MEDICATION_SCHEDULE] JOIN [REF_PATIENT_MEDICATION]" in sql
        assert "[MEDICATION_SCHEDULE].[AdministerTime] = '0900'" in sql
        assert "[SCHEDULE]" not in sql.replace("[MEDICATION_SCHEDULE]", "")

    def test_two_courses_of_same_drug_marks_the_pending_one(self, monkeypatch):
        result, session = _put(monkeypatch, doses=[1, 2], rowcounts=[0, 1])
        assert isinstance(result, datetime.datetime)
        session.commit.assert_called_once()

    def test_update_only_applies_to_pending_dose(self, monkeypatch):
        # status check used to be a separate read, so two caregivers could both mark the dose
        _, session = _put(monkeypatch, doses=[1], rowcounts=[1])
        update_sql = _sql(_executed(session)[1])
        assert update_sql.startswith("UPDATE [MEDICATION_SCHEDULE]")
        assert "[MEDICATION_SCHEDULE].[Status] = '0'" in update_sql

    def test_already_given_raises(self, monkeypatch):
        result, session = _put(monkeypatch, doses=[1], rowcounts=[0])
        assert isinstance(result, writer_module.MedicationAlreadyAdministeredException)
        session.commit.assert_not_called()

    def test_missing_dose_raises_not_found(self, monkeypatch):
        result, _ = _put(monkeypatch, doses=[], rowcounts=[])
        assert isinstance(result, writer_module.MedicationScheduleNotFoundException)
