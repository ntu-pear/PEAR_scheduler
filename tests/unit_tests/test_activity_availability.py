"""db_utils/availability.py and the views that use it."""

import datetime
import logging

import pandas as pd
import pytest
from sqlalchemy import Boolean, Column, Date, Integer, MetaData, String, Table, Time, create_engine, insert

from pear_schedule.db_utils import views
from pear_schedule.db_utils.availability import (
    apply_availability, availability_slots, format_slots, window_covers, windows_by_activity,
)
from pear_schedule.utils import DBTABLES

WEEK = datetime.datetime(2024, 3, 18)  # Monday
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MON, TUE, WED = 1, 2, 4

CONFIG = {
    "MIN_ACTIVITY_DURATION": 30,
    "DAY_OF_WEEK_ORDER": DAYS,
    "OPEN_DAYS": ["Monday", "Tuesday", "Wednesday"],
    "SLOTS_PER_DAY": {"Monday": 8, "Tuesday": 8, "Wednesday": 4},
    "WORKING_HOURS": {"monday": {"open": "09:00", "close": "13:00"}, "tuesday": {"open": "09:00", "close": "13:00"},
                      "wednesday": {"open": "10:00", "close": "12:00"}},
}


def _w(days, start, end, start_date=None, end_date=None):
    return {"DaysOfWeek": days, "StartTime": start, "EndTime": end, "StartDate": start_date, "EndDate": end_date}


def _slots(windows, minutes=30):
    return availability_slots(windows, minutes, WEEK, CONFIG)


class TestAvailabilitySlots:
    def test_fixed_window_is_one_start(self):
        assert _slots([_w(MON, "10:00", "11:00")], 60) == {(0, 2)}

    def test_longer_window_allows_every_start_that_fits(self):
        assert _slots([_w(MON, "10:00", "11:30")], 60) == {(0, 2), (0, 3)}
        assert _slots([_w(MON, "10:00", "11:30")], 30) == {(0, 2), (0, 3), (0, 4)}

    def test_days_bitmask(self):
        assert _slots([_w(MON | WED, "10:00", "10:30")]) == {(0, 2), (2, 0)}

    def test_each_day_uses_its_own_opening_time(self):
        # Wednesday opens at 10:00, so 10:00 is its slot 0
        assert _slots([_w(WED, "10:30", "11:00")]) == {(2, 1)}

    def test_closed_day_is_skipped(self):
        assert _slots([_w(16, "10:00", "10:30")]) == set()  # Friday, not open

    def test_window_past_closing_is_cut(self):
        assert _slots([_w(MON, "12:30", "14:00")]) == {(0, 7)}
        assert _slots([_w(MON, "12:30", "14:00")], 60) == set()

    def test_window_not_on_the_slot_grid(self):
        # 10:15-11:15 only fully holds 10:30-11:00
        assert _slots([_w(MON, "10:15", "11:15")]) == {(0, 3)}

    def test_date_range(self):
        assert _slots([_w(MON | TUE, "10:00", "10:30", start_date=datetime.date(2024, 3, 19))]) == {(1, 2)}
        assert _slots([_w(MON | TUE, "10:00", "10:30", end_date=datetime.date(2024, 3, 18))]) == {(0, 2)}
        assert _slots([_w(MON, "10:00", "10:30", end_date=datetime.date(2024, 3, 17))]) == set()

    def test_not_recurring_uses_its_dates(self):
        assert _slots([_w(0, "10:00", "10:30", start_date=datetime.date(2024, 3, 19))]) == {(1, 2)}
        assert _slots([_w(0, "10:00", "10:30", start_date=datetime.date(2024, 3, 18),
                          end_date=datetime.date(2024, 3, 20))]) == {(0, 2), (1, 2), (2, 0)}
        assert _slots([_w(0, "10:00", "10:30")]) == set()

    def test_time_types(self):
        for start, end in [(datetime.time(10), datetime.time(10, 30)), ("10:00:00", "10:30:00"),
                           (pd.Timedelta(hours=10), pd.Timedelta(hours=10, minutes=30))]:
            assert _slots([_w(MON, start, end)]) == {(0, 2)}

    def test_window_covers(self):
        assert window_covers(_w(TUE, "10:00", "11:00"), "Tuesday", datetime.date(2024, 3, 19), DAYS)
        assert not window_covers(_w(TUE, "10:00", "11:00"), "Monday", datetime.date(2024, 3, 18), DAYS)


