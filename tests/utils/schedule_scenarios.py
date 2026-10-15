"""
Random centres for the property tests and scripts/evaluate_gap_fill.py.
Everything comes from one random.Random, so a seed gives back the same scenario.
"""

import datetime
import random
import types
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pandas as pd

from tests.utils.scheduler_config import make_scheduler_config

WEEK_START = datetime.datetime(2024, 3, 18)  # a Monday
FAR_FUTURE = pd.Timestamp("2099-12-31")
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@dataclass
class Scenario:
    config: Dict[str, Any]
    views: Dict[str, pd.DataFrame]
    params: Dict[str, Any] = field(default_factory=dict)


def _df(columns: List[str], rows: Optional[List[list]] = None) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame({c: pd.Series([], dtype="object") for c in columns})
    return pd.DataFrame(rows, columns=columns)


def make_scenario(
    rng: random.Random,
    *,
    patients: int = 3,
    days: int = 5,
    slots: int = 12,
    pool_size: int = 8,
    flexible_share: float = 0.6,
    short_share: float = 0.4,
    compulsory: int = 2,
    like_rate: float = 0.3,
    dislike_rate: float = 0.15,
    exclusion_rate: float = 0.1,
    recommend_rate: float = 0.1,
    not_recommend_rate: float = 0.05,
) -> Scenario:
    open_days = DAY_ORDER[:days]
    config = make_scheduler_config(
        OPEN_DAYS=open_days, SLOTS_PER_DAY={d: slots for d in open_days}, DAYS=days,
        WORKING_HOURS={d.lower(): {"open": "09:00", "close": f"{9 + slots // 2:02d}:{'30' if slots % 2 else '00'}"} for d in open_days},
        TARGET_WEEKLY_GROUP_ACTIVITIES=0,
    )

    # compulsory: same slot every day, never overlapping (activity service enforces unique slots)
    taken, comp_rows = set(), []
    for i in range(compulsory):
        length = 1 if rng.random() < 0.5 else 2
        starts = [s for s in range(slots - length + 1) if not taken & set(range(s, s + length))]
        if not starts:
            break
        s = rng.choice(starts)
        taken |= set(range(s, s + length))
        comp_rows.append([f"Compulsory {i}", 1, ",".join(f"{d}-{s}" for d in range(days)), 30 * length])

    # individual pool
    pool_rows = []
    for i in range(pool_size):
        aid = 100 + i
        minutes = 30 if rng.random() < short_share else 60
        fixed = None
        if rng.random() >= flexible_share:
            fixed = ",".join(f"{rng.randrange(days)}-{rng.randrange(slots - minutes // 30 + 1)}" for _ in range(rng.randint(1, 2)))
        pool_rows.append([aid, f"Activity {i}", fixed, minutes, minutes, FAR_FUTURE, pd.Timestamp("2020-01-01")])

    likes, dislikes, excl, recs, not_recs = [], [], [], [], []
    for pid in range(1, patients + 1):
        for aid, title, fixed, minutes, *_ in pool_rows:
            r = rng.random()
            if r < like_rate:
                likes.append([pid, aid, FAR_FUTURE])
            elif r < like_rate + dislike_rate:
                dislikes.append([pid, aid, FAR_FUTURE])
            if rng.random() < exclusion_rate:
                end = None if rng.random() < 0.3 else WEEK_START + datetime.timedelta(days=rng.randrange(days), hours=23, minutes=59)
                excl.append([len(excl) + 1, aid, pid, "", end, title])
            r = rng.random()
            if r < recommend_rate:
                recs.append([aid, 0 if fixed is None else 1, minutes, title, fixed, pid, FAR_FUTURE])
            elif r < recommend_rate + not_recommend_rate:
                not_recs.append([aid, 0 if fixed is None else 1, title, pid, FAR_FUTURE])

    views = {
        "PatientsOnlyView": pd.DataFrame({"PatientID": list(range(1, patients + 1))}),
        "CompulsoryActivitiesOnlyView": _df(["ActivityTitle", "IsFixed", "FixedTimeSlots", "MinDuration"], comp_rows),
        "ActivitiesView": _df(["ActivityID", "ActivityTitle", "FixedTimeSlots", "MinDuration", "MaxDuration", "EndDate", "StartDate"], pool_rows),
        "PatientsView": _df(["PatientID", "PreferredActivityID", "ActivityEndDate"], likes),
        "PatientsUnpreferredView": _df(["PatientID", "DispreferredActivityID", "ActivityEndDate"], dislikes),
        "ActivitiesExcludedView": _df(["ActivityExclusionID", "ActivityID", "PatientID", "ExclusionRemarks", "EndDateTime", "ActivityTitle"], excl),
        "RecommendedActivitiesView": _df(["ActivityID", "IsFixed", "MinDuration", "ActivityTitle", "FixedTimeSlots", "PatientID", "ActivityEndDate"], recs),
        "DisrecommendedActivitiesView": _df(["ActivityID", "IsFixed", "ActivityTitle", "PatientID", "ActivityEndDate"], not_recs),
        "GroupActivitiesOnlyView": _df(["ActivityID", "CentreActivityID", "ActivityTitle", "IsFixed", "FixedTimeSlots", "MinPeopleReq", "MinDuration"]),
        "GroupActivitiesPreferenceView": _df(["CentreActivityID", "PatientID", "IsLike"]),
        "GroupActivitiesRecommendationView": _df(["CentreActivityID", "PatientID", "DoctorRecommendation"]),
        "GroupActivitiesExclusionView": _df(["CentreActivityID", "PatientID"]),
        "AdhocActivityView": _df(["AdhocID", "PatientID", "OldActivityTitle", "NewActivityTitle", "StartDate", "EndDate"]),
        "MedicationView": _df(["PatientID", "MedicationID", "PrescriptionName", "Dosage", "AdministerTime", "StartDateTime", "EndDateTime", "Instruction", "IsDeleted"]),
        "CaregiverAllocatedView": _df(["patientId", "caregiverId", "tempCaregiverId", "supervisorId"]),
        "ValidRoutineActivitiesView": _df(["PatientID", "ActivityID", "ActivityTitle", "FixedTimeSlots"]),
        "ExistingScheduleView": _df(["ScheduleID", "PatientID", "MedicationSchedule"]),
    }
    params = dict(patients=patients, days=days, slots=slots, pool_size=pool_size, flexible_share=flexible_share,
                  short_share=short_share, compulsory=compulsory)
    return Scenario(config, views, params)


