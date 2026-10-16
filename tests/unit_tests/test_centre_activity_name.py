"""A centre activity's own name, shown instead of its activity's title when set."""

import datetime
import random
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, MetaData, String, Table, create_engine, insert

from messaging.centre_activity_consumer import CentreActivityConsumer
from messaging.mappers.mapper_util import map_centre_activity_create, map_centre_activity_update
from pear_schedule.db_utils import views
from tests.unit_tests.test_activity_availability import DB_TABLES
from tests.unit_tests.test_group_scheduling import _empty_patient_schedules, _group_config, _patch_group_views, _scheduled_bins
from tests.utils.scheduler_config import make_scheduler_config

WEEK = datetime.datetime(2024, 3, 18)


@pytest.fixture
def db(monkeypatch):
    schema = MetaData()
    activity = Table("REF_ACTIVITY", schema, Column("ActivityID", Integer, primary_key=True), Column("ActivityTitle", String))
    centre = Table(
        "REF_CENTRE_ACTIVITY", schema,
        Column("CentreActivityID", Integer, primary_key=True), Column("ActivityID", Integer),
        Column("IsGroup", Boolean), Column("IsDeleted", Boolean), Column("IsCompulsory", Boolean),
        Column("IsFixed", Boolean), Column("FixedTimeSlots", String), Column("Name", String), Column("MinDuration", Integer),
        Column("MaxDuration", Integer), Column("MinPeopleReq", Integer), Column("StartDate", Date), Column("EndDate", Date),
    )
    patient = Table("REF_PATIENT", schema, Column("PatientID", Integer, primary_key=True), Column("Name", String))
    adhoc = Table(
        "REF_ADHOC", schema,
        Column("AdhocID", Integer, primary_key=True), Column("PatientID", Integer),
        Column("OldCentreActivityID", Integer), Column("NewCentreActivityID", Integer),
        Column("StartDate", Date), Column("EndDate", Date), Column("Status", String), Column("IsDeleted", String),
        Column("CreatedDateTime", DateTime), Column("UpdatedDateTime", DateTime),
    )
    engine = create_engine("sqlite:///:memory:")
    schema.create_all(engine)
    with engine.begin() as conn:
        for aid, title in [(1, "Breathing"), (2, "Walk"), (3, "Puzzles")]:
            conn.execute(insert(activity).values(ActivityID=aid, ActivityTitle=title))
        # two centre activities of one activity, one with no name, one with a blank name
        for cid, aid, name, group in [(1, 1, "Breathing AM", True), (2, 1, "Breathing PM", False), (3, 2, None, False), (4, 3, "  ", False)]:
            conn.execute(insert(centre).values(
                CentreActivityID=cid, ActivityID=aid, IsGroup=group, IsDeleted=False, IsCompulsory=False,
                IsFixed=False, FixedTimeSlots=None, Name=name, MinDuration=30, MaxDuration=30, MinPeopleReq=2 if group else 1,
                StartDate=datetime.date(2024, 1, 1), EndDate=datetime.date(2024, 12, 31),
            ))
        conn.execute(insert(patient).values(PatientID=7, Name="P7"))
        conn.execute(insert(adhoc).values(
            AdhocID=1, PatientID=7, OldCentreActivityID=3, NewCentreActivityID=2, Status="Approved", IsDeleted="0",
            StartDate=datetime.date(2024, 3, 18), EndDate=datetime.date(2024, 3, 22),
            CreatedDateTime=WEEK, UpdatedDateTime=WEEK,
        ))
    monkeypatch.setattr(views.DB, "schema", schema, raising=False)
    monkeypatch.setattr(views, "get_week_start", lambda: WEEK)
    monkeypatch.setattr(views, "get_week_end", lambda: WEEK + datetime.timedelta(days=6, hours=23, minutes=59))
    return engine


def _data(engine, view):
    view.init_app({"DB_TABLES": DB_TABLES})
    with engine.connect() as conn:
        return view.get_data(conn=conn)


class TestViews:
    def test_name_wins_else_the_title(self, db):
        assert sorted(_data(db, views.ActivitiesView)["ActivityTitle"]) == ["Breathing PM", "Puzzles", "Walk"]

    def test_group_view(self, db):
        assert list(_data(db, views.GroupActivitiesOnlyView)["ActivityTitle"]) == ["Breathing AM"]

    def test_one_title_column_where_the_whole_activity_is_selected(self, db):
        for view in (views.AllActivitiesView, views.ActivitiesView, views.ActivityAndCentreActivityView):
            df = _data(db, view)
            assert list(df.columns).count("ActivityTitle") == 1, view.__name__
        both = _data(db, views.ActivityAndCentreActivityView)
        assert sorted(both["ActivityTitle"]) == ["Breathing AM", "Breathing PM", "Puzzles", "Walk"]

    def test_adhoc_titles_match_the_schedule(self, db):
        row = _data(db, views.AdhocActivityView).iloc[0]
        assert (row["OldActivityTitle"], row["NewActivityTitle"]) == ("Walk", "Breathing PM")