def _activities(rows):
    return pd.DataFrame(rows, columns=["CentreActivityID", "ActivityTitle", "IsFixed", "FixedTimeSlots", "MinDuration"])


class TestApplyAvailability:
    def test_no_rows_left_as_is(self):
        df = _activities([[1, "Walk", 0, None, 30], [2, "Physio", 1, "0-2", 60]])
        out = apply_availability(df, {}, WEEK, CONFIG)
        assert out.equals(df)
        out = apply_availability(df, {3: [_w(MON, "10:00", "10:30")]}, WEEK, CONFIG)
        assert out.equals(df)

    def test_fixed_takes_its_slots_from_availability(self):
        df = _activities([[2, "Physio", "1", None, 60]])
        out = apply_availability(df, {2: [_w(MON | TUE, "11:00", "12:00")]}, WEEK, CONFIG)
        assert out["FixedTimeSlots"].tolist() == ["0-4,1-4"]

    def test_fixed_mismatch_keeps_fixed_slots_and_warns(self, caplog):
        df = _activities([[2, "Physio", 1, "0-2", 60]])
        with caplog.at_level(logging.WARNING):
            out = apply_availability(df, {2: [_w(MON, "11:00", "12:00")]}, WEEK, CONFIG)
        assert out["FixedTimeSlots"].tolist() == ["0-2"]
        assert "differs from FixedTimeSlots 0-2, keeping FixedTimeSlots" in caplog.text

    def test_fixed_with_expired_availability_is_kept(self, caplog):
        # staging had compulsory Vital Check AM with only expired test windows
        df = _activities([[3, "Vital Check AM", 1, "0-4,1-4", 30]])
        expired = [_w(MON, "09:00", "09:30", end_date=datetime.date(2024, 3, 1))]
        with caplog.at_level(logging.WARNING):
            out = apply_availability(df, {3: expired}, WEEK, CONFIG)
        assert out["FixedTimeSlots"].tolist() == ["0-4,1-4"]
        assert "none this week differs" in caplog.text

    def test_fixed_without_slots_and_no_window_this_week_is_dropped(self):
        df = _activities([[2, "Physio", 1, None, 60], [4, "Bingo", 1, "", 30]])
        out = apply_availability(df, {2: [_w(16, "11:00", "12:00")]}, WEEK, CONFIG)
        assert out.empty

    def test_fixed_without_slots_or_rows_is_dropped(self, caplog):
        df = _activities([[2, "Physio", 1, None, 60], [1, "Walk", 0, None, 30]])
        with caplog.at_level(logging.WARNING):
            out = apply_availability(df, {}, WEEK, CONFIG)
        assert out["ActivityTitle"].tolist() == ["Walk"]
        assert "no FixedTimeSlots and no availability" in caplog.text

    def test_matching_fixed_slots_no_warning(self, caplog):
        df = _activities([[2, "Physio", True, "0-4", 60]])
        with caplog.at_level(logging.WARNING):
            apply_availability(df, {2: [_w(MON, "11:00", "12:00")]}, WEEK, CONFIG)
        assert "differs" not in caplog.text

    def test_staging_rows_from_15_oct_change_nothing_fixed(self):
        """The availability on staging on 15 Oct: stale test windows that disagree with the timetable."""
        week = datetime.datetime(2026, 10, 12)
        six_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        config = {**CONFIG, "OPEN_DAYS": six_days, "SLOTS_PER_DAY": {d: 16 for d in six_days},
                  "WORKING_HOURS": {d.lower(): {"open": "09:00", "close": "17:00"} for d in six_days}}
        d = datetime.date
        windows = {
            2: [_w(31, "16:00", "17:00", d(2026, 1, 21), d(2026, 5, 31)), _w(0, "09:00", "10:00", d(2026, 1, 21), d(2026, 1, 31))],
            3: [_w(1, "09:00", "10:00", d(2026, 1, 21), d(2026, 5, 31))],
            5: [_w(3, "15:00", "16:00", d(2026, 1, 21), d(2026, 5, 31))],
            10: [_w(0, "09:00", "10:00", d(2026, 4, 30), d(2026, 5, 31))],
            21: [_w(31, "16:00", "16:30", d(2026, 4, 23), d(2027, 5, 31))],
        }
        df = _activities([
            [2, "Breathing exercise AM", 1, "0-2,1-2,2-2,3-2,4-2,5-2", 60], [3, "Vital Check AM", 1, "0-4,1-4,2-4,3-4,4-4", 60],
            [5, "tee break", 1, "1-12,3-12", 60], [10, "ART & CRAFT", 1, "3-14", 60], [21, "Sort Cards", 1, "2-2", 30],
        ])
        out = apply_availability(df, windows, week, config)
        assert out.equals(df)

    def test_flexible_limited_to_its_windows(self):
        df = _activities([[1, "Walk", 0, None, 30]])
        out = apply_availability(df, {1: [_w(TUE, "09:00", "10:00")]}, WEEK, CONFIG)
        assert out["FixedTimeSlots"].tolist() == ["1-0,1-1"]

    def test_flexible_left_alone_when_told(self):
        df = _activities([[1, "Bingo", 0, None, 60]])
        out = apply_availability(df, {1: [_w(TUE, "09:00", "10:00")]}, WEEK, CONFIG, restrict_flexible=False)
        assert out.equals(df)

    def test_nothing_this_week_is_dropped(self):
        df = _activities([[1, "Walk", 0, None, 30], [2, "Reading", 0, None, 30]])
        out = apply_availability(df, {1: [_w(16, "09:00", "10:00")]}, WEEK, CONFIG)
        assert out["ActivityTitle"].tolist() == ["Reading"]

    def test_input_not_changed(self):
        df = _activities([[1, "Walk", 0, None, 30]])
        apply_availability(df, {1: [_w(TUE, "09:00", "10:00")]}, WEEK, CONFIG)
        assert df["FixedTimeSlots"].tolist() == [None]

    def test_windows_by_activity_skips_deleted(self):
        rows = pd.DataFrame([
            {"CentreActivityID": 1, "IsDeleted": False, **_w(MON, "09:00", "10:00")},
            {"CentreActivityID": 1, "IsDeleted": "1", **_w(TUE, "09:00", "10:00")},
            {"CentreActivityID": 2, **_w(MON, "09:00", "10:00")},
        ])
        out = windows_by_activity(rows)
        assert [w["DaysOfWeek"] for w in out[1]] == [MON]
        assert list(out) == [1, 2]

    def test_format_slots_sorted(self):
        assert format_slots({(1, 0), (0, 3), (0, 1)}) == "0-1,0-3,1-0"


