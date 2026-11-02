"""
Sign-in on /schedule routes that used to take none. No DB: the handlers never run.
"""

import pytest
from fastapi import HTTPException

from pear_schedule.api import schedule_router
from pear_schedule.api.auth_util import JWTPayload, get_current_user
from pear_schedule.api.schedule_router import require_supervisor


def _user(role):
    return JWTPayload(userId="1", fullName="Jane Doe", email="jane@example.com", roleName=role, sessionId="s1")


def _deps(path):
    route = next(r for r in schedule_router.router.routes if r.path == path)
    return [d.call for d in route.dependant.dependencies]


class TestRequireSupervisor:
    def test_supervisor_allowed(self):
        user = _user("SUPERVISOR")
        assert require_supervisor(user) is user

    @pytest.mark.parametrize("role", ["CAREGIVER", "GUARDIAN", "DOCTOR", "ADMIN", "GAME THERAPIST"])
    def test_other_roles_get_403(self, role):
        with pytest.raises(HTTPException) as exc:
            require_supervisor(_user(role))
        assert exc.value.status_code == 403


class TestRoutesRequireSignIn:
    def test_get_schedule_needs_any_signed_in_user(self):
        # the web and mobile schedule pages call it for every role
        assert get_current_user in _deps("/getSchedule/")

    @pytest.mark.parametrize("path", ["/patientTest/", "/adhoc/", "/systemTest/"])
    def test_supervisor_only(self, path):
        assert require_supervisor in _deps(path)
