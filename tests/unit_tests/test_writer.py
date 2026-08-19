"""
Tests for writer.py schedule labels.
"""

import datetime
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


def _freeze_today(monkeypatch, fixed_now):
    class FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    fake_datetime_module = SimpleNamespace(
        datetime=FixedDatetime, timedelta=datetime.timedelta, date=datetime.date
    )
    monkeypatch.setattr(writer_module, "datetime", fake_datetime_module)


class TestPastDayProtection:
    """Past days shouldn't get overwritten on regenerate."""

    def test_regenerate_does_not_overwrite_past_days(self, monkeypatch):
        config = _config(
            OPEN_DAYS=["Monday", "Tuesday", "Wednesday"],
            SLOTS_PER_DAY={"Monday": 1, "Tuesday": 1, "Wednesday": 1},
            WORKING_HOURS={
                "monday": {"open": "09:00", "close": "09:30"},
                "tuesday": {"open": "09:00", "close": "09:30"},
                "wednesday": {"open": "09:00", "close": "09:30"},
            },
        )
        # Wednesday 2024-03-20, same week as Monday 2024-03-18.
        _freeze_today(monkeypatch, datetime.datetime(2024, 3, 20, 10, 0, 0))

        schedule_table = MagicMock()
        fake_schema = MagicMock()
        fake_schema.tables = {"SCHEDULE": schedule_table}
        monkeypatch.setattr(writer_module.DB, "schema", fake_schema, raising=False)
        monkeypatch.setattr(ScheduleWriter, "config", config, raising=False)

        conn = MagicMock()
        result = ScheduleWriter.write(
            patientSchedules={"1": [["MonAct"], ["TueAct"], ["WedAct"]]},
            medicationScheduleRef=_FakeMedicationScheduleRef(),
            conn=conn,
            overwriteExisting=True,
            schedule_meta={"1": {"ScheduleID": 42}},
        )

        assert result is True
        updated_data = schedule_table.update.return_value.values.call_args[0][0]
        assert "Monday" not in updated_data
        assert "Tuesday" not in updated_data
        assert "Wednesday" in updated_data


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
