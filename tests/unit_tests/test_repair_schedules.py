"""
repair_schedules and the regenerate switch. Views, DB and the adhoc/medication stages are mocked.
"""

import datetime
import json
from unittest.mock import MagicMock, patch

import pandas as pd

from pear_schedule.api import schedule_router
from pear_schedule.scheduler import repair
from pear_schedule.scheduler.gapFill import PoolActivity
from pear_schedule.scheduler.invariants import PatientRules, RuleInputs
from tests.utils.scheduler_config import make_scheduler_config

CFG = make_scheduler_config(OPEN_DAYS=["Monday", "Tuesday"], SLOTS_PER_DAY={"Monday": 2, "Tuesday": 2})
WEEK = datetime.datetime(2024, 3, 18)


def _row(pid, monday, tuesday):
    labels = ["09:00-09:30", "09:30-10:00"]
    return {"PatientID": pid, "ScheduleID": pid,
            "Monday": json.dumps(dict(zip(labels, monday))), "Tuesday": json.dumps(dict(zip(labels, tuesday)))}


def _run(now, rows, dislikes=()):
    data = repair.RepairData(
        inputs=RuleInputs(
            slots_per_day=[2, 2], min_activity_duration=30, week_start=WEEK,
            pool=[PoolActivity(1, "Walk", 30), PoolActivity(2, "Puzzles", 30)],
            patients={1: PatientRules(dislikes=set(dislikes)), 2: PatientRules()},
            activity_ids_by_title={"Walk": 1, "Puzzles": 2},
        ),
        patient_ids=[1, 2, 3],
    )
    out = {}
    with patch.object(repair, "load_repair_data", return_value=data), \
         patch("pear_schedule.db.DB.get_engine", return_value=MagicMock()), \
         patch("pear_schedule.scheduler.individualScheduling.PreferredActivityScheduler.getMostUpdatedSchedules",
               return_value=pd.DataFrame(rows)), \
         patch("pear_schedule.scheduler.adhocScheduling.AdhocScheduler.fillSchedule"), \
         patch("pear_schedule.scheduler.medicationScheduling.medicationScheduler.fillSchedule", return_value="meds"):
        meds = repair.repair_schedules(CFG, out, now=now)
    return out, meds


def test_only_changed_and_new_patients_are_written():
    rows = [_row(1, ["Walk", "Puzzles"], ["Walk", "Puzzles"]), _row(2, ["Walk", "Puzzles"], ["Walk", "Puzzles"])]
    out, meds = _run(datetime.datetime(2024, 3, 18, 0, 0), rows, dislikes={1})
    assert meds == "meds"
    assert set(out) == {1, 3}  # 1 now dislikes Walk, 3 has no schedule yet
    assert "Walk" not in out[1][0] and "Walk" not in out[1][1]


def test_started_slots_keep_the_saved_text():
    saved = "Walk | Give Medication@0900: Aspirin(1)"
    rows = [_row(1, [saved, "Puzzles"], ["Walk", "Puzzles"]), _row(2, ["Walk", "Puzzles"], ["Walk", "Puzzles"])]
    out, _ = _run(datetime.datetime(2024, 3, 18, 9, 10), rows, dislikes={1})
    assert out[1][0][0] == saved  # 09:00 already started
    assert out[1][1][0] != "Walk"


def test_regenerate_uses_repair_only_when_asked():
    with patch.object(schedule_router, "repair_schedules", return_value="r") as rep, \
         patch.object(schedule_router, "build_schedules", return_value="b") as build:
        assert schedule_router._regenerate_build({"REGENERATE_MODE": "repair"}, {}) == "r"
        assert schedule_router._regenerate_build({"REGENERATE_MODE": "rebuild"}, {}) == "b"
        assert schedule_router._regenerate_build({}, {}) == "b"
    assert rep.call_count == 1 and build.call_count == 2
