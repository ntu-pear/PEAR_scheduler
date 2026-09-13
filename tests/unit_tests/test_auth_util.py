import asyncio
import base64
import json
import time
from unittest import mock

import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from pear_schedule.api.auth_util import (
    JWTPayload,
    Token,
    decode_jwtToken,
    generateAccessToken_onLogin,
    get_current_user,
    get_role_name,
    is_supervisor,
)


def make_token(exp=None, sub=None, header="header", signature="signature"):
    """Build a header.payload.signature string like a real JWT (unpadded base64url payload)."""
    payload_data = {}
    if exp is not None:
        payload_data["exp"] = exp
    if sub is not None:
        payload_data["sub"] = sub
    payload_json = json.dumps(payload_data)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"{header}.{payload_b64}.{signature}"


def make_sub(userId="1", fullName="Jane Doe", email="jane@example.com", roleName="SUPERVISOR", sessionId="sess-1"):
    return json.dumps({
        "userId": userId,
        "fullName": fullName,
        "email": email,
        "roleName": roleName,
        "sessionId": sessionId,
    })


class TestDecodeJwtToken:

    def test_valid_token_returns_payload(self):
        token = make_token(exp=int(time.time()) + 3600, sub=make_sub())

        result = decode_jwtToken(token)

        assert isinstance(result, JWTPayload)
        assert result.roleName == "SUPERVISOR"

    def test_malformed_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_jwtToken("not-a-jwt")

        assert exc_info.value.status_code == 401

    def test_invalid_base64_payload_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_jwtToken("header.!!!not-base64!!!.signature")

        assert exc_info.value.status_code == 401

    def test_missing_expiration_raises_401(self):
        token = make_token(sub=make_sub())

        with pytest.raises(HTTPException) as exc_info:
            decode_jwtToken(token)

        assert exc_info.value.status_code == 401
        assert "expiration" in exc_info.value.detail

    def test_missing_expiration_returns_none_when_bypassed(self):
        token = make_token(sub=make_sub())

        assert decode_jwtToken(token, bypass_auth=True) is None

    def test_expired_token_raises_401(self):
        token = make_token(exp=int(time.time()) - 3600, sub=make_sub())

        with pytest.raises(HTTPException) as exc_info:
            decode_jwtToken(token)

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail

    def test_expired_token_returns_none_when_bypassed(self):
        token = make_token(exp=int(time.time()) - 3600, sub=make_sub())

        assert decode_jwtToken(token, bypass_auth=True) is None

    def test_missing_subject_raises_401(self):
        token = make_token(exp=int(time.time()) + 3600)

        with pytest.raises(HTTPException) as exc_info:
            decode_jwtToken(token)

        assert exc_info.value.status_code == 401
        assert "subject" in exc_info.value.detail

    def test_missing_subject_returns_none_when_bypassed(self):
        token = make_token(exp=int(time.time()) + 3600)

        assert decode_jwtToken(token, bypass_auth=True) is None

    def test_subject_not_valid_json_raises_401(self):
        token = make_token(exp=int(time.time()) + 3600, sub="not-json")

        with pytest.raises(HTTPException) as exc_info:
            decode_jwtToken(token)

        assert exc_info.value.status_code == 401

    def test_subject_missing_required_field_raises_401(self):
        incomplete_sub = json.dumps({"userId": "1"})
        token = make_token(exp=int(time.time()) + 3600, sub=incomplete_sub)

        with pytest.raises(HTTPException) as exc_info:
            decode_jwtToken(token)

        assert exc_info.value.status_code == 401


class TestGetCurrentUser:

    def test_no_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(token="")

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Not authenticated"

    def test_valid_token_returns_decoded_payload(self):
        token = make_token(exp=int(time.time()) + 3600, sub=make_sub())

        result = get_current_user(token=token)

        assert isinstance(result, JWTPayload)


class TestRoleHelpers:

    def test_get_role_name_returns_role(self):
        payload = JWTPayload(**json.loads(make_sub(roleName="CAREGIVER")))

        assert get_role_name(payload) == "CAREGIVER"

    def test_get_role_name_returns_none_for_missing_attribute(self):
        assert get_role_name(object()) is None

    def test_is_supervisor_true(self):
        payload = JWTPayload(**json.loads(make_sub(roleName="SUPERVISOR")))

        assert is_supervisor(payload) is True

    def test_is_supervisor_false(self):
        payload = JWTPayload(**json.loads(make_sub(roleName="CAREGIVER")))

        assert is_supervisor(payload) is False


class TestGenerateAccessTokenOnLogin:

    def test_returns_bearer_token_from_user_login(self):
        form_data = OAuth2PasswordRequestForm(username="jane", password="pw", scope="")

        with mock.patch(
            "pear_schedule.api.auth_util.user_login",
            return_value={"access_token": "abc123"},
        ) as mock_login:
            result = asyncio.run(generateAccessToken_onLogin(form_data))

        mock_login.assert_called_once_with(username="jane", password="pw")
        assert isinstance(result, Token)
        assert result.access_token == "abc123"
        assert result.token_type == "bearer"