DB_TABLES = DBTABLES(
    ACTIVITY_TABLE="REF_ACTIVITY", ACTIVITY_EXCLUSION_TABLE="REF_ACTIVITY_EXCLUSION",
    CENTRE_ACTIVITY_TABLE="REF_CENTRE_ACTIVITY", CENTRE_ACTIVITY_PREFERENCE_TABLE="REF_ACTIVITY_PREFERENCE",
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE="REF_ACTIVITY_RECOMMENDATION", PATIENT_TABLE="REF_PATIENT",
    ROUTINE_TABLE="REF_ACTIVITY_ROUTINE", SCHEDULE_TABLE="SCHEDULE", MEDICATION_SCHEDULE_TABLE="MEDICATION_SCHEDULE",
    MEDICATION_TABLE="REF_PATIENT_MEDICATION", ALLOCATION_TABLE="REF_PATIENT_ALLOCATION",
    CARE_CENTRE_TABLE="REF_CARE_CENTRE", ADHOC_TABLE="REF_ADHOC",
)


@pytest.fixture
def db(monkeypatch):
    schema = MetaData()
    activity = Table("REF_ACTIVITY", schema, Column("ActivityID", Integer, primary_key=True), Column("ActivityTitle", String))
    centre = Table(
        "REF_CENTRE_ACTIVITY", schema,
        Column("CentreActivityID", Integer, primary_key=True), Column("ActivityID", Integer),
        Column("IsGroup", Boolean), Column("IsDeleted", Boolean), Column("IsCompulsory", Boolean),
        Column("IsFixed", Boolean), Column("FixedTimeSlots", String), Column("MinDuration", Integer),
        Column("MaxDuration", Integer), Column("MinPeopleReq", Integer), Column("StartDate", Date), Column("EndDate", Date),
    )
    availability = Table(
        "REF_CENTRE_ACTIVITY_AVAILABILITY", schema,
        Column("CentreActivityAvailabilityID", Integer, primary_key=True), Column("CentreActivityID", Integer),
        Column("IsDeleted", Boolean), Column("DaysOfWeek", Integer), Column("StartTime", Time), Column("EndTime", Time),
        Column("StartDate", Date), Column("EndDate", Date),
    )
    engine = create_engine("sqlite:///:memory:")
    schema.create_all(engine)
    with engine.begin() as conn:
        for cid, title, fixed, slots, compulsory, group in [
            (1, "Walk", False, None, False, False), (2, "Puzzles", False, None, False, False),
            (3, "Exercise", True, "0-0", True, False), (4, "Bingo", False, None, False, True),
        ]:
            conn.execute(insert(activity).values(ActivityID=cid, ActivityTitle=title))
            conn.execute(insert(centre).values(
                CentreActivityID=cid, ActivityID=cid, IsGroup=group, IsDeleted=False, IsCompulsory=compulsory,
                IsFixed=fixed, FixedTimeSlots=slots, MinDuration=30, MaxDuration=30, MinPeopleReq=2 if group else 1,
                StartDate=datetime.date(2024, 1, 1), EndDate=datetime.date(2024, 12, 31),
            ))
        rows = [(1, 1, False, TUE, "09:00"), (2, 1, True, MON, "09:00"), (3, 3, False, MON, "10:00"), (4, 4, False, TUE, "09:00")]
        for aid, cid, deleted, days, start in rows:
            begin = datetime.datetime.strptime(start, "%H:%M")
            conn.execute(insert(availability).values(
                CentreActivityAvailabilityID=aid, CentreActivityID=cid, IsDeleted=deleted, DaysOfWeek=days,
                StartTime=begin.time(), EndTime=(begin + datetime.timedelta(minutes=30)).time(),
            ))
    monkeypatch.setattr(views.DB, "schema", schema, raising=False)
    monkeypatch.setattr(views, "get_week_start", lambda: WEEK)
    monkeypatch.setattr(views, "get_week_end", lambda: WEEK + datetime.timedelta(days=6, hours=23, minutes=59))
    return engine


