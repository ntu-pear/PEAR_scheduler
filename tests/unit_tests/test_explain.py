"""
scheduler/explain.py and the explain_schedule CLI, on the mocked pipeline from test_build_schedules.
"""

import json
import types
from unittest.mock import MagicMock, patch

import pytest

from pear_schedule.scheduler import explain
from pear_schedule.scheduler import trace
from tests.unit_tests.test_build_schedules import SCHEDULER_CLASSES, _config, _freeze_now, _patch_all_views


def _explain(monkeypatch, patient_ids=None):
    cfg = _config()
    for _, cls in SCHEDULER_CLASSES:
        monkeypatch.setattr(cls, "config", cfg, raising=False)
    with _freeze_now(monkeypatch), _patch_all_views():
        monkeypatch.setattr(explain, "current_week_start", lambda: __import__("datetime").datetime(2024, 3, 18))
        return explain.run_explanation(cfg, patient_ids)


class TestParseSlots:
    def test_parses_day_slot_pairs(self):
        assert explain.parse_slots("0-1,2-3") == frozenset({(0, 1), (2, 3)})

    @pytest.mark.parametrize("value", [None, "", "  ", "None", "nan"])
    def test_flexible_activity_has_no_slots(self, value):
        assert explain.parse_slots(value) == frozenset()


class TestRunExplanation:
    def test_is_json_serialisable(self, monkeypatch):
        json.dumps(_explain(monkeypatch))

    def test_every_slot_says_which_stage_placed_it(self, monkeypatch):
        result = _explain(monkeypatch)
        for pid, p in result["patients"].items():
            for day in p["days"]:
                assert len(day["labels"]) == len(day["slots"])
                for slot in day["slots"]:
                    assert slot["placed_by"] in explain.STAGE_ORDER, (pid, day["day"], slot)

    def test_known_placements(self, monkeypatch):
        monday = _explain(monkeypatch)["patients"]["1"]["days"][0]
        assert monday["day"] == "Monday"
        assert monday["labels"][0] == "09:00-09:30"
        slot0, slot1 = monday["slots"][0], monday["slots"][1]
        # compulsory slot replaced by adhoc, then medication appended
        assert [h["stage"] for h in slot0["history"]] == ["compulsory", "adhoc", "medication"]
        assert slot0["placed_by"] == "adhoc"
        assert slot0["activity"] == "Adhoc Replacement Activity"
        assert slot1["placed_by"] == "recommended_routine"
        assert any(e["reason"] == "most_constrained_fixed_slot" for e in slot1["events"])

    def test_adhoc_override_is_not_reported_as_missing_compulsory(self, monkeypatch):
        result = _explain(monkeypatch)
        assert "R4" not in result["summary"]["violations_by_rule"]

    def test_free_and_easy_slots_are_classified(self, monkeypatch):
        # no individual activities in the mock, nothing is avoidable
        result = _explain(monkeypatch)
        fe = result["summary"]["free_and_easy"]
        assert fe["total"] > 0
        assert fe["avoidable_logic"] == 0
        assert fe["avoidable_rearranging_gap_fill"] == 0
        assert fe["unavoidable_by_reason"] == {"no_eligible_activities": fe["total"]}
        for day in result["patients"]["2"]["days"]:
            for slot in day["slots"]:
                if slot["activity"] == "Free and Easy":
                    assert slot["free_and_easy"] == "no_eligible_activities"

    def test_patient_filter(self, monkeypatch):
        result = _explain(monkeypatch, patient_ids=[2])
        assert list(result["patients"]) == ["2"]
        assert result["summary"]["patients"] == 2  # summary still covers the whole run

    def test_format_text_summarises_and_lists_slots(self, monkeypatch):
        result = _explain(monkeypatch)
        text = explain.format_text(result, [2])
        assert "Week of 2024-03-18: 2 patients" in text
        assert "Free and Easy:" in text
        assert "Patient 2" in text and "Patient 1:" not in text
        assert "DATA: no_eligible_activities" in text

    def test_nan_becomes_null(self):
        import numpy as np
        assert explain._jsonable({"a": float("nan"), "b": np.float64("inf"), "c": np.int64(3)}) == {"a": None, "b": None, "c": 3}
        json.loads(json.dumps(explain._jsonable([float("nan")]), allow_nan=False))

    def test_slot_minutes_for_the_viewer(self, monkeypatch):
        assert _explain(monkeypatch)["slot_minutes"] == 30


