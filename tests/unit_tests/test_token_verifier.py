import logging

import pytest
import requests
from fastapi import HTTPException

from pear_schedule.api import token_verifier
from pear_schedule.api.token_verifier import Verdict, VerifiedUser, apply_verification, verify_token

USER = {"userId": "U1", "fullName": "Sam", "roleName": "SUPERVISOR", "email": "s@example.com"}


class FakeResponse:
    def __init__(self, status_code, body=None, json_error=None):
        self.status_code = status_code
        self._body = body or {}
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._body


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setenv("USER_BE_ORIGIN", "http://user-svc")
    monkeypatch.delenv("AUTH_VERIFY_MODE", raising=False)
    token_verifier.reset_cache()
    yield
    token_verifier.reset_cache()


def _respond(monkeypatch, status, body=None):
    monkeypatch.setattr(token_verifier, "_call_user_service", lambda base_url, token: FakeResponse(status, body))


def _verifier_raises(monkeypatch):
    def boom(token, now=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(token_verifier, "verify_token", boom)


def test_valid(monkeypatch):
    _respond(monkeypatch, 200, USER)
    verdict, user = verify_token("tok", now=lambda: 1.0)
    assert verdict == Verdict.VALID and user == VerifiedUser("U1", "Sam", "SUPERVISOR", "s@example.com")


def test_network_error_backs_off(monkeypatch):
    calls = []

    def boom(base_url, token):
        calls.append(token)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(token_verifier, "_call_user_service", boom)
    verify_token("a", now=lambda: 1000.0)
    verify_token("b", now=lambda: 1010.0)
    assert calls == ["a"]


def test_shadow_logs_mismatch(monkeypatch, caplog):
    _respond(monkeypatch, 200, USER)
    with caplog.at_level(logging.WARNING, logger="pear.auth"):
        assert apply_verification("tok", "U1", "ADMIN", "/schedule/regenerate/supervisor/") is None
    assert caplog.records[-1].auth_reason == "identity_mismatch"


def test_enforce_rejects_and_503s(monkeypatch):
    monkeypatch.setenv("AUTH_VERIFY_MODE", "enforce")
    _respond(monkeypatch, 401)
    with pytest.raises(HTTPException) as exc:
        apply_verification("tok", "U1", "SUPERVISOR", "/x")
    assert exc.value.status_code == 401
    token_verifier.reset_cache()
    _respond(monkeypatch, 500)
    with pytest.raises(HTTPException) as exc:
        apply_verification("tok", "U1", "SUPERVISOR", "/x")
    assert exc.value.status_code == 503


def test_unparseable_200_body_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        token_verifier,
        "_call_user_service",
        lambda base_url, token: FakeResponse(200, json_error=ValueError("not json")),
    )
    assert verify_token("tok", now=lambda: 1.0) == (Verdict.UNAVAILABLE, None)


def test_shadow_verifier_error_returns_none_and_logs(monkeypatch, caplog):
    _verifier_raises(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="pear.auth"):
        assert apply_verification("tok", "U1", "ADMIN", "/x") is None
    assert caplog.records[-1].auth_reason == "verifier_error"


def test_enforce_verifier_error_503s(monkeypatch):
    monkeypatch.setenv("AUTH_VERIFY_MODE", "enforce")
    _verifier_raises(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        apply_verification("tok", "U1", "ADMIN", "/x")
    assert exc.value.status_code == 503


def test_log_message_names_claimed_identity(monkeypatch, caplog):
    _respond(monkeypatch, 401)
    with caplog.at_level(logging.WARNING, logger="pear.auth"):
        apply_verification("tok", "U1", "ADMIN", "/x")
    assert "claimed user U1, role ADMIN" in caplog.records[-1].getMessage()


_resp = lambda s: FakeResponse(s)


def _counting(monkeypatch, status):
    calls = []

    def fake(base_url, token):
        calls.append(token)
        return _resp(status)

    monkeypatch.setattr(token_verifier, "_call_user_service", fake)
    return calls


@pytest.mark.parametrize("token", ["toké", "a" * 5000])
def test_non_ascii_or_oversized_token_is_rejected_without_calling_user_service(monkeypatch, token):
    calls = _counting(monkeypatch, 200)
    assert verify_token(token, now=lambda: 1000.0) == (Verdict.REJECTED, None)
    assert calls == []


def test_client_error_429_is_rejected_without_backoff(monkeypatch):
    calls = _counting(monkeypatch, 429)
    assert verify_token("a", now=lambda: 1000.0) == (Verdict.REJECTED, None)
    assert verify_token("b", now=lambda: 1010.0) == (Verdict.REJECTED, None)
    assert calls == ["a", "b"]


def test_503_is_unavailable_and_backs_off(monkeypatch):
    calls = _counting(monkeypatch, 503)
    assert verify_token("a", now=lambda: 1000.0) == (Verdict.UNAVAILABLE, None)
    assert verify_token("b", now=lambda: 1010.0) == (Verdict.UNAVAILABLE, None)
    assert calls == ["a"]
