"""
db_utils/views.py - pins down a real bug where several views require an activity's date
range to fully contain the scheduling week instead of just overlapping it, so anything
starting/ending mid-week gets wrongly excluded.

Just build_query() / compile_query() here, no live DB.
"""

from datetime import datetime

import pytest
from sqlalchemy import MetaData, Table, Column, Integer, String, Boolean, Date

from pear_schedule.db_utils import views
from pear_schedule.db_utils.views import (
    ActivitiesView,
    CompulsoryActivitiesOnlyView,
    GroupActivitiesOnlyView,
    GroupActivitiesPreferenceView,
    GroupActivitiesRecommendationView,
    RecommendedActivitiesView,
)
from pear_schedule.utils import DBTABLES

FIXED_MONDAY = "2024-03-18"
FIXED_SUNDAY = datetime(2024, 3, 24, 23, 59, 59)

DB_TABLES = DBTABLES(
    ACTIVITY_TABLE="REF_ACTIVITY",
    ACTIVITY_EXCLUSION_TABLE="REF_ACTIVITY_EXCLUSION",
    CENTRE_ACTIVITY_TABLE="REF_CENTRE_ACTIVITY",
    CENTRE_ACTIVITY_PREFERENCE_TABLE="REF_ACTIVITY_PREFERENCE",
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE="REF_ACTIVITY_RECOMMENDATION",
    PATIENT_TABLE="REF_PATIENT",
    SCHEDULE_TABLE="SCHEDULE",
    MEDICATION_SCHEDULE_TABLE="MEDICATION_SCHEDULE",
    MEDICATION_TABLE="REF_PATIENT_MEDICATION",
    ALLOCATION_TABLE="REF_PATIENT_ALLOCATION",
    CARE_CENTRE_TABLE="REF_CARE_CENTRE",
    ADHOC_TABLE="REF_ADHOC",
)


def _make_fake_schema() -> MetaData:
    schema = MetaData()
    Table(
        "REF_ACTIVITY", schema,
        Column("ActivityID", Integer, primary_key=True),
        Column("ActivityTitle", String),
        Column("IsDeleted", String(1)),
    )
    Table(
        "REF_CENTRE_ACTIVITY", schema,
        Column("CentreActivityID", Integer, primary_key=True),
        Column("ActivityID", Integer),
        Column("IsGroup", Boolean),
        Column("IsDeleted", Boolean),
        Column("IsCompulsory", Boolean),
        Column("IsFixed", Boolean),
        Column("FixedTimeSlots", String),
        Column("MinDuration", Integer),
        Column("MaxDuration", Integer),
        Column("MinPeopleReq", Integer),
        Column("StartDate", Date),
        Column("EndDate", Date),
    )
    Table(
        "REF_ACTIVITY_PREFERENCE", schema,
        Column("CentreActivityPreferenceID", Integer, primary_key=True),
        Column("CentreActivityID", Integer),
        Column("PatientID", Integer),
        Column("IsLike", Integer),
        Column("IsDeleted", Boolean),
    )
    Table(
        "REF_ACTIVITY_RECOMMENDATION", schema,
        Column("CentreActivityRecommendationID", Integer, primary_key=True),
        Column("CentreActivityID", Integer),
        Column("PatientID", Integer),
        Column("DoctorRecommendation", Integer),
        Column("IsDeleted", Boolean),
    )
    return schema


@pytest.fixture(autouse=True)
def fake_view_config(monkeypatch):
    """Point every affected view at an in-memory schema + fixed week boundaries, no DB connection involved."""
    monkeypatch.setattr(views.DB, "schema", _make_fake_schema(), raising=False)
    monkeypatch.setattr(views, "get_monday", lambda: FIXED_MONDAY)
    monkeypatch.setattr(views, "get_next_sunday", lambda: FIXED_SUNDAY)
    for view_cls in (
        ActivitiesView,
        CompulsoryActivitiesOnlyView,
        GroupActivitiesOnlyView,
        GroupActivitiesPreferenceView,
        GroupActivitiesRecommendationView,
        RecommendedActivitiesView,
    ):
        view_cls.init_app({"DB_TABLES": DB_TABLES})


class TestActivityDateRangeFiltering:
    @pytest.mark.parametrize(
        "view_cls",
        [
            ActivitiesView,
            CompulsoryActivitiesOnlyView,
            GroupActivitiesOnlyView,
            GroupActivitiesPreferenceView,
            GroupActivitiesRecommendationView,
            RecommendedActivitiesView,
        ],
    )
    def test_requires_full_week_containment_instead_of_overlap(self, view_cls):
        sql = str(views.compile_query(view_cls.build_query()))

        assert f'"REF_CENTRE_ACTIVITY"."StartDate" < \'{FIXED_MONDAY}\'' in sql
        assert f'"REF_CENTRE_ACTIVITY"."EndDate" > \'{FIXED_SUNDAY}\'' in sql
