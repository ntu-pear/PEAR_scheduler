"""
/schedule/patient/{id}/: who can see which patient. User service, DB and patient service mocked.
"""

import datetime
import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi import HTTPException

from pear_schedule.api import patient_schedule_router as psr
from pear_schedule.api.token_verifier import Verdict, VerifiedUser

ALLOCATIONS = pd.DataFrame({
    "patientId": [5, 6, 7],
    "caregiverId": ["C1", "C2", "C2"],
    "tempCaregiverId": [None, "C1", None],
    "supervisorId": ["S1", "S1", "S1"],
})


def _user(monkeypatch, role, user_id="U1", verdict=Verdict.VALID):
    user = VerifiedUser(user_id, "Sam", role, "s@example.com") if verdict == Verdict.VALID else None
    monkeypatch.setattr(psr, "verify_token", lambda token: (verdict, user))
    return user


def _page(ids, total_pages=1):
    res = MagicMock()
    res.json.return_value = {"data": [{"id": i} for i in ids], "pageNo": 0, "pageSize": 100,
                             "totalRecords": len(ids), "totalPages": total_pages}
    return res


def _status(fn):
    with pytest.raises(HTTPException) as exc:
        fn()
    return exc.value.status_code


class TestToken:
    def test_forged_or_expired_is_401(self, monkeypatch):
        _user(monkeypatch, "SUPERVISOR", verdict=Verdict.REJECTED)
        assert _status(lambda: psr.require_verified_user("t")) == 401

    @pytest.mark.parametrize("verdict", [Verdict.UNAVAILABLE, Verdict.UNCONFIGURED])
    def test_no_user_service_is_503(self, monkeypatch, verdict):
        _user(monkeypatch, "SUPERVISOR", verdict=verdict)
        assert _status(lambda: psr.require_verified_user("t")) == 503

    def test_verifier_crash_is_503(self, monkeypatch):
        def boom(token):
            raise RuntimeError("down")
        monkeypatch.setattr(psr, "verify_token", boom)
        assert _status(lambda: psr.require_verified_user("t")) == 503


class TestCanView:
    def test_supervisor_sees_anyone(self):
        assert psr.can_view(VerifiedUser("U1", "Sam", "SUPERVISOR", ""), 999, "t")

    def test_caregiver_sees_own_and_temp_patients_only(self):
        with patch.object(psr.CaregiverAllocatedView, "get_data", return_value=ALLOCATIONS):
            c1 = VerifiedUser("C1", "Cat", "CAREGIVER", "")
            assert psr.can_view(c1, 5, "t")       # caregiver
            assert psr.can_view(c1, 6, "t")       # temp caregiver
            assert not psr.can_view(c1, 7, "t")

    def test_guardian_asks_patient_service_with_their_token(self, monkeypatch):
        monkeypatch.setenv("PATIENT_SERVICE_URL", "http://patient/")
        with patch.object(psr.requests, "get", return_value=_page([5, 8])) as get:
            g = VerifiedUser("G 1", "Gus", "GUARDIAN", "")
            assert psr.can_view(g, 8, "tok")
            assert not psr.can_view(g, 6, "tok")
        url = get.call_args.args[0]
        assert url == "http://patient/api/v1/patients/by-guardian/G%201"
        assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer tok"}

    def test_guardian_reads_every_page(self, monkeypatch):
        monkeypatch.setenv("PATIENT_SERVICE_URL", "http://patient")
        with patch.object(psr.requests, "get", side_effect=[_page([1], 2), _page([9], 2)]) as get:
            assert psr.can_view(VerifiedUser("G1", "Gus", "GUARDIAN", ""), 9, "t")
        assert get.call_count == 2

    def test_guardian_without_patient_service_is_503(self, monkeypatch):
        monkeypatch.delenv("PATIENT_SERVICE_URL", raising=False)
        assert _status(lambda: psr.can_view(VerifiedUser("G1", "Gus", "GUARDIAN", ""), 5, "t")) == 503

    def test_guardian_when_patient_service_fails_is_503(self, monkeypatch):
        monkeypatch.setenv("PATIENT_SERVICE_URL", "http://patient")
        bad = MagicMock()
        bad.raise_for_status.side_effect = RuntimeError("500")
        with patch.object(psr.requests, "get", return_value=bad):
            assert _status(lambda: psr.can_view(VerifiedUser("G1", "Gus", "GUARDIAN", ""), 5, "t")) == 503

    @pytest.mark.parametrize("role", ["ADMIN", "DOCTOR", "GAME_THERAPIST", "supervisor", ""])
    def test_other_roles_see_nobody(self, role):
        assert not psr.can_view(VerifiedUser("U1", "Sam", role, ""), 5, "t")


class TestRoute:
    def _df(self):
        return pd.DataFrame({"ScheduleID": [1], "PatientID": [5], "Name": ["Alice"], "Monday": ["{}"]})

    def test_admin_is_403(self, monkeypatch):
        _user(monkeypatch, "ADMIN")
        assert _status(lambda: psr.get_patient_schedule(5, None, "t")) == 403

    def test_other_patient_is_403(self, monkeypatch):
        _user(monkeypatch, "CAREGIVER", "C9")
        with patch.object(psr.CaregiverAllocatedView, "get_data", return_value=ALLOCATIONS):
            assert _status(lambda: psr.get_patient_schedule(5, None, "t")) == 403

    def test_this_week_for_that_patient(self, monkeypatch):
        _user(monkeypatch, "SUPERVISOR")
        with patch.object(psr.WeeklyScheduleView, "get_data", return_value=self._df()) as get:
            res = psr.get_patient_schedule(5, None, "t")
        get.assert_called_once_with(at=None, patient_id=5)
        body = json.loads(res.body)
        assert body["Status"] == "200"
        assert body["Data"] == [{"PatientID": 5, "Name": "Alice", "Monday": "{}"}]

    def test_date_asks_for_that_week(self, monkeypatch):
        _user(monkeypatch, "SUPERVISOR")
        with patch.object(psr.WeeklyScheduleView, "get_data", return_value=self._df()) as get:
            psr.get_patient_schedule(5, datetime.date(2026, 10, 8), "t")
        get.assert_called_once_with(at=datetime.datetime(2026, 10, 8, 12), patient_id=5)

    def test_nothing_saved_is_404(self, monkeypatch):
        _user(monkeypatch, "SUPERVISOR")
        empty = pd.DataFrame(columns=["ScheduleID", "PatientID", "Name"])
        with patch.object(psr.WeeklyScheduleView, "get_data", return_value=empty):
            assert json.loads(psr.get_patient_schedule(5, None, "t").body)["Status"] == "404"

    def test_route_needs_a_token(self):
        route = next(r for r in psr.router.routes if r.path == "/{patient_id}/")
        assert any(d.call is psr.oauth2_scheme for d in route.dependant.dependencies)
