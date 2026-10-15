"""
getSchedule for another week. View query on sqlite, route with the view mocked.
"""

import datetime
import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, insert

from pear_schedule.api import schedule_router
from pear_schedule.db_utils import views
from pear_schedule.db_utils.views import WeeklyScheduleView

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LAST_WEEK = datetime.datetime(2026, 10, 5)
THIS_WEEK = datetime.datetime(2026, 10, 12)


def _schema() -> MetaData:
    schema = MetaData()
    Table("REF_PATIENT", schema, Column("PatientID", Integer, primary_key=True), Column("Name", String))
    Table(
        "SCHEDULE", schema,
        Column("ScheduleID", Integer, primary_key=True),
        Column("PatientID", Integer),
        *[Column(d, String) for d in DAYS],
        Column("StartDate", DateTime),
        Column("EndDate", DateTime),
    )
    return schema


@pytest.fixture
def engine(monkeypatch):
    schema = _schema()
    monkeypatch.setattr(views.DB, "schema", schema, raising=False)
    monkeypatch.setattr(WeeklyScheduleView, "db_tables",
                        SimpleNamespace(SCHEDULE_TABLE="SCHEDULE", PATIENT_TABLE="REF_PATIENT"), raising=False)
    engine = create_engine("sqlite:///:memory:")
    schema.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(schema.tables["REF_PATIENT"]).values(PatientID=1, Name="Alice"))
        for sid, start in ((1, LAST_WEEK), (2, THIS_WEEK)):
            conn.execute(insert(schema.tables["SCHEDULE"]).values(
                ScheduleID=sid, PatientID=1, StartDate=start,
                EndDate=start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59),
                **{d: json.dumps({"09:00-09:30": f"week {sid}"}) for d in DAYS},
            ))
    return engine


def _ids(engine, **kw):
    with engine.connect() as conn:
        return [r["ScheduleID"] for r in conn.execute(WeeklyScheduleView.build_query(**kw)).mappings()]


class TestWeeklyScheduleView:
    def test_any_day_in_a_past_week_gets_that_week(self, engine):
        assert _ids(engine, at=datetime.datetime(2026, 10, 5, 12)) == [1]   # Monday
        assert _ids(engine, at=datetime.datetime(2026, 10, 11, 12)) == [1]  # Sunday

    def test_no_date_is_this_week(self, engine, monkeypatch):
        class FixedNow(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 15, 17, 0)
        monkeypatch.setattr(views, "datetime", FixedNow)
        assert _ids(engine) == [2]

    def test_week_with_nothing_saved_is_empty(self, engine):
        assert _ids(engine, at=datetime.datetime(2026, 9, 1, 12)) == []


class TestGetScheduleRoute:
    def _df(self):
        return pd.DataFrame({"ScheduleID": [1], "PatientID": [1], "Name": ["Alice"]})

    def test_no_date_keeps_the_old_call(self):
        with patch.object(schedule_router.WeeklyScheduleView, "get_data", return_value=self._df()) as get:
            res = schedule_router.get_schedule(SimpleNamespace(), None)
        get.assert_called_once_with()
        assert json.loads(res.body)["Status"] == "200"

    def test_date_asks_for_that_day(self):
        with patch.object(schedule_router.WeeklyScheduleView, "get_data", return_value=self._df()) as get:
            schedule_router.get_schedule(SimpleNamespace(), datetime.date(2026, 10, 8))
        get.assert_called_once_with(at=datetime.datetime(2026, 10, 8, 12))

    def test_nothing_saved_that_week_is_404(self):
        empty = pd.DataFrame(columns=["ScheduleID", "PatientID", "Name"])
        with patch.object(schedule_router.WeeklyScheduleView, "get_data", return_value=empty):
            res = schedule_router.get_schedule(SimpleNamespace(), datetime.date(2026, 9, 1))
        assert json.loads(res.body)["Status"] == "404"
