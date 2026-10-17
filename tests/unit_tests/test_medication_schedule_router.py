"""
Auth on /MedicationSchedule routes. No DB, no HTTP client.
"""

import datetime

import pytest
from fastapi import HTTPException

from pear_schedule.api import medication_schedule_router
from pear_schedule.api.auth_util import JWTPayload, get_current_user
from pear_schedule.api.utils import PatientServiceUnavailableException
import json

import pandas as pd

from pear_schedule.api.utils import MedicationNotAdministeredException
from pear_schedule.schemas.medication_schedule import MedicationScheduleUndo, MedicationScheduleUpdate
from pear_schedule.api.medication_schedule_router import require_dose_marker, require_supervisor


def _user(role):
    return JWTPayload(userId="1", fullName="Jane Doe", email="jane@example.com", roleName=role, sessionId="s1")


def _route(path):
    return next(r for r in medication_schedule_router.router.routes if r.path == path)


class TestRequireSupervisor:
    def test_supervisor_allowed(self):
        user = _user("SUPERVISOR")
        assert require_supervisor(user) is user

    @pytest.mark.parametrize("role", ["GUARDIAN", "DOCTOR", "ADMIN", "GAME THERAPIST"])
    def test_other_roles_get_403(self, role):
        with pytest.raises(HTTPException) as exc:
            require_supervisor(_user(role))
        assert exc.value.status_code == 403


class TestMedicationRoutesRequireAuth:
    # these routes used to have no auth at all
    def test_get_depends_on_require_dose_marker(self):
        assert require_dose_marker in [d.call for d in _route("/get/").dependant.dependencies]

    def test_undo_depends_on_require_supervisor(self):
        assert require_supervisor in [d.call for d in _route("/undo/").dependant.dependencies]

    def test_update_depends_on_require_dose_marker(self):
        assert require_dose_marker in [d.call for d in _route("/update/").dependant.dependencies]

    def test_require_supervisor_reads_the_bearer_token(self):
        sub_deps = [d.call for d in _route("/get/").dependant.dependencies[0].dependencies]
        assert get_current_user in sub_deps


class TestRequireDoseMarker:
    @pytest.mark.parametrize("role", ["CAREGIVER", "SUPERVISOR"])
    def test_caregivers_and_supervisors_allowed(self, role):
        user = _user(role)
        assert require_dose_marker(user) is user

    @pytest.mark.parametrize("role", ["GUARDIAN", "DOCTOR", "ADMIN", "GAME THERAPIST"])
    def test_other_roles_get_403(self, role):
        with pytest.raises(HTTPException) as exc:
            require_dose_marker(_user(role))
        assert exc.value.status_code == 403


def _body(**overrides):
    data = dict(PatientID=1, PrescriptionName="Paracetamol", AdministerDate=datetime.date(2026, 10, 15),
                AdministerTime="0900", Status="1", AdministeredBy="someone-else")
    data.update(overrides)
    return MedicationScheduleUpdate(**data)


class TestMarkDoseGiven:
    @pytest.fixture
    def calls(self, monkeypatch):
        seen = {"patient": [], "written": None}

        def fake_update(data, before_commit=None):
            seen["written"] = data
            before_commit(7)
            return datetime.datetime(2026, 10, 15, 9, 1)

        monkeypatch.setattr(medication_schedule_router.MedicationScheduleWrite, "update", fake_update)
        monkeypatch.setattr(medication_schedule_router, "record_administration",
                            lambda *a: seen["patient"].append(a))
        monkeypatch.setattr(medication_schedule_router, "caregiver_patients", lambda user_id: {1} if user_id == "1" else set())
        return seen

    def test_actor_comes_from_token_not_body(self, calls):
        medication_schedule_router.update_medication_schedule(None, _body(), _user("CAREGIVER"), "tok")
        assert calls["written"].AdministeredBy == "1"

    def test_patient_called_with_callers_token_before_commit(self, calls):
        medication_schedule_router.update_medication_schedule(None, _body(), _user("CAREGIVER"), "tok")
        assert calls["patient"] == [("tok", 7, datetime.date(2026, 10, 15), "0900")]

    def test_status_0_is_refused(self, calls):
        """It used to write who gave it and when onto a dose that wasn't given."""
        with pytest.raises(HTTPException) as exc:
            medication_schedule_router.update_medication_schedule(None, _body(Status="0"), _user("SUPERVISOR"), "tok")
        assert exc.value.status_code == 400
        assert calls["written"] is None and calls["patient"] == []

    def test_caregiver_cannot_mark_another_caregivers_patient(self, calls):
        with pytest.raises(HTTPException) as exc:
            medication_schedule_router.update_medication_schedule(None, _body(PatientID=2), _user("CAREGIVER"), "tok")
        assert exc.value.status_code == 403
        assert calls["written"] is None and calls["patient"] == []

    def test_supervisor_can_mark_any_patient(self, calls):
        medication_schedule_router.update_medication_schedule(None, _body(PatientID=2), _user("SUPERVISOR"), "tok")
        assert calls["written"].PatientID == 2

    def test_patient_down_is_503(self, monkeypatch):
        def failing_update(data, before_commit=None):
            before_commit(7)

        def patient_down(*a):
            raise PatientServiceUnavailableException("timeout")

        monkeypatch.setattr(medication_schedule_router.MedicationScheduleWrite, "update", failing_update)
        monkeypatch.setattr(medication_schedule_router, "record_administration", patient_down)
        monkeypatch.setattr(medication_schedule_router, "caregiver_patients", lambda user_id: {1})
        with pytest.raises(HTTPException) as exc:
            medication_schedule_router.update_medication_schedule(None, _body(), _user("CAREGIVER"), "tok")
        assert exc.value.status_code == 503


