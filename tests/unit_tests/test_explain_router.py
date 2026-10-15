"""
/schedule/explain routes. No DB, no HTTP client.
"""

import datetime
import json
import types
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from pear_schedule.api import explain_router
from pear_schedule.api.auth_util import oauth2_scheme
from pear_schedule.api.token_verifier import Verdict, VerifiedUser
from pear_schedule.scheduler import explain

WEEK = datetime.datetime(2024, 3, 18, 10, 30)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    explain_router.reset_cache()
    monkeypatch.setattr(explain, "current_week_start", lambda: WEEK)
    # nothing saved yet unless a test says so, so it builds
    monkeypatch.setattr(explain, "explain_saved_week", lambda config, with_names: None)
    yield
    explain_router.reset_cache()


def _verdict(monkeypatch, verdict, role="SUPERVISOR"):
    user = VerifiedUser("U1", "Sam", role, "s@example.com") if verdict == Verdict.VALID else None
    monkeypatch.setattr(explain_router, "verify_token", lambda token: (verdict, user))


def _route(path):
    return next(r for r in explain_router.router.routes if r.path == path)


class TestRequireVerifiedStaff:
    def test_supervisor_allowed(self, monkeypatch):
        _verdict(monkeypatch, Verdict.VALID)
        assert explain_router.require_verified_staff("t").userId == "U1"

    def test_admin_allowed(self, monkeypatch):
        _verdict(monkeypatch, Verdict.VALID, "ADMIN")
        assert explain_router.require_verified_staff("t").userId == "U1"

    @pytest.mark.parametrize("role", ["GUARDIAN", "DOCTOR", "CAREGIVER", "supervisor", ""])
    def test_other_roles_get_403(self, monkeypatch, role):
        _verdict(monkeypatch, Verdict.VALID, role)
        with pytest.raises(HTTPException) as exc:
            explain_router.require_verified_staff("t")
        assert exc.value.status_code == 403

    def test_forged_or_expired_token_gets_401(self, monkeypatch):
        _verdict(monkeypatch, Verdict.REJECTED)
        with pytest.raises(HTTPException) as exc:
            explain_router.require_verified_staff("t")
        assert exc.value.status_code == 401

    @pytest.mark.parametrize("verdict", [Verdict.UNAVAILABLE, Verdict.UNCONFIGURED])
    def test_no_user_service_gets_503(self, monkeypatch, verdict):
        # unlike shadow mode, never let it through unchecked
        _verdict(monkeypatch, verdict)
        with pytest.raises(HTTPException) as exc:
            explain_router.require_verified_staff("t")
        assert exc.value.status_code == 503

    def test_verifier_crash_gets_503(self, monkeypatch):
        def boom(token):
            raise RuntimeError("down")
        monkeypatch.setattr(explain_router, "verify_token", boom)
        with pytest.raises(HTTPException) as exc:
            explain_router.require_verified_staff("t")
        assert exc.value.status_code == 503

    def test_ignores_shadow_mode(self, monkeypatch):
        monkeypatch.setenv("AUTH_VERIFY_MODE", "shadow")
        _verdict(monkeypatch, Verdict.REJECTED)
        with pytest.raises(HTTPException):
            explain_router.require_verified_staff("t")

    def test_data_route_needs_it(self):
        deps = [d.call for d in _route("/").dependant.dependencies]
        assert explain_router.require_verified_staff in deps
        sub = next(d for d in _route("/").dependant.dependencies if d.call is explain_router.require_verified_staff)
        assert oauth2_scheme in [d.call for d in sub.dependencies]


class TestCachedExplanation:
    @pytest.fixture
    def run(self, monkeypatch):
        run = MagicMock(side_effect=lambda config, with_names: {"n": run.call_count})
        monkeypatch.setattr(explain, "run_explanation", run)
        return run

    def test_reuses_a_recent_build(self, run):
        clock = iter([0, 60, 120]).__next__
        assert explain_router.cached_explanation({}, now=clock) == {"n": 1}
        assert explain_router.cached_explanation({}, now=clock) == {"n": 1}
        assert run.call_count == 1
        assert run.call_args.kwargs == {"with_names": True}

    def test_rebuilds_after_30_minutes(self, run):
        times = iter([0, 30 * 60, 30 * 60])
        explain_router.cached_explanation({}, now=lambda: next(times))
        assert explain_router.cached_explanation({}, now=lambda: next(times)) == {"n": 2}

    def test_refresh_waits_5_minutes(self, run):
        times = iter([0, 60, 5 * 60, 5 * 60])
        explain_router.cached_explanation({}, now=lambda: next(times))
        assert explain_router.cached_explanation({}, refresh=True, now=lambda: next(times)) == {"n": 1}
        assert explain_router.cached_explanation({}, refresh=True, now=lambda: next(times)) == {"n": 2}

    def test_new_week_rebuilds(self, run, monkeypatch):
        explain_router.cached_explanation({}, now=lambda: 0)
        monkeypatch.setattr(explain, "current_week_start", lambda: WEEK + datetime.timedelta(days=7))
        assert explain_router.cached_explanation({}, now=lambda: 1) == {"n": 2}

    def test_saved_week_is_used_when_there_is_one(self, monkeypatch, run):
        monkeypatch.setattr(explain, "explain_saved_week", lambda config, with_names: {"source": "saved"})
        assert explain_router.cached_explanation({}, now=lambda: 0) == {"source": "saved"}
        run.assert_not_called()

    def test_reset_drops_the_cached_copy(self, run):
        explain_router.cached_explanation({}, now=lambda: 0)
        explain_router.reset_cache()
        assert explain_router.cached_explanation({}, now=lambda: 1) == {"n": 2}

    def test_failed_build_is_not_cached(self, monkeypatch):
        calls = []

        def flaky(config, with_names):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("db down")
            return {"ok": True}
        monkeypatch.setattr(explain, "run_explanation", flaky)
        with pytest.raises(RuntimeError):
            explain_router.cached_explanation({}, now=lambda: 0)
        assert explain_router.cached_explanation({}, now=lambda: 1) == {"ok": True}


class TestRoutes:
    def _request(self):
        return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(config={"x": 1})))

    def test_returns_the_explanation_and_never_writes(self, monkeypatch):
        from pear_schedule.db_utils.writer import ScheduleWriter
        writer = MagicMock()
        monkeypatch.setattr(ScheduleWriter, "write", writer)
        monkeypatch.setattr(explain, "run_explanation", lambda config, with_names: {"week_start": "2024-03-18"})
        user = VerifiedUser("U1", "Sam", "SUPERVISOR", "")
        res = explain_router.get_explanation(self._request(), refresh=False, user=user)
        assert json.loads(res.body)["week_start"] == "2024-03-18"
        writer.assert_not_called()

    def test_build_error_is_500(self, monkeypatch):
        def boom(config, with_names):
            raise RuntimeError("db down")
        monkeypatch.setattr(explain, "run_explanation", boom)
        with pytest.raises(HTTPException) as exc:
            explain_router.get_explanation(self._request(), refresh=False, user=VerifiedUser("U1", "Sam", "SUPERVISOR", ""))
        assert exc.value.status_code == 500

    def test_view_has_no_data_and_points_at_the_api(self):
        page = explain_router.view_explainer().body.decode()
        assert "window.EXPLAIN_API" in page
        assert "window.EXPLAIN_DATA =" not in page
        assert "<!-- EXPLAIN_DATA -->" not in page

    def test_view_needs_no_login(self):
        assert _route("/view/").dependant.dependencies == []