@contextmanager
def patched(scenario: Scenario, strategy: str = "greedy"):
    """Views, config and 'now' set up for one scenario."""
    from pear_schedule.scheduler import explain
    from pear_schedule.scheduler.adhocScheduling import AdhocScheduler
    from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
    from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
    from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler, RecommendedRoutineActivityScheduler
    from pear_schedule.scheduler.medicationScheduling import medicationScheduler

    config = {**scenario.config, "GAP_FILL_STRATEGY": strategy}
    now = WEEK_START + datetime.timedelta(hours=8)

    class _Now(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    fake_dt = types.SimpleNamespace(datetime=_Now, date=datetime.date, timedelta=datetime.timedelta)
    with ExitStack() as stack:
        for name, df in scenario.views.items():
            stack.enter_context(patch(f"pear_schedule.db_utils.views.{name}.get_data", return_value=df))
        stack.enter_context(patch("pear_schedule.scheduler.individualScheduling.DB.get_engine", return_value=MagicMock()))
        for mod in ("individualScheduling", "adhocScheduling", "medicationScheduling"):
            stack.enter_context(patch(f"pear_schedule.scheduler.{mod}.datetime", fake_dt))
        stack.enter_context(patch.object(explain, "current_week_start", lambda: WEEK_START))
        for cls in (CompulsoryActivityScheduler, RecommendedRoutineActivityScheduler, GroupActivityScheduler,
                    PreferredActivityScheduler, AdhocScheduler, medicationScheduler):
            stack.enter_context(patch.object(cls, "config", config, create=True))
        yield config


def run(scenario: Scenario, strategy: str = "greedy"):
    """Build schedules for a scenario. Returns (schedules, trace, rule inputs)."""
    from pear_schedule.scheduler import explain, trace
    from pear_schedule.scheduler.utils import build_schedules

    with patched(scenario, strategy) as config:
        schedules = {}
        with trace.tracing() as t:
            build_schedules(config, schedules)
        inputs = explain.collect_rule_inputs(config, WEEK_START)
    return schedules, t, inputs
