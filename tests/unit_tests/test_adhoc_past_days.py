"""
/adhoc/ must not change days that already happened. No DB, no HTTP client.
"""

import datetime
import json
import types
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pear_schedule.api import schedule_router
from pear_schedule.api.utils import AdHocRequest, dropPastDays
from tests.utils.scheduler_config import make_scheduler_config

WEDNESDAY = datetime.date(2024, 3, 20)
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class TestDropPastDays:
    def test_range_from_today_is_unchanged(self):
        assert dropPastDays("2024-03-20", "2024-03-22", WEDNESDAY) == ("2024-03-20", "2024-03-22")

    def test_start_in_the_past_moves_to_today(self):
        assert dropPastDays("2024-03-18T00:00:00", "2024-03-22", WEDNESDAY) == ("2024-03-20", "2024-03-22")

    def test_range_ending_today_keeps_today(self):
        assert dropPastDays("2024-03-18", "2024-03-20", WEDNESDAY) == ("2024-03-20", "2024-03-20")

    def test_range_all_in_the_past(self):
        assert dropPastDays("2024-03-18", "2024-03-19", WEDNESDAY) is None


class TestAdhocRoute:
    def _run(self, monkeypatch, start, end):
        fake_dt = types.SimpleNamespace(date=types.SimpleNamespace(today=lambda: WEDNESDAY), datetime=datetime.datetime)
        monkeypatch.setattr(schedule_router, "datetime", fake_dt)
        week = pd.DataFrame([{
            "ScheduleID": 1, "PatientID": 1,
            "StartDate": pd.Timestamp("2024-03-18"), "EndDate": pd.Timestamp("2024-03-24 23:59"),
            **{d: json.dumps({"09:00-10:00": "Mahjong"}) for d in DAYS},
        }])
        names = {1: "Mahjong", 2: "Karaoke"}
        update = MagicMock(return_value={"Status": "200", "Message": "ok", "Data": ""})
        request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(config={**make_scheduler_config(), "DB_TABLES": MagicMock()})))
        with patch.object(schedule_router.ActivityNameView, "get_data",
                          side_effect=lambda arg1: pd.DataFrame({"ActivityTitle": [names[arg1]]})), \
             patch.object(schedule_router.AdHocScheduleView, "get_data", return_value=week), \
             patch.object(schedule_router.DB, "schema", MagicMock(), create=True), \
             patch.object(schedule_router.ScheduleWriter, "updateDB", update):
            res = schedule_router.adhoc_change_schedule(
                request, AdHocRequest(OldActivityID=1, NewActivityID=2, PatientID=1, StartDate=start, EndDate=end))
        return json.loads(res.body), update

    def test_past_days_are_left_alone(self, monkeypatch):
        body, update = self._run(monkeypatch, "2024-03-18", "2024-03-22")
        assert body["Status"] == "200"
        _, written, chosen = update.call_args.args
        assert chosen == ["Wednesday", "Thursday", "Friday"]
        assert "Monday" not in written.columns and "Tuesday" not in written.columns

    def test_all_past_is_refused(self, monkeypatch):
        body, update = self._run(monkeypatch, "2024-03-18", "2024-03-19")
        assert body["Status"] == "400"
        update.assert_not_called()

    def test_future_range_still_works(self, monkeypatch):
        body, update = self._run(monkeypatch, "2024-03-21", "2024-03-23")
        assert update.call_args.args[2] == ["Thursday", "Friday", "Saturday"]

    def test_change_is_noted_until_its_event_arrives(self, monkeypatch):
        from pear_schedule.scheduler import repair
        monkeypatch.setattr(repair, "_adhoc_noted", [])
        self._run(monkeypatch, "2024-03-18", "2024-03-22")
        assert repair._adhoc_noted == [(1, datetime.date(2024, 3, d), "Mahjong", "Karaoke") for d in (20, 21, 22)]
