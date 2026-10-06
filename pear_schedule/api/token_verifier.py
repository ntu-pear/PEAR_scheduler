import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests
from fastapi import HTTPException, status

BASE_URL_ENV = "USER_BE_ORIGIN"
CACHE_TTL_SECONDS = 60
OUTAGE_BACKOFF_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 2.0
MAX_CACHE_ENTRIES = 10000
MAX_TOKEN_LENGTH = 4096

auth_logger = logging.getLogger("pear.auth")


@dataclass(frozen=True)
class VerifiedUser:
    userId: str
    fullName: str
    roleName: str
    email: str


class Verdict:
    VALID = "valid"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"
    UNCONFIGURED = "unconfigured"


_cache: dict[str, tuple[float, str, Optional[VerifiedUser]]] = {}
_outage_until = 0.0


def reset_cache() -> None:
    global _outage_until
    _cache.clear()
    _outage_until = 0.0


def verify_mode() -> str:
    mode = os.getenv("AUTH_VERIFY_MODE", "shadow").strip().lower()
    return mode if mode in ("shadow", "enforce") else "shadow"


def _call_user_service(base_url: str, token: str):
    return requests.get(
        f"{base_url}/api/v1/current_user/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def verify_token(token: str, now: Optional[Callable[[], float]] = None) -> tuple[str, Optional[VerifiedUser]]:
    global _outage_until
    clock = now or time.monotonic
    base_url = os.getenv(BASE_URL_ENV, "").rstrip("/")
    if not base_url:
        return Verdict.UNCONFIGURED, None

    if not token.isascii() or len(token) > MAX_TOKEN_LENGTH:
        return Verdict.REJECTED, None

    current = clock()
    if current < _outage_until:
        return Verdict.UNAVAILABLE, None

    key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cached = _cache.get(key)
    if cached and cached[0] > current:
        return cached[1], cached[2]

    try:
        response = _call_user_service(base_url, token)
    except requests.RequestException:
        _outage_until = current + OUTAGE_BACKOFF_SECONDS
        return Verdict.UNAVAILABLE, None

    if response.status_code == 200:
        try:
            body = response.json()
            result = (
                Verdict.VALID,
                VerifiedUser(
                    userId=str(body["userId"]),
                    fullName=body["fullName"],
                    roleName=body["roleName"],
                    email=body.get("email", ""),
                ),
            )
        except (ValueError, KeyError, TypeError):
            _outage_until = current + OUTAGE_BACKOFF_SECONDS
            return Verdict.UNAVAILABLE, None
    elif 400 <= response.status_code < 500:
        result = (Verdict.REJECTED, None)
    else:
        _outage_until = current + OUTAGE_BACKOFF_SECONDS
        return Verdict.UNAVAILABLE, None

    if len(_cache) >= MAX_CACHE_ENTRIES:
        _cache.clear()
    _cache[key] = (current + CACHE_TTL_SECONDS, result[0], result[1])
    return result


def _log_auth_event(event: str, reason: str, endpoint: str, claimed_user_id: str, claimed_role: str) -> None:
    auth_logger.warning(
        f"Auth {event}: {reason} on {endpoint} (claimed user {claimed_user_id}, role {claimed_role})",
        extra={
            "auth_event": event,
            "auth_reason": reason,
            "auth_endpoint": endpoint,
            "auth_claimed_user_id": claimed_user_id,
            "auth_claimed_role": claimed_role,
        },
    )


def apply_verification(token: str, claimed_user_id: str, claimed_role: str, endpoint: str) -> Optional[VerifiedUser]:
    mode = verify_mode()
    try:
        verdict, user = verify_token(token)
    except Exception:
        if mode == "shadow":
            _log_auth_event("would_reject", "verifier_error", endpoint, claimed_user_id, claimed_role)
            return None
        _log_auth_event("rejected", "verifier_error", endpoint, claimed_user_id, claimed_role)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication service unavailable")

    if verdict == Verdict.UNCONFIGURED:
        if mode == "enforce":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication service not configured")
        return None

    reason = None
    if verdict == Verdict.REJECTED:
        reason = "token_rejected"
    elif verdict == Verdict.UNAVAILABLE:
        reason = "user_service_unavailable"
    elif user is not None and (user.userId != str(claimed_user_id) or user.roleName != claimed_role):
        reason = "identity_mismatch"

    if mode == "shadow":
        if reason:
            _log_auth_event("would_reject", reason, endpoint, claimed_user_id, claimed_role)
        return None

    if reason:
        _log_auth_event("rejected", reason, endpoint, claimed_user_id, claimed_role)
        if reason == "user_service_unavailable":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication service unavailable")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return user
