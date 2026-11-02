"""RecommendedActivitiesView on a real (SQLite) query."""

import datetime

import pytest
from sqlalchemy import Boolean, Column, Date, Integer, MetaData, String, Table, create_engine, insert

from pear_schedule.db_utils import views
from tests.unit_tests.test_activity_availability import DB_TABLES

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
        Column("StartDate", Date), Column("EndDate", Date),
    )
    recs = Table(
        "REF_ACTIVITY_RECOMMENDATION", schema,
        Column("ActivityRecommendationID", Integer, primary_key=True), Column("CentreActivityID", Integer),
        Column("PatientID", Integer), Column("DoctorRecommendation", Integer), Column("IsDeleted", Boolean),
    )
    engine = create_engine("sqlite:///:memory:")
    schema.create_all(engine)
    with engine.begin() as conn:
        for cid, title, deleted in [(1, "Walk", False), (2, "Old walk", True)]:
            conn.execute(insert(activity).values(ActivityID=cid, ActivityTitle=title))
            conn.execute(insert(centre).values(
                CentreActivityID=cid, ActivityID=cid, IsGroup=False, IsDeleted=deleted, IsCompulsory=False,
                IsFixed=False, FixedTimeSlots=None, Name=None, MinDuration=30,
                StartDate=datetime.date(2024, 1, 1), EndDate=datetime.date(2024, 12, 31),
            ))
            conn.execute(insert(recs).values(ActivityRecommendationID=cid, CentreActivityID=cid, PatientID=7,
                                             DoctorRecommendation=1, IsDeleted=False))
    monkeypatch.setattr(views.DB, "schema", schema, raising=False)
    monkeypatch.setattr(views, "get_week_start", lambda: WEEK)
    monkeypatch.setattr(views, "get_week_end", lambda: WEEK + datetime.timedelta(days=6, hours=23, minutes=59))
    views.RecommendedActivitiesView.init_app({"DB_TABLES": DB_TABLES})
    return engine


def test_deleted_centre_activity_is_not_recommended(db):
    """The recommendation row can outlive its centre activity, it used to keep it scheduled."""
    with db.connect() as conn:
        df = views.RecommendedActivitiesView.get_data(conn=conn)
    assert list(df["ActivityTitle"]) == ["Walk"]