def _view_data(engine, view, on=True):
    view.init_app({"DB_TABLES": DB_TABLES, "USE_ACTIVITY_AVAILABILITY": on, **CONFIG})
    views.CentreActivityAvailabilityView.init_app({"DB_TABLES": DB_TABLES, **CONFIG})
    with engine.connect() as conn:
        df = view.get_data(conn=conn)
    return dict(zip(df["ActivityTitle"], df["FixedTimeSlots"]))


class TestViewsWithAvailability:
    def test_off_by_default(self, db):
        assert _view_data(db, views.ActivitiesView, on=False) == {"Walk": None, "Puzzles": None}

    def test_activities_view(self, db):
        # deleted Monday row ignored, Puzzles has none so stays flexible
        assert _view_data(db, views.ActivitiesView) == {"Walk": "1-0", "Puzzles": None}

    def test_compulsory_view_keeps_its_fixed_slots(self, db):
        # its 10:00 Monday window disagrees with 0-0, FixedTimeSlots wins
        assert _view_data(db, views.CompulsoryActivitiesOnlyView) == {"Exercise": "0-0"}

    def test_flexible_group_left_alone(self, db):
        assert _view_data(db, views.GroupActivitiesOnlyView) == {"Bingo": None}

    def test_routines_never_use_it(self):
        assert not views.ValidRoutineActivitiesView.uses_availability

    def test_without_a_connection(self, db, monkeypatch):
        monkeypatch.setattr(views.DB, "get_engine", lambda: db, raising=False)
        views.ActivitiesView.init_app({"DB_TABLES": DB_TABLES, "USE_ACTIVITY_AVAILABILITY": True, **CONFIG})
        views.CentreActivityAvailabilityView.init_app({"DB_TABLES": DB_TABLES, **CONFIG})
        df = views.ActivitiesView.get_data()
        assert dict(zip(df["ActivityTitle"], df["FixedTimeSlots"])) == {"Walk": "1-0", "Puzzles": None}

    def test_only_a_real_true_turns_it_on(self, db):
        # a string from a bad config isn't enough
        assert _view_data(db, views.ActivitiesView, on="false") == {"Walk": None, "Puzzles": None}


