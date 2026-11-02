import base64
import json
import time

import pytest
from fastapi import HTTPException

from pear_schedule.api import auth_util
from pear_schedule.api.token_verifier import VerifiedUser


def _token(role="SUPERVISOR"):
    sub = json.dumps({"userId": "U1", "fullName": "Sam", "email": "s@example.com",
                      "roleName": role, "sessionId": "S1"})
    payload = json.dumps({"sub": sub, "exp": int(time.time()) + 3600}).encode()
    return "eyJhbGciOiJIUzI1NiJ9." + base64.urlsafe_b64encode(payload).decode().rstrip("=") + ".sig"


def test_shadow_keeps_claimed_identity(monkeypatch):
    monkeypatch.setattr(auth_util, "apply_verification", lambda **kw: None)
    assert auth_util.decode_jwtToken(_token(role="ADMIN"), endpoint="/x").roleName == "ADMIN"


def test_enforce_uses_verified_identity(monkeypatch):
    monkeypatch.setattr(auth_util, "apply_verification",
                        lambda **kw: VerifiedUser("U1", "Sam (verified)", "SUPERVISOR", "s@example.com"))
    payload = auth_util.decode_jwtToken(_token())
    assert payload.fullName == "Sam (verified)" and payload.sessionId == "S1"


def test_verifier_503_is_not_converted_to_401(monkeypatch):
    def unavailable(**kw):
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    monkeypatch.setattr(auth_util, "apply_verification", unavailable)
    with pytest.raises(HTTPException) as exc:
        auth_util.decode_jwtToken(_token())
    assert exc.value.status_code == 503
