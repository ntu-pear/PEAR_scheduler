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
    def test_never_writes_schedules_or_centre_hours(self, monkeypatch, tmp_path, capsys):
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
        fake_result = {"summary": {}, "patients": {}}
        out_file = tmp_path / "explain.json"
        with patch("pear_schedule.scheduler.explain.run_explanation", return_value=fake_result), \
             patch("pear_schedule.scheduler.explain.format_text", return_value="report"):
            app.explain_schedule(fake_config, types.SimpleNamespace(patient=None, json=str(out_file)))

        writer.assert_not_called()
        save.assert_not_called()
        assert json.loads(out_file.read_text()) == fake_result
        assert "report" in capsys.readouterr().out
