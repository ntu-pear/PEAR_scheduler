"""
Schedule explainer at a link. Supervisors only, and the token is always checked with
the user service, even when AUTH_VERIFY_MODE is shadow. Read-only.
"""

import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from pear_schedule.api.auth_util import oauth2_scheme
from pear_schedule.api.token_verifier import Verdict, VerifiedUser, verify_token
from pear_schedule.scheduler import explain

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Explain"])

CACHE_SECONDS = 30 * 60
REFRESH_SECONDS = 5 * 60

# one build at a time, the rest wait and get the cached one
_lock = threading.Lock()
_cache: dict = {}


def reset_cache() -> None:
    # waits for a build in progress, so it can't put back an old copy
    with _lock:
        _cache.clear()


def require_verified_supervisor(token: str = Depends(oauth2_scheme)) -> VerifiedUser:
    try:
        verdict, user = verify_token(token)
    except Exception:
        logger.exception("Token check failed")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if verdict == Verdict.REJECTED:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if verdict != Verdict.VALID or user is None:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if user.roleName != "SUPERVISOR":
        raise HTTPException(status_code=403, detail="Only supervisors can view the schedule explainer")
    return user


def cached_explanation(config, refresh: bool = False, now=time.monotonic) -> dict:
    with _lock:
        week = explain.current_week_start().date()
        if _cache and _cache["week"] == week:
            age = now() - _cache["built"]
            # refresh still reuses a very recent build so it can't be spammed
            if age < (REFRESH_SECONDS if refresh else CACHE_SECONDS):
                return _cache["data"]
        # the saved week as it is, else a fresh build if nothing is saved yet
        data = explain.explain_saved_week(config, with_names=True) or explain.run_explanation(config, with_names=True)
        _cache.update(week=week, built=now(), data=data)
        return data


@router.get("/")
def get_explanation(request: Request, refresh: bool = False,
                    user: VerifiedUser = Depends(require_verified_supervisor)):
    logger.info(f"Schedule explainer opened by {user.userId} (refresh={refresh})")
    try:
        return JSONResponse(cached_explanation(request.app.state.config, refresh))
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail="Could not build the explanation, check the scheduler logs")


@router.get("/view/", response_class=HTMLResponse, include_in_schema=False)
def view_explainer():
    # no data in the page, it signs in and fetches it from the route above
    return HTMLResponse(explain.viewer_page('<script>window.EXPLAIN_API = {data: "../", token: "../../token"};</script>'))
