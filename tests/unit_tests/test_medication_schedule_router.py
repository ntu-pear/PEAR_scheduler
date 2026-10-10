"""
Auth on /MedicationSchedule routes. No DB, no HTTP client.
"""

import pytest
from fastapi import HTTPException

from pear_schedule.api import medication_schedule_router
from pear_schedule.api.auth_util import JWTPayload, get_current_user
from pear_schedule.api.medication_schedule_router import require_supervisor


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
    @pytest.mark.parametrize("path", ["/get/", "/update/"])
    def test_route_depends_on_require_supervisor(self, path):
        assert require_supervisor in [d.call for d in _route(path).dependant.dependencies]

    def test_require_supervisor_reads_the_bearer_token(self):
        sub_deps = [d.call for d in _route("/get/").dependant.dependencies[0].dependencies]
        assert get_current_user in sub_deps
