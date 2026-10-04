import datetime
import json
import logging
import re
from typing import Any, Mapping, Optional

import requests
from sqlalchemy import update

from pear_schedule.db import DB
from pear_schedule.db_utils.utils import timeslot_index
from pear_schedule.db_utils.views import CareCentreView

logger = logging.getLogger(__name__)

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TIME_FORMAT = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
REQUEST_TIMEOUT_SECONDS = 3


def is_valid_working_hours(hours: Any) -> bool:
    """Same rules Activity service applies when saving working hours."""
    if not isinstance(hours, dict) or set(hours) != set(DAYS):
        return False
    for times in hours.values():
        if not isinstance(times, dict):
            return False
        open_time, close_time = times.get("open"), times.get("close")
        if open_time is None and close_time is None:
            continue
        if not (isinstance(open_time, str) and isinstance(close_time, str)):
            return False
        if not (TIME_FORMAT.match(open_time) and TIME_FORMAT.match(close_time)) or close_time <= open_time:
            return False
    return True


def fetch_working_hours(base_url: str, centre_id: int) -> Optional[dict]:
    """Gets working hours from Activity service. None if unavailable or invalid.

    Activity's GET /care_centres/{id}/working_hours is token-less on purpose for this call. If it
    ever rejects the call (e.g. 401), this returns None and the caller falls back to
    REF_CARE_CENTRE, with only a warning in the logs.
    """
    if not base_url:
        return None
    url = f"{base_url.rstrip('/')}/api/v1/care_centres/{centre_id}/working_hours"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        hours = response.json().get("working_hours")
    except (requests.RequestException, ValueError, AttributeError) as e:
        logger.warning(f"Could not fetch care centre hours from {url}: {e}")
        return None
    if not is_valid_working_hours(hours):
        logger.error(f"Invalid care centre hours from {url}: {hours}")
        return None
    return hours


def save_working_hours(config: Mapping[str, Any], hours: dict) -> None:
    """Keeps REF_CARE_CENTRE as the last known good copy."""
    care_centre = DB.schema.tables[config["DB_TABLES"].CARE_CENTRE_TABLE]
    with DB.get_engine().begin() as conn:
        result = conn.execute(
            update(care_centre)
            .where(care_centre.c["id"] == config["CARE_CENTRE_ID"])
            .values(working_hours=json.dumps(hours))
        )
    if result.rowcount == 0:
        logger.warning(f"No REF_CARE_CENTRE row with id {config['CARE_CENTRE_ID']} to update")


def read_saved_working_hours() -> dict:
    """Working hours from REF_CARE_CENTRE."""
    df = CareCentreView.get_data()
    if df.empty:
        raise Exception("No care centre found in database.")
    hours_str = df.iloc[0]["WorkingHours"]
    if not hours_str:
        raise Exception("Working hours not found for care centre.")
    return json.loads(hours_str)


def load_working_hours(config: Mapping[str, Any]) -> dict:
    """From Activity service if reachable (and saved locally), else from REF_CARE_CENTRE."""
    hours = fetch_working_hours(config.get("ACTIVITY_SERVICE_URL"), config["CARE_CENTRE_ID"])
    if hours is None:
        logger.info("Using care centre hours saved in REF_CARE_CENTRE")
        return read_saved_working_hours()
    try:
        save_working_hours(config, hours)
    except Exception:
        logger.exception("Could not save care centre hours to REF_CARE_CENTRE")
    return hours


def validate_group_timeslot_mapping(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and convert each GROUP_TIMESLOT_MAPPING entry (e.g. "Monday 09:30") into a
    (day_index, slot_index) tuple.
    """
    for i, timeslot_str in enumerate(config["GROUP_TIMESLOT_MAPPING"]):
        qualified_day = timeslot_str.split(" ")[0]
        if qualified_day not in config["OPEN_DAYS"]:
            raise Exception(f"Group timeslot mapping not schedulable on {timeslot_str} because centre is not open on {qualified_day}.")
        day = config["OPEN_DAYS"].index(qualified_day)

        time_obj = datetime.datetime.strptime(timeslot_str.split(" ")[1], "%H:%M")
        opening_time_obj = datetime.datetime.strptime(config["WORKING_HOURS"].get(qualified_day.lower()).get("open"), "%H:%M")
        slot = timeslot_index(time_obj - opening_time_obj, config["MIN_ACTIVITY_DURATION"])
        if slot < 0 or slot >= config["SLOTS_PER_DAY"].get(qualified_day):
            raise Exception(f"Group timeslot mapping not schedulable on {timeslot_str} because timing is out of bounds for center's working hours.")
        config["GROUP_TIMESLOT_MAPPING"][i] = (day, slot)

    return config


def centre_hours_config(config: Mapping[str, Any], hours: dict) -> dict:
    """Config values that depend on working hours. Raises if the group timeslots don't fit."""
    open_days, slots_per_day = [], {}
    for day in config["DAY_OF_WEEK_ORDER"]:
        times = hours.get(day.lower()) or {}
        if times.get("open"):
            open_days.append(day)
            opening = datetime.datetime.strptime(times["open"], "%H:%M")
            closing = datetime.datetime.strptime(times["close"], "%H:%M")
            slots_per_day[day] = (closing - opening) // datetime.timedelta(minutes=config["MIN_ACTIVITY_DURATION"])

    candidate = {
        **config,
        "OPEN_DAYS": open_days,
        "WORKING_HOURS": hours,
        "SLOTS_PER_DAY": slots_per_day,
        # validate a copy of the original strings, the live list holds converted tuples
        "GROUP_TIMESLOT_MAPPING": list(config["GROUP_TIMESLOT_MAPPING_RAW"]),
    }
    validate_group_timeslot_mapping(candidate)
    return {key: candidate[key] for key in ("OPEN_DAYS", "WORKING_HOURS", "SLOTS_PER_DAY", "GROUP_TIMESLOT_MAPPING")}


def apply_centre_hours(config: dict) -> None:
    """Loads working hours and updates config in place. Raises on failure (used at startup)."""
    config.setdefault("GROUP_TIMESLOT_MAPPING_RAW", list(config["GROUP_TIMESLOT_MAPPING"]))
    config.update(centre_hours_config(config, load_working_hours(config)))


def refresh_centre_hours(config: dict) -> bool:
    """Same as apply_centre_hours but keeps the current config if anything fails."""
    try:
        apply_centre_hours(config)
        return True
    except Exception:
        logger.exception("Could not refresh care centre hours, keeping current config")
        return False