class TestNames:
    def test_add_names(self):
        result = {"patients": {"1": {}, "2": {}}}
        explain.add_names(result, {1: "Mdm Tan"})
        assert result["patients"]["1"]["name"] == "Mdm Tan"
        assert result["patients"]["2"]["name"] is None

    def test_no_names_by_default(self, monkeypatch):
        assert all("name" not in p for p in _explain(monkeypatch)["patients"].values())

    def test_patient_names_prefers_preferred_name(self, monkeypatch):
        import sqlalchemy as sa
        from pear_schedule.db import DB

        engine = sa.create_engine("sqlite://")
        meta = sa.MetaData()
        table = sa.Table("REF_PATIENT", meta, sa.Column("PatientID", sa.Integer), sa.Column("Name", sa.String),
                         sa.Column("PreferredName", sa.String))
        meta.create_all(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), [
                {"PatientID": 1, "Name": "Tan Ah Mei", "PreferredName": "Mdm Tan"},
                {"PatientID": 2, "Name": " Lim Boon ", "PreferredName": None},
            ])
        monkeypatch.setattr(DB, "schema", meta, raising=False)
        monkeypatch.setattr(DB, "get_engine", classmethod(lambda cls: engine))
        cfg = {"DB_TABLES": types.SimpleNamespace(PATIENT_TABLE="REF_PATIENT")}
        assert explain.patient_names(cfg) == {1: "Mdm Tan", 2: "Lim Boon"}


class TestDumpHtml:
    def _page(self, tmp_path, explanation, viewer=explain.VIEWER):
        out = tmp_path / "out.html"
        explain.dump_html(explanation, str(out), viewer)
        return out.read_text(encoding="utf-8")

    def test_data_goes_in_before_the_viewer_script(self, tmp_path):
        page = self._page(tmp_path, {"week_start": "2024-03-18", "patients": {}})
        assert "<!-- EXPLAIN_DATA -->" not in page
        data_at = page.index("window.EXPLAIN_DATA = ")
        assert data_at < page.index("if (window.EXPLAIN_DATA)")
        assert '"week_start": "2024-03-18"' in page

    def test_title_cannot_close_the_script_tag(self, tmp_path):
        page = self._page(tmp_path, {"title": "</script><b>x"})
        assert "</script><b>x" not in page
        start = page.index("window.EXPLAIN_DATA = ") + len("window.EXPLAIN_DATA = ")
        assert json.loads(page[start:page.index(";</script>", start)]) == {"title": "</script><b>x"}

    def test_viewer_without_placeholder(self, tmp_path):
        viewer = tmp_path / "viewer.html"
        viewer.write_text("<html></html>")
        with pytest.raises(ValueError):
            self._page(tmp_path, {}, str(viewer))


class TestCollectRuleInputs:
    def test_group_recommendations_count(self, monkeypatch):
        """Group recommendations used to be ignored, so a recommended but disliked group activity was flagged R3."""
        cfg = _config()
        with _patch_all_views():
            inputs = explain.collect_rule_inputs(cfg, __import__("datetime").datetime(2024, 3, 18))
        # the mock recommends group activity 20 (Mahjong) to patients 1 and 2
        assert 20 in inputs.patients[1].recommended
        assert 20 in inputs.patients[2].recommended


class TestExplainScheduleCli:
    def _run(self, monkeypatch, args):
        import app

        fake_config = types.SimpleNamespace(
            DB_CONN_STR="x", GROUP_TIMESLOT_MAPPING=["Monday 10:00"], DAY_OF_WEEK_ORDER=["Monday"],
            MIN_ACTIVITY_DURATION=30,
        )
        writer = MagicMock()
        save = MagicMock()
        monkeypatch.setattr(app.DB, "init_app", MagicMock())
        monkeypatch.setattr(app.CareCentreView, "init_app", MagicMock())
        monkeypatch.setattr(app, "read_saved_working_hours", lambda: {"monday": {"open": "09:00", "close": "13:00"}})
        monkeypatch.setattr(app, "centre_hours_config", lambda cfg, hours: {"OPEN_DAYS": ["Monday"]})
        monkeypatch.setattr(app, "loadConfigs", MagicMock())
        monkeypatch.setattr(app.ScheduleWriter, "write", writer)
        monkeypatch.setattr("pear_schedule.services.care_centre_util.save_working_hours", save)
        run = MagicMock(return_value={"summary": {}, "patients": {}})
        with patch("pear_schedule.scheduler.explain.run_explanation", run), \
             patch("pear_schedule.scheduler.explain.format_text", return_value="report"):
            app.explain_schedule(fake_config, types.SimpleNamespace(patient=None, **args))
        writer.assert_not_called()
        save.assert_not_called()
        return run

    def test_never_writes_schedules_or_centre_hours(self, monkeypatch, tmp_path, capsys):
        out_file = tmp_path / "explain.json"
        self._run(monkeypatch, {"json": str(out_file)})
        assert json.loads(out_file.read_text()) == {"summary": {}, "patients": {}}
        assert "report" in capsys.readouterr().out

    def test_html_and_names(self, monkeypatch, tmp_path):
        out_file = tmp_path / "schedule.html"
        run = self._run(monkeypatch, {"json": None, "html": str(out_file), "with_names": True})
        assert run.call_args.kwargs["with_names"] is True
        assert "window.EXPLAIN_DATA = " in out_file.read_text(encoding="utf-8")

    def test_names_off_by_default(self, monkeypatch):
        import app

        monkeypatch.setattr("sys.argv", ["app.py", "explain_schedule", "-c", "configprod.py", "--html", "out.html"])
        args = app.parse_args()
        assert args.html == "out.html" and args.with_names is False
        run = self._run(monkeypatch, {"json": None, "html": None, "with_names": args.with_names})
        assert run.call_args.kwargs["with_names"] is False
