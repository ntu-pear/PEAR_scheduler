"""
services/care_centre_util.py: care centre working hours from Activity service,
with REF_CARE_CENTRE as fallback. No HTTP or DB.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects import mssql

from pear_schedule.services import care_centre_util as util
from tests.utils.scheduler_config import make_scheduler_config

WEEKDAY_HOURS = {
    **{d: {"open": "09:00", "close": "17:00"} for d in ["monday", "tuesday", "wednesday", "thursday", "friday"]},
    "saturday": {"open": None, "close": None},
    "sunday": {"open": None, "close": None},
}


def _hours(**changes):
    hours = json.loads(json.dumps(WEEKDAY_HOURS))
    hours.update(changes)
    return hours


def _config(**overrides):
    cfg = make_scheduler_config(
        GROUP_TIMESLOT_MAPPING=overrides.pop("GROUP_TIMESLOT_MAPPING", ["Monday 10:00", "Friday 16:00"]),
        **overrides,
    )
    cfg["CARE_CENTRE_ID"] = 1
    cfg["ACTIVITY_SERVICE_URL"] = "http://activity:8000"
    cfg["DB_TABLES"] = SimpleNamespace(CARE_CENTRE_TABLE="REF_CARE_CENTRE")
    return cfg


def _response(status=200, body=None):
    resp = MagicMock()
    resp.json.return_value = body
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return resp


class TestIsValidWorkingHours:
    def test_valid(self):
        assert util.is_valid_working_hours(_hours())

    @pytest.mark.parametrize("hours", [
        None,
        {"monday": {"open": "09:00", "close": "17:00"}},  # missing days
        _hours(monday={"open": "09:00", "close": None}),  # only one side set
        _hours(monday={"open": "9am", "close": "17:00"}),  # bad format
        _hours(monday={"open": "17:00", "close": "09:00"}),  # closes before opening
        _hours(monday="09:00-17:00"),  # not a dict
    ])
    def test_invalid(self, hours):
        assert not util.is_valid_working_hours(hours)


class TestFetchWorkingHours:
    def test_returns_hours_from_activity_service(self, monkeypatch):
        calls = []
        monkeypatch.setattr(util.requests, "get", lambda url, timeout: calls.append(url) or _response(body={"id": 1, "working_hours": _hours()}))
        assert util.fetch_working_hours("http://activity:8000/", 1) == _hours()
        assert calls == ["http://activity:8000/api/v1/care_centres/1/working_hours"]

    def test_no_url_skips_request(self, monkeypatch):
        monkeypatch.setattr(util.requests, "get", MagicMock(side_effect=AssertionError("should not be called")))
        assert util.fetch_working_hours("", 1) is None

    @pytest.mark.parametrize("get", [
        MagicMock(side_effect=requests.Timeout("timed out")),
        MagicMock(side_effect=requests.ConnectionError("refused")),
        MagicMock(return_value=_response(status=404)),
        MagicMock(return_value=_response(body={"working_hours": {"monday": {}}})),  # invalid shape
        MagicMock(return_value=_response(body=None)),
    ])
    def test_returns_none_when_unavailable_or_invalid(self, monkeypatch, get):
        monkeypatch.setattr(util.requests, "get", get)
        assert util.fetch_working_hours("http://activity:8000", 1) is None


class TestSaveWorkingHours:
    def test_updates_the_centre_row(self, monkeypatch):
        schema = MetaData()
        Table("REF_CARE_CENTRE", schema, Column("id", Integer, primary_key=True), Column("working_hours", String))
        monkeypatch.setattr(util.DB, "schema", schema, raising=False)
        conn = MagicMock()
        conn.execute.return_value = SimpleNamespace(rowcount=1)
        engine = MagicMock()
        engine.begin.return_value.__enter__.return_value = conn
        monkeypatch.setattr(util.DB, "get_engine", lambda: engine)

        util.save_working_hours(_config(), _hours())

        sql = str(conn.execute.call_args[0][0].compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))
        assert sql.startswith("UPDATE [REF_CARE_CENTRE] SET working_hours=")
        assert "WHERE [REF_CARE_CENTRE].id = 1" in sql


class TestLoadWorkingHours:
    def test_uses_activity_service_and_saves_copy(self, monkeypatch):
        saved = []
        monkeypatch.setattr(util, "fetch_working_hours", lambda url, cid: _hours())
        monkeypatch.setattr(util, "save_working_hours", lambda cfg, hours: saved.append(hours))
        assert util.load_working_hours(_config()) == _hours()
        assert saved == [_hours()]

    def test_falls_back_to_saved_copy(self, monkeypatch):
        monkeypatch.setattr(util, "fetch_working_hours", lambda url, cid: None)
        monkeypatch.setattr(util.CareCentreView, "get_data", classmethod(lambda cls: pd.DataFrame({"WorkingHours": [json.dumps(_hours())]})))
        assert util.load_working_hours(_config()) == _hours()

    def test_save_failure_still_returns_fetched_hours(self, monkeypatch):
        monkeypatch.setattr(util, "fetch_working_hours", lambda url, cid: _hours())
        monkeypatch.setattr(util, "save_working_hours", MagicMock(side_effect=Exception("db down")))
        assert util.load_working_hours(_config()) == _hours()

    def test_no_saved_copy_raises(self, monkeypatch):
        monkeypatch.setattr(util, "fetch_working_hours", lambda url, cid: None)
        monkeypatch.setattr(util.CareCentreView, "get_data", classmethod(lambda cls: pd.DataFrame(columns=["WorkingHours"])))
        with pytest.raises(Exception, match="No care centre"):
            util.load_working_hours(_config())


class TestApplyAndRefresh:
    def _use_hours(self, monkeypatch, hours):
        monkeypatch.setattr(util, "load_working_hours", lambda cfg: hours)

    def test_apply_sets_hour_based_config(self, monkeypatch):
        self._use_hours(monkeypatch, _hours(saturday={"open": "09:00", "close": "12:00"}))
        cfg = _config()
        util.apply_centre_hours(cfg)
        assert cfg["OPEN_DAYS"] == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        assert cfg["SLOTS_PER_DAY"]["Monday"] == 16
        assert cfg["SLOTS_PER_DAY"]["Saturday"] == 6
        assert cfg["GROUP_TIMESLOT_MAPPING"] == [(0, 2), (4, 14)]

    def test_refresh_twice_reuses_original_mapping_strings(self, monkeypatch):
        # the live mapping holds converted tuples, so revalidating it would crash
        self._use_hours(monkeypatch, _hours())
        cfg = _config()
        util.apply_centre_hours(cfg)
        self._use_hours(monkeypatch, _hours(monday={"open": "08:00", "close": "17:00"}))
        assert util.refresh_centre_hours(cfg) is True
        assert cfg["GROUP_TIMESLOT_MAPPING"] == [(0, 4), (4, 14)]
        assert cfg["WORKING_HOURS"]["monday"]["open"] == "08:00"

    def test_refresh_keeps_old_config_when_group_slot_no_longer_fits(self, monkeypatch):
        self._use_hours(monkeypatch, _hours())
        cfg = _config()
        util.apply_centre_hours(cfg)
        before = {k: cfg[k] for k in ("OPEN_DAYS", "WORKING_HOURS", "SLOTS_PER_DAY", "GROUP_TIMESLOT_MAPPING")}

        self._use_hours(monkeypatch, _hours(friday={"open": "09:00", "close": "15:00"}))  # 16:00 group slot out of hours
        assert util.refresh_centre_hours(cfg) is False
        assert {k: cfg[k] for k in before} == before

    def test_refresh_keeps_old_config_when_hours_unavailable(self, monkeypatch):
        self._use_hours(monkeypatch, _hours())
        cfg = _config()
        util.apply_centre_hours(cfg)
        monkeypatch.setattr(util, "load_working_hours", MagicMock(side_effect=Exception("no care centre")))
        assert util.refresh_centre_hours(cfg) is False
        assert cfg["OPEN_DAYS"] == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    def test_apply_raises_at_startup_when_group_slot_does_not_fit(self, monkeypatch):
        self._use_hours(monkeypatch, _hours(monday={"open": "11:00", "close": "17:00"}))
        with pytest.raises(Exception, match="out of bounds"):
            util.apply_centre_hours(_config())
