"""
db_utils/views.py
Just build_query() / compile_query() here, no live DB.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import MetaData, Table, Column, Integer, String, Boolean, Date, DateTime, create_engine, insert

from pear_schedule.db_utils import views
from pear_schedule.db_utils.views import (
    ActivitiesView,
    CompulsoryActivitiesOnlyView,
    GroupActivitiesExclusionView,
    GroupActivitiesOnlyView,
    GroupActivitiesPreferenceView,
    GroupActivitiesRecommendationView,
    PatientsUnpreferredView,
    PatientsView,
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
        "REF_PATIENT", schema,
        Column("PatientID", Integer, primary_key=True),
    )
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
    Table(
        "REF_ACTIVITY_EXCLUSION", schema,
        Column("ActivityExclusionID", Integer, primary_key=True),
        Column("PatientID", Integer),
        Column("CentreActivityID", Integer),
        Column("StartDateTime", DateTime),
        Column("EndDateTime", DateTime),
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
        GroupActivitiesExclusionView,
        GroupActivitiesOnlyView,
        GroupActivitiesPreferenceView,
        GroupActivitiesRecommendationView,
        RecommendedActivitiesView,
        PatientsView,
        PatientsUnpreferredView,
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
    def test_uses_overlap_check_not_full_week_containment(self, view_cls):
        sql = str(views.compile_query(view_cls.build_query()))

        assert f'"REF_CENTRE_ACTIVITY"."StartDate" <= \'{FIXED_SUNDAY}\'' in sql
        assert f'"REF_CENTRE_ACTIVITY"."EndDate" >= \'{FIXED_MONDAY}\'' in sql


class TestGroupActivitiesExclusionViewWeekBoundary:
    """GroupActivitiesExclusionView.build_query() computes its own week boundary inline
    (not via get_monday()/get_next_sunday()) and used to roll over to next week's dates
    whenever run on a Sunday, unlike every other week-boundary computation in the codebase."""

    def test_sunday_uses_current_week_not_next_week(self, monkeypatch):
        # Sunday 2024-03-24 is the last day of the week starting Monday 2024-03-18 (FIXED_MONDAY).
        class FixedSundayDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2024, 3, 24, 10, 0, 0)

        monkeypatch.setattr(views, "datetime", FixedSundayDatetime)

        params = GroupActivitiesExclusionView.build_query().compile().params

        assert params["EndDateTime_1"] == datetime(2024, 3, 18, 0, 0, 0)  # start_of_week
        assert params["StartDateTime_1"] == datetime(2024, 3, 24, 23, 59, 59)  # end_of_week


# 4 fake activities, one per date-range shape. All three of SPANS_WEEK, STARTS_MIDWEEK and
# ENDS_MIDWEEK overlap the week and should be scheduled. 
# OUTSIDE_WEEK doesn't overlap at all and should never come back.
WEEK_OVERLAP_CASES = {
    "SPANS_WEEK": (date(2024, 3, 1), date(2024, 4, 1)),
    "STARTS_MIDWEEK": (date(2024, 3, 20), date(2024, 4, 1)),  # starts Wed, still runs past Sunday
    "ENDS_MIDWEEK": (date(2024, 3, 1), date(2024, 3, 20)),    # ends Wed, was already running Monday
    "OUTSIDE_WEEK": (date(2024, 4, 1), date(2024, 4, 10)),
}


def _seed_centre_activities(engine, schema, *, is_group, is_compulsory, is_fixed, extra_join_row=None):
    """
    Insert one REF_ACTIVITY/REF_CENTRE_ACTIVITY row per case in WEEK_OVERLAP_CASES.
    """
    activity = schema.tables["REF_ACTIVITY"]
    centre_activity = schema.tables["REF_CENTRE_ACTIVITY"]
    with engine.begin() as conn:
        for centre_activity_id, (label, (start, end)) in enumerate(WEEK_OVERLAP_CASES.items(), start=1):
            conn.execute(insert(activity).values(ActivityID=centre_activity_id, ActivityTitle=label))
            conn.execute(insert(centre_activity).values(
                CentreActivityID=centre_activity_id, ActivityID=centre_activity_id,
                IsGroup=is_group, IsDeleted=False, IsCompulsory=is_compulsory, IsFixed=is_fixed,
                FixedTimeSlots=None, MinDuration=30, MaxDuration=30, MinPeopleReq=1,
                StartDate=start, EndDate=end,
            ))
            if extra_join_row is not None:
                table_name, row_builder = extra_join_row
                conn.execute(insert(schema.tables[table_name]).values(**row_builder(centre_activity_id)))


class TestActivityDateRangeFilteringImpact:
    """Same fix as above, but runs the queries for real against an in-memory SQLite DB instead
    of just reading the SQL text, so we can see which activities actually come back."""

    @pytest.mark.parametrize(
        "view_cls, view_kwargs, identify_by",
        [
            (ActivitiesView, dict(is_group=False, is_compulsory=False, is_fixed=False), "ActivityTitle"),
            (GroupActivitiesOnlyView, dict(is_group=True, is_compulsory=False, is_fixed=False), "ActivityTitle"),
            (CompulsoryActivitiesOnlyView, dict(is_group=False, is_compulsory=True, is_fixed=True), "ActivityTitle"),
            (
                # needs a matching REF_ACTIVITY_RECOMMENDATION row or the join drops everything
                RecommendedActivitiesView,
                dict(
                    is_group=False, is_compulsory=False, is_fixed=False,
                    extra_join_row=("REF_ACTIVITY_RECOMMENDATION", lambda cid: dict(
                        CentreActivityRecommendationID=cid, CentreActivityID=cid, PatientID=1,
                        DoctorRecommendation=1, IsDeleted=False,
                    )),
                ),
                "ActivityTitle",
            ),
            (
                # needs a matching REF_ACTIVITY_PREFERENCE row, same reason as above
                GroupActivitiesPreferenceView,
                dict(
                    is_group=True, is_compulsory=False, is_fixed=False,
                    extra_join_row=("REF_ACTIVITY_PREFERENCE", lambda cid: dict(
                        CentreActivityPreferenceID=cid, CentreActivityID=cid, PatientID=1,
                        IsLike=1, IsDeleted=False,
                    )),
                ),
                "CentreActivityID",
            ),
            (
                # needs a matching REF_ACTIVITY_RECOMMENDATION row, same reason as above
                GroupActivitiesRecommendationView,
                dict(
                    is_group=True, is_compulsory=False, is_fixed=False,
                    extra_join_row=("REF_ACTIVITY_RECOMMENDATION", lambda cid: dict(
                        CentreActivityRecommendationID=cid, CentreActivityID=cid, PatientID=1,
                        DoctorRecommendation=1, IsDeleted=False,
                    )),
                ),
                "CentreActivityID",
            ),
        ],
    )
    def test_mid_week_activities_are_included_in_results(self, view_cls, view_kwargs, identify_by):
        engine = create_engine("sqlite:///:memory:")
        schema = views.DB.schema
        schema.create_all(engine)

        view_kwargs = dict(view_kwargs)
        extra_join_row = view_kwargs.pop("extra_join_row", None)
        _seed_centre_activities(engine, schema, extra_join_row=extra_join_row, **view_kwargs)

        with engine.connect() as conn:
            rows = conn.execute(view_cls.build_query()).mappings().all()

        if identify_by == "ActivityTitle":
            returned_labels = {row["ActivityTitle"] for row in rows}
        else:
            id_to_label = {i: label for i, label in enumerate(WEEK_OVERLAP_CASES, start=1)}
            returned_labels = {id_to_label[row["CentreActivityID"]] for row in rows}

        # SPANS_WEEK, STARTS_MIDWEEK and ENDS_MIDWEEK all overlap the week and should come back. OUTSIDE_WEEK doesn't overlap at all and should stay excluded.
        assert returned_labels == {"SPANS_WEEK", "STARTS_MIDWEEK", "ENDS_MIDWEEK"}, (
            f"{view_cls.__name__} returned {returned_labels}; expected all three overlapping "
            "cases, OUTSIDE_WEEK excluded."
        )


# These two views only check StartDate, no EndDate in the SQL (done later in Python, see individualScheduling.py).
# So we just need StartDate cases here, not the full matrix above.
STARTDATE_CASES = {
    "STARTS_BEFORE_WEEK": date(2024, 3, 1),
    "STARTS_ON_MONDAY": date(2024, 3, 18),   # old code excluded this too, off by one
    "STARTS_MIDWEEK": date(2024, 3, 20),     # Wed
    "STARTS_AFTER_WEEK": date(2024, 3, 25),  # next Monday, shouldn't count
}
FAR_FUTURE_END_DATE = date(2024, 12, 31)  # not filtered, just keep it out of the way
PATIENT_ID = 1


def _seed_patient_preferences(engine, schema, *, is_like):
    patient = schema.tables["REF_PATIENT"]
    activity = schema.tables["REF_ACTIVITY"]
    centre_activity = schema.tables["REF_CENTRE_ACTIVITY"]
    centre_activity_preference = schema.tables["REF_ACTIVITY_PREFERENCE"]
    with engine.begin() as conn:
        conn.execute(insert(patient).values(PatientID=PATIENT_ID))
        for centre_activity_id, (label, start) in enumerate(STARTDATE_CASES.items(), start=1):
            conn.execute(insert(activity).values(ActivityID=centre_activity_id, ActivityTitle=label))
            conn.execute(insert(centre_activity).values(
                CentreActivityID=centre_activity_id, ActivityID=centre_activity_id,
                IsGroup=False, IsDeleted=False, IsCompulsory=False, IsFixed=False,
                FixedTimeSlots=None, MinDuration=30, MaxDuration=30, MinPeopleReq=1,
                StartDate=start, EndDate=FAR_FUTURE_END_DATE,
            ))
            conn.execute(insert(centre_activity_preference).values(
                CentreActivityPreferenceID=centre_activity_id, CentreActivityID=centre_activity_id,
                PatientID=PATIENT_ID, IsLike=is_like, IsDeleted=False,
            ))


class TestPatientPreferenceStartDateFiltering:
    """Same idea as the impact test above, but for PatientsView/PatientsUnpreferredView - shows
    the StartDate fix actually changes what preferences a patient gets."""

    @pytest.mark.parametrize(
        "view_cls, is_like, activity_id_col",
        [
            (PatientsView, 1, "PreferredActivityID"),
            (PatientsUnpreferredView, 0, "DispreferredActivityID"),
        ],
    )
    def test_activity_added_on_or_after_monday_is_still_included(self, view_cls, is_like, activity_id_col):
        engine = create_engine("sqlite:///:memory:")
        schema = views.DB.schema
        schema.create_all(engine)

        _seed_patient_preferences(engine, schema, is_like=is_like)

        with engine.connect() as conn:
            rows = conn.execute(view_cls.build_query()).mappings().all()

        id_to_label = {i: label for i, label in enumerate(STARTDATE_CASES, start=1)}
        returned_labels = {
            id_to_label[row[activity_id_col]] for row in rows if row[activity_id_col] is not None
        }

        # STARTS_ON_MONDAY and STARTS_MIDWEEK only show up because of the fix. Old code
        # would've only returned STARTS_BEFORE_WEEK.
        assert returned_labels == {"STARTS_BEFORE_WEEK", "STARTS_ON_MONDAY", "STARTS_MIDWEEK"}, (
            f"{view_cls.__name__} returned {returned_labels}; expected everything up to and "
            "including this week, STARTS_AFTER_WEEK excluded."
        )
