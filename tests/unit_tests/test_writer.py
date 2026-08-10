"""
Tests for writer.py schedule labels.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from configprod import DAY_TIMESLOTS
from pear_schedule.db_utils import writer as writer_module
from pear_schedule.db_utils.writer import ScheduleWriter
from tests.utils.scheduler_config import make_scheduler_config


class _FakeMedicationScheduleRef:
    def reformatMedicationScheduleData(self, _cls):
        return {}


def _config(**overrides):
    open_days = overrides.pop("OPEN_DAYS", ["Monday", "Tuesday"])
    cfg = make_scheduler_config(OPEN_DAYS=open_days, **overrides)
    cfg["DB_TABLES"] = SimpleNamespace(SCHEDULE_TABLE="SCHEDULE")
    return cfg


def _write(patientSchedules, config, monkeypatch):
    """Runs ScheduleWriter.write() with the DB mocked out."""
    schedule_table = MagicMock()
    fake_schema = MagicMock()
    fake_schema.tables = {"SCHEDULE": schedule_table}
    monkeypatch.setattr(writer_module.DB, "schema", fake_schema, raising=False)
    monkeypatch.setattr(ScheduleWriter, "config", config, raising=False)

    with patch.object(writer_module.ExistingScheduleView, "get_data", return_value=pd.DataFrame()):
        conn = MagicMock()
        result = ScheduleWriter.write(
            patientSchedules=patientSchedules,
            medicationScheduleRef=_FakeMedicationScheduleRef(),
            conn=conn,
            overwriteExisting=False,
        )
    return result, schedule_table


def _inserted_schedule_data(schedule_table):
    return schedule_table.insert.return_value.values.call_args[0][0]


class TestScheduleLabeling:
    def test_slots_are_keyed_by_day_timeslots_in_order(self, monkeypatch):
        config = _config(
            SLOTS_PER_DAY={"Monday": 2, "Tuesday": 2},
            WORKING_HOURS={
                "monday": {"open": "09:00", "close": "10:00"},
                "tuesday": {"open": "09:00", "close": "10:00"},
            },
        )
        patientSchedules = {"1": [["Morning Walk", ""], ["", "Art Class"]]}

        result, schedule_table = _write(patientSchedules, config, monkeypatch)

        assert result is True
        schedule_data = _inserted_schedule_data(schedule_table)
        assert json.loads(schedule_data["Monday"]) == {
            "09:00-09:30": "Morning Walk",
            "09:30-10:00": "Free and Easy",
        }
        assert json.loads(schedule_data["Tuesday"]) == {
            "09:00-09:30": "Free and Easy",
            "09:30-10:00": "Art Class",
        }

    def test_empty_activity_string_becomes_free_and_easy(self, monkeypatch):
        config = _config(
            OPEN_DAYS=["Monday"],
            SLOTS_PER_DAY={"Monday": 1},
            WORKING_HOURS={"monday": {"open": "09:00", "close": "09:30"}},
        )
        patientSchedules = {"1": [[""]]}

        result, schedule_table = _write(patientSchedules, config, monkeypatch)

        assert result is True
        schedule_data = _inserted_schedule_data(schedule_table)
        assert json.loads(schedule_data["Monday"]) == {"09:00-09:30": "Free and Easy"}

    def test_day_needing_more_slots_than_day_timeslots_no_longer_crashes(self, monkeypatch):
        """Checks that writer no longer depends on the hardcoded DAY_TIMESLOTS list."""
        config = _config(
            OPEN_DAYS=["Monday"],
            SLOTS_PER_DAY={"Monday": 3},
            WORKING_HOURS={"monday": {"open": "09:00", "close": "10:30"}},
            DAY_TIMESLOTS=["09:00-09:30", "09:30-10:00"],  # stale, should be ignored now
        )
        patientSchedules = {"1": [["A", "B", "C"]]}

        result, schedule_table = _write(patientSchedules, config, monkeypatch)

        assert result is True
        schedule_data = _inserted_schedule_data(schedule_table)
        assert json.loads(schedule_data["Monday"]) == {
            "09:00-09:30": "A",
            "09:30-10:00": "B",
            "10:00-10:30": "C",
        }
