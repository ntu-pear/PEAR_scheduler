"""Next week preview: building another week, the views and stages that follow it, and the calendar rows."""

import datetime
import json
import random
from contextlib import nullcontext

import pandas as pd
import pytest
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, MetaData, String, Table, create_engine, insert

from pear_schedule.db_utils import utils, views
from pear_schedule.db_utils.utils import building_for, building_week, get_week_end, get_week_start, next_week_start, schedule_day_columns
from pear_schedule.scheduler import explain
from tests.unit_tests.test_activity_availability import DB_TABLES
from tests.utils.schedule_scenarios import WEEK_START, make_scenario, patched

NEXT = (WEEK_START + datetime.timedelta(days=7)).date()


def _this_monday():
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())


class TestBuildingWeek:
    def test_normal_run_is_unchanged(self):
        assert building_for() is None
        assert get_week_start().date() == _this_monday()
        assert get_week_end().date() == _this_monday() + datetime.timedelta(days=6)

    def test_builds_as_that_monday_midnight(self):
        with building_week(NEXT):
            assert building_for() == datetime.datetime(2024, 3, 25)
            assert get_week_start() == datetime.datetime(2024, 3, 25)
            assert get_week_end() == datetime.datetime(2024, 3, 31, 23, 59, 59)
        assert building_for() is None

    def test_any_day_means_its_week(self):
        with building_week(datetime.date(2024, 3, 28)):
            assert get_week_start() == datetime.datetime(2024, 3, 25)

    def test_resets_after_an_error(self):
        with pytest.raises(RuntimeError):
            with building_week(NEXT):
                raise RuntimeError("build failed")
        assert building_for() is None

    @pytest.mark.parametrize("now", [
        datetime.datetime(2024, 3, 18, 0, 0), datetime.datetime(2024, 3, 21, 15, 0), datetime.datetime(2024, 3, 24, 23, 59),
    ])
    def test_next_week_start(self, now):
        assert next_week_start(now) == datetime.date(2024, 3, 25)

    def test_explain_follows_it(self):
        with building_week(NEXT):
            assert explain.current_week_start().date() == NEXT


class TestScheduleDayColumns:
    def test_same_as_the_writer(self):
        config = {"OPEN_DAYS": ["Monday", "Tuesday"], "MIN_ACTIVITY_DURATION": 30,
                  "WORKING_HOURS": {"monday": {"open": "09:00"}, "tuesday": {"open": "10:00"}}}
        columns = schedule_day_columns([["Walk", ""], ["Free and Easy", "Bingo | Give Medication@0930"]], config)
        assert json.loads(columns["Monday"]) == {"09:00-09:30": "Walk", "09:30-10:00": "Free and Easy"}
        assert json.loads(columns["Tuesday"]) == {"10:00-10:30": "Free and Easy", "10:30-11:00": "Bingo | Give Medication@0930"}