class TestSchedulingWithAvailability:
    """Whole pipeline on random centres, windows applied the way the views would."""

    @pytest.mark.parametrize("seed", range(6))
    @pytest.mark.parametrize("strategy", ["greedy", "optimal"])
    def test_activities_only_land_in_their_windows(self, seed, strategy):
        import random

        from pear_schedule.scheduler.invariants import base_title, check_rules
        from tests.utils.schedule_scenarios import WEEK_START, make_scenario, run

        rng = random.Random(seed)
        scenario = make_scenario(rng, patients=4, days=5, slots=12, pool_size=8, flexible_share=1.0, recommend_rate=0.3)
        config = scenario.config
        windows = {}
        for aid in scenario.views["ActivitiesView"]["ActivityID"]:
            if rng.random() < 0.6:
                start = 9 + rng.randrange(4)
                windows[aid] = [_w(1 << rng.randrange(5), f"{start:02d}:00", f"{start + 2:02d}:00")]
        for name in ("ActivitiesView", "RecommendedActivitiesView"):
            df = scenario.views[name].copy()
            df["CentreActivityID"] = df["ActivityID"]
            df["IsFixed"] = 0
            scenario.views[name] = apply_availability(df, windows, WEEK_START, config)

        schedules, _, inputs = run(scenario, strategy)

        allowed = {}
        for _, r in scenario.views["ActivitiesView"].iterrows():
            if r["ActivityID"] in windows:
                allowed[r["ActivityTitle"]] = availability_slots(windows[r["ActivityID"]], r["MinDuration"], WEEK_START, config)
        dropped = {r["ActivityTitle"] for _, r in scenario.views["ActivitiesView"].iterrows()} ^ \
                  {f"Activity {i}" for i in range(8)}
        for days in schedules.values():
            for d, day in enumerate(days):
                titles = [base_title(v) for v in day]
                for s, t in enumerate(titles):
                    assert t not in dropped
                    if t in allowed and (s == 0 or titles[s - 1] != t):
                        assert (d, s) in allowed[t], f"{t} at {(d, s)}, allowed {sorted(allowed[t])}"
        violations = check_rules(schedules, inputs)
        # greedy can leave avoidable Free and Easy (R8), nothing else
        assert [v for v in violations if strategy == "optimal" or v.rule != "R8"] == []