class TestCaregiverMedicationList:
    @pytest.fixture
    def today(self, monkeypatch):
        r = medication_schedule_router
        monkeypatch.setattr(r.medicationScheduler, "generateTodayMedSchedule", lambda: {"x": 1})
        monkeypatch.setattr(r.MedicationScheduleWrite, "write", lambda schedules: True)
        monkeypatch.setattr(r.TodayMedicationScheduleView, "get_data",
                            lambda *a, **k: pd.DataFrame({"PatientID": [1, 2, 3], "PrescriptionName": ["A", "B", "C"]}))
        monkeypatch.setattr(r, "caregiver_patients", lambda user_id: {1, 3} if user_id == "1" else set())

    def _patients(self, role):
        res = medication_schedule_router.get_medication_schedule(None, _user(role))
        return [row["PatientID"] for row in json.loads(res.body)]

    def test_caregiver_sees_only_their_patients(self, today):
        assert self._patients("CAREGIVER") == [1, 3]

    def test_supervisor_sees_everyone(self, today):
        assert self._patients("SUPERVISOR") == [1, 2, 3]


class TestNotGivenDoses:
    def test_not_given_dose_is_null_not_nat(self, monkeypatch):
        """Once one dose today is given the column is datetimes, the others used to come back as "NaT"."""
        r = medication_schedule_router
        given = datetime.datetime(2026, 10, 16, 9, 5)
        monkeypatch.setattr(r.medicationScheduler, "generateTodayMedSchedule", lambda: {"x": 1})
        monkeypatch.setattr(r.MedicationScheduleWrite, "write", lambda schedules: True)
        monkeypatch.setattr(r.TodayMedicationScheduleView, "get_data", lambda *a, **k: pd.DataFrame({
            "PatientID": [1, 1], "AdministerDate": pd.to_datetime(["2026-10-16", "2026-10-16"]),
            "ActualAdministerTime": pd.to_datetime([given, None]), "AdministeredBy": ["u1", None],
        }))
        rows = json.loads(r.get_medication_schedule(None, _user("SUPERVISOR")).body)
        assert rows[0]["ActualAdministerTime"] == "2026-10-16T09:05:00"
        assert rows[1]["ActualAdministerTime"] is None
        assert rows[1]["AdministerDate"] == "2026-10-16T00:00:00"


def _undo_body():
    return MedicationScheduleUndo(PatientID=1, PrescriptionName="Paracetamol",
                                  AdministerDate=datetime.date(2026, 10, 15), AdministerTime="0900")


class TestUndoDose:
    def _run(self, monkeypatch, undo, patient):
        monkeypatch.setattr(medication_schedule_router.MedicationScheduleWrite, "undo", undo)
        monkeypatch.setattr(medication_schedule_router, "undo_administration", patient)
        return medication_schedule_router.undo_medication_schedule(_undo_body(), _user("SUPERVISOR"), "tok")

    def test_patient_undone_with_callers_token_before_commit(self, monkeypatch):
        calls = []
        self._run(monkeypatch, lambda data, before_commit=None: before_commit(7), lambda *a: calls.append(a))
        assert calls == [("tok", 7, datetime.date(2026, 10, 15), "0900")]

    def test_patient_down_is_503(self, monkeypatch):
        def patient_down(*a):
            raise PatientServiceUnavailableException("timeout")

        with pytest.raises(HTTPException) as exc:
            self._run(monkeypatch, lambda data, before_commit=None: before_commit(7), patient_down)
        assert exc.value.status_code == 503

    def test_dose_not_given_is_400(self, monkeypatch):
        def not_given(data, before_commit=None):
            raise MedicationNotAdministeredException()

        with pytest.raises(HTTPException) as exc:
            self._run(monkeypatch, not_given, lambda *a: None)
        assert exc.value.status_code == 400
