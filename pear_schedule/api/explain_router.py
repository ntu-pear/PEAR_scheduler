"""
Schedule explainer at a link, and next week's preview. Supervisors and admins only, and the token
is always checked with the user service, even when AUTH_VERIFY_MODE is shadow. Read-only.
"""

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from pear_schedule.api.auth_util import oauth2_scheme
from pear_schedule.api.token_verifier import Verdict, VerifiedUser, verify_token
from pear_schedule.db_utils.utils import next_week_start
from pear_schedule.scheduler import explain

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Explain"])
preview_router = APIRouter(tags=["Explain"])

# roles that can see the explainer, it has patient names
ALLOWED_ROLES = {"SUPERVISOR", "ADMIN"}

CACHE_SECONDS = 30 * 60
REFRESH_SECONDS = 5 * 60

# one build at a time, the rest wait and get the cached one
_lock = threading.Lock()
_cache: dict = {}


def reset_cache() -> None:
    # waits for a build in progress, so it can't put back an old copy
    with _lock:
        _cache.clear()


def require_verified_staff(token: str = Depends(oauth2_scheme)) -> VerifiedUser:
    try:
        verdict, user = verify_token(token)
    except Exception:
        logger.exception("Token check failed")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if verdict == Verdict.REJECTED:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if verdict != Verdict.VALID or user is None:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if user.roleName not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Only supervisors and admins can view the schedule explainer")
    return user


def cached_explanation(config, refresh: bool = False, now=time.monotonic, week: str = "this") -> dict:
    with _lock:
        start = next_week_start() if week == "next" else explain.current_week_start().date()
        hit = _cache.get(week)
        if hit and hit["week"] == start:
            age = now() - hit["built"]
            # refresh still reuses a very recent build so it can't be spammed
            if age < (REFRESH_SECONDS if refresh else CACHE_SECONDS):
                return hit["data"]
        if week == "next":
            # nothing is saved for next week, always a fresh build
            data = explain.preview_next_week(config, with_names=True)
        else:
            # the saved week as it is, else a fresh build if nothing is saved yet
            data = explain.explain_saved_week(config, with_names=True) or explain.run_explanation(config, with_names=True)
        _cache[week] = {"week": start, "built": now(), "data": data}
        return data


@router.get("/")
def get_explanation(request: Request, refresh: bool = False, week: Literal["this", "next"] = "this",
                    user: VerifiedUser = Depends(require_verified_staff)):
    logger.info(f"Schedule explainer opened by {user.userId} (week={week}, refresh={refresh})")
    try:
        # the role decides the PEAR links on the page, a copy since the cached dict is shared
        return JSONResponse({**cached_explanation(request.app.state.config, refresh, week=week), "viewer_role": user.roleName})
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail="Could not build the explanation, check the scheduler logs")


@preview_router.get("/")
def get_preview(request: Request, refresh: bool = False,
                user: VerifiedUser = Depends(require_verified_staff)):
    # next week in the getSchedule shape, for the calendar. Not saved, can change until Monday
    logger.info(f"Next week preview opened by {user.userId} (refresh={refresh})")
    try:
        config = request.app.state.config
        data = cached_explanation(config, refresh, week="next")
        return JSONResponse({
            "Status": "200",
            "Message": "Preview of next week, not saved",
            "Preview": True,
            "BuiltAt": data["generated_at"],
            "Data": explain.schedule_rows(data, config),
        })
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail="Could not build the preview, check the scheduler logs")


def _csp(page: str) -> str:
    # only the page's own inline scripts run, and it only talks to the scheduler
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"
        for script in re.findall(r"<script>(.*?)</script>", page, re.S))
    return (f"default-src 'none'; script-src {hashes}; style-src 'unsafe-inline'; img-src data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


@router.get("/view/", response_class=HTMLResponse, include_in_schema=False)
def view_explainer():
    # no data in the page, it signs in and fetches it from the route above
    api = {"data": "../", "token": "../../token"}
    pear = os.getenv("EXPLAIN_PEAR_URL", "").strip()
    if pear.startswith(("http://", "https://")):
        api["pear"] = pear  # the PEAR web app, for the "in PEAR" links
    script = "<script>window.EXPLAIN_API = " + json.dumps(api).replace("</", "<\\/") + ";</script>"
    page = explain.viewer_page(script)
    return HTMLResponse(page, headers={"Content-Security-Policy": _csp(page)})