@pytest.fixture
def db(monkeypatch):
    """Real dates around today, so the views' own week filters are what's tested."""
    schema = MetaData()
    activity = Table("REF_ACTIVITY", schema, Column("ActivityID", Integer, primary_key=True), Column("ActivityTitle", String))
    centre = Table(
        "REF_CENTRE_ACTIVITY", schema,
        Column("CentreActivityID", Integer, primary_key=True), Column("ActivityID", Integer),
        Column("IsGroup", Boolean), Column("IsDeleted", Boolean), Column("IsCompulsory", Boolean),
        Column("IsFixed", Boolean), Column("FixedTimeSlots", String), Column("Name", String), Column("MinDuration", Integer),
        Column("MaxDuration", Integer), Column("StartDate", Date), Column("EndDate", Date),
    )
    exclusion = Table(
        "REF_ACTIVITY_EXCLUSION", schema,
        Column("ActivityExclusionID", Integer, primary_key=True), Column("CentreActivityID", Integer),
        Column("PatientID", Integer), Column("ExclusionRemarks", String), Column("IsDeleted", Boolean),
        Column("StartDateTime", DateTime), Column("EndDateTime", DateTime),
    )
    monday = _this_monday()
    next_monday = monday + datetime.timedelta(days=7)
    engine = create_engine("sqlite:///:memory:")
    schema.create_all(engine)
    with engine.begin() as conn:
        for cid, title, start, end in [
            (1, "Walk", monday - datetime.timedelta(days=30), monday + datetime.timedelta(days=60)),
            (2, "Ends this week", monday - datetime.timedelta(days=30), monday + datetime.timedelta(days=4)),
            (3, "Starts next week", next_monday, next_monday + datetime.timedelta(days=60)),
        ]:
            conn.execute(insert(activity).values(ActivityID=cid, ActivityTitle=title))
            conn.execute(insert(centre).values(
                CentreActivityID=cid, ActivityID=cid, IsGroup=False, IsDeleted=False, IsCompulsory=False,
                IsFixed=False, FixedTimeSlots=None, MinDuration=30, MaxDuration=30, StartDate=start, EndDate=end,
            ))
        this_friday = datetime.datetime.combine(monday + datetime.timedelta(days=4), datetime.time(23, 59))
        conn.execute(insert(exclusion).values(
            ActivityExclusionID=1, CentreActivityID=1, PatientID=7, ExclusionRemarks="", IsDeleted=False,
            StartDateTime=datetime.datetime.combine(monday, datetime.time()), EndDateTime=this_friday,
        ))
    monkeypatch.setattr(views.DB, "schema", schema, raising=False)
    for view in (views.ActivitiesView, views.ActivitiesExcludedView):
        view.init_app({"DB_TABLES": DB_TABLES})
    return engine, next_monday


def _titles(engine, view):
    with engine.connect() as conn:
        return set(view.get_data(conn=conn)["ActivityTitle"])


class TestViewsFollowTheWeek:
    def test_activities_this_week(self, db):
        engine, _ = db
        assert _titles(engine, views.ActivitiesView) == {"Walk", "Ends this week"}

    def test_activities_next_week(self, db):
        engine, next_monday = db
        with building_week(next_monday):
            assert _titles(engine, views.ActivitiesView) == {"Walk", "Starts next week"}

    def test_exclusion_ending_this_week_is_gone_next_week(self, db):
        engine, next_monday = db
        assert _titles(engine, views.ActivitiesExcludedView) == {"Walk"}
        with building_week(next_monday):
            assert _titles(engine, views.ActivitiesExcludedView) == set()


def _scenario():
    scenario = make_scenario(random.Random(1), patients=2, days=5, slots=8, pool_size=4, flexible_share=1.0,
                             like_rate=0, dislike_rate=0, exclusion_rate=0, recommend_rate=0, not_recommend_rate=0)
    v = scenario.views
    v["MedicationView"] = pd.DataFrame({
        "PatientID": [1], "MedicationID": [1], "PrescriptionName": ["Aspirin"], "Dosage": ["1 tablet"],
        "AdministerTime": ["0900"], "StartDateTime": [WEEK_START + datetime.timedelta(days=7)],
        "EndDateTime": [datetime.datetime(2099, 12, 31)], "Instruction": [""], "IsDeleted": [0],
    })
    v["ActivitiesExcludedView"] = pd.DataFrame({
        "ActivityExclusionID": [1], "ActivityID": [100], "PatientID": [2], "ExclusionRemarks": [""],
        "EndDateTime": [WEEK_START + datetime.timedelta(days=6, hours=23, minutes=59)], "ActivityTitle": ["Activity 0"],
    })
    v["AdhocActivityView"] = pd.DataFrame({
        "AdhocID": [1], "PatientID": [1], "OldActivityTitle": ["Compulsory 0"], "NewActivityTitle": ["Adhoc swap"],
        "StartDate": [WEEK_START.date()], "EndDate": [(WEEK_START + datetime.timedelta(days=4)).date()],
    })
    return scenario