class TestWritePath:
    DATA = {"id": 2, "activity_id": 1, "is_compulsory": False, "is_fixed": False, "is_group": False,
            "start_date": "2026-10-01", "end_date": "2026-12-31", "min_duration": 30, "max_duration": 30,
            "min_people_req": 1, "fixed_time_slots": None, "name": "Breathing PM",
            "created_date": "2026-10-16T10:00:00", "modified_date": "2026-10-16T10:00:00"}

    def test_mapper_carries_the_name(self):
        assert map_centre_activity_create(self.DATA)["Name"] == "Breathing PM"
        assert map_centre_activity_update({"id": 2, "name": "Breathing PM", "modified_date": "2026-10-16T10:00:00"})["Name"] == "Breathing PM"

    def test_insert_includes_the_name(self, db_session_mock):
        from pear_schedule.crud.ref_centre_activity_crud import create_ref_centre_activity
        from pear_schedule.schemas.ref_centre_activity import RefCentreActivityCreate

        db_session_mock.query().filter().first.side_effect = [None, (1,), object()]
        mapped = map_centre_activity_create(self.DATA)
        create_ref_centre_activity(db_session_mock, RefCentreActivityCreate(**mapped), "c1", "u1", skip_duplicate_check=True)
        query, params = db_session_mock.execute.call_args.args
        assert ":Name" in str(query) and params["Name"] == "Breathing PM"

    def _update(self, **new_data):
        consumer = CentreActivityConsumer.__new__(CentreActivityConsumer)
        consumer.config = make_scheduler_config()
        consumer.map_centre_activity_update = map_centre_activity_update
        consumer.update_ref_centre_activity = MagicMock(return_value=(object(), False))
        message = {"correlation_id": "c1", "centre_activity_id": 2, "modified_by": "u1",
                   "new_data": {"id": 2, "modified_date": "2026-10-16T10:00:00", "modified_by_id": "u1", **new_data}}
        consumer._handle_centre_activity_updated(None, message)
        return consumer.update_ref_centre_activity.call_args.kwargs["centre_activity_update"].model_dump(exclude_unset=True)

    def test_update_sets_the_name(self):
        assert self._update(name="Breathing PM")["Name"] == "Breathing PM"

    def test_clearing_the_name_goes_back_to_the_title(self):
        # the mapper drops None on updates, it has to come through to clear it
        dumped = self._update(name=None)
        assert "Name" in dumped and dumped["Name"] is None

    def test_name_not_sent_is_left_alone(self):
        assert "Name" not in self._update(min_duration=30)


class TestScheduling:
    def test_am_and_pm_of_one_activity_both_placed(self):
        """Different names are different activities to the stages and the once-a-day rule."""
        from pear_schedule.scheduler.invariants import base_title, check_rules
        from tests.utils.schedule_scenarios import FAR_FUTURE, make_scenario, run

        scenario = make_scenario(random.Random(3), patients=2, days=3, slots=8, pool_size=3, compulsory=0,
                                 flexible_share=1.0, like_rate=0, dislike_rate=0, exclusion_rate=0,
                                 recommend_rate=0, not_recommend_rate=0)
        scenario.views["CompulsoryActivitiesOnlyView"] = pd.DataFrame(
            [["Breathing AM", 1, "0-0,1-0,2-0", 30]], columns=["ActivityTitle", "IsFixed", "FixedTimeSlots", "MinDuration"])
        pool = scenario.views["ActivitiesView"]
        pm = pd.DataFrame([[200, "Breathing PM", "0-6,1-6,2-6", 30, 30, FAR_FUTURE, pd.Timestamp("2020-01-01")]], columns=pool.columns)
        scenario.views["ActivitiesView"] = pd.concat([pool, pm], ignore_index=True)

        for strategy in ("greedy", "optimal"):
            schedules, _, inputs = run(scenario, strategy)
            for days in schedules.values():
                for day in days:
                    titles = [base_title(v) for v in day]
                    assert titles[0] == "Breathing AM" and titles[6] == "Breathing PM", strategy
            assert [v for v in check_rules(schedules, inputs) if v.rule != "R8"] == []

    def test_group_title_with_an_apostrophe(self, monkeypatch):
        """Titles used to go into DataFrame.query strings, a ' crashed group scheduling."""
        from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler

        cfg = _group_config()
        monkeypatch.setattr(GroupActivityScheduler, "config", cfg, raising=False)
        group = pd.DataFrame({"ActivityID": [1], "CentreActivityID": [1], "ActivityTitle": ["Mdm Lim's Mahjong"],
                              "IsFixed": [0], "FixedTimeSlots": [""], "MinPeopleReq": [2], "MinDuration": [30]})
        recs = pd.DataFrame({"CentreActivityID": [1, 1], "PatientID": [1, 2], "DoctorRecommendation": [1, 1]})

        with _patch_group_views([1, 2], group, recommendation_df=recs):
            result = GroupActivityScheduler.fillSchedule(_empty_patient_schedules([1, 2], cfg["OPEN_DAYS"], 8))

        assert len(_scheduled_bins(result, 1, "Mdm Lim's Mahjong")) == 1