def _build(preview, week=NEXT):
    from pear_schedule.scheduler.utils import build_schedules

    schedules = {}
    with patched(_scenario(), "optimal") as config:
        with building_week(week) if preview else nullcontext():
            build_schedules(config, schedules)
    return schedules


def _has(schedules, pid, text):
    return any(text in value for day in schedules[pid] for value in day)


class TestPipelineFollowsTheWeek:
    def test_medication_starting_next_week(self):
        assert not _has(_build(False), 1, "Give Medication")
        assert _has(_build(True), 1, "Give Medication")

    def test_exclusion_ending_this_week(self):
        assert not _has(_build(False), 2, "Activity 0")
        assert _has(_build(True), 2, "Activity 0")

    def test_adhoc_for_this_week_only(self):
        assert _has(_build(False), 1, "Adhoc swap")
        assert not _has(_build(True), 1, "Adhoc swap")

    def test_building_this_week_is_the_normal_build(self):
        assert _build(True, WEEK_START.date()) == _build(False)
        assert building_for() is None


class TestPreviewNextWeek:
    def test_builds_next_week_and_marks_it(self, monkeypatch):
        seen = {}

        def run(config, patient_ids, with_names, with_what_if):
            seen["week"] = utils.get_week_start()
            return {"source": "built"}
        monkeypatch.setattr(explain, "run_explanation", run)
        out = explain.preview_next_week({}, now=datetime.datetime(2024, 3, 21, 15, 0))
        assert seen["week"] == datetime.datetime(2024, 3, 25)
        assert out["source"] == "preview"
        assert building_for() is None

    def test_never_writes(self, monkeypatch):
        from unittest.mock import MagicMock

        from pear_schedule.db_utils.writer import ScheduleWriter
        writer = MagicMock()
        monkeypatch.setattr(ScheduleWriter, "write", writer)
        monkeypatch.setattr(explain, "run_explanation", lambda *a: {"source": "built"})
        explain.preview_next_week({})
        writer.assert_not_called()


class TestScheduleRows:
    CONFIG = {"OPEN_DAYS": ["Monday", "Tuesday"], "MIN_ACTIVITY_DURATION": 30,
              "WORKING_HOURS": {"monday": {"open": "09:00"}, "tuesday": {"open": "09:00"}}}

    def _explanation(self):
        def day(*values):
            return {"slots": [{"value": v} for v in values]}
        return {"week_start": "2024-03-25", "patients": {
            "1": {"name": "Ann", "days": [day("Walk", ""), day("Bingo", "Walk")]},
        }}

    def test_same_columns_as_get_schedule(self, monkeypatch):
        schema = MetaData()
        days = [Column(d, String) for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
        Table(DB_TABLES.SCHEDULE_TABLE, schema, Column("ScheduleID", Integer), Column("PatientID", Integer), *days,
              Column("StartDate", DateTime), Column("EndDate", DateTime))
        Table(DB_TABLES.PATIENT_TABLE, schema, Column("PatientID", Integer), Column("Name", String))
        monkeypatch.setattr(views.DB, "schema", schema, raising=False)
        views.WeeklyScheduleView.init_app({"DB_TABLES": DB_TABLES})
        # getSchedule drops ScheduleID
        get_schedule = [c.name for c in views.WeeklyScheduleView.build_query().selected_columns if c.name != "ScheduleID"]
        assert list(explain.schedule_rows(self._explanation(), self.CONFIG)[0]) == get_schedule

    def test_values(self):
        row = explain.schedule_rows(self._explanation(), self.CONFIG)[0]
        assert row["PatientID"] == 1 and row["Name"] == "Ann"
        assert json.loads(row["Monday"]) == {"09:00-09:30": "Walk", "09:30-10:00": "Free and Easy"}
        assert row["Wednesday"] == "" and row["Sunday"] == ""
        assert row["StartDate"] == "2024-03-25T00:00:00"
        assert row["EndDate"] == "2024-03-31T23:59:59"
