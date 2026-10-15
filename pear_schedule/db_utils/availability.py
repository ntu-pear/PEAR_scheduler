"""
Centre activity availability (REF_CENTRE_ACTIVITY_AVAILABILITY) as FixedTimeSlots.

With USE_ACTIVITY_AVAILABILITY on, an activity that has availability rows gets its
FixedTimeSlots from them instead:
  - fixed: one start per window (the window is the activity's length), this is what
    replaces fixed_time_slots
  - flexible individual: every start whose whole span fits in a window
  - flexible group: left as is, group slots still come from GROUP_TIMESLOT_MAPPING
  - none of its windows this week: not scheduled this week
Activities with no rows are left as is.
"""

import datetime
import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

Window = Mapping[str, Any]  # DaysOfWeek, StartTime, EndTime, StartDate, EndDate


def _time(value) -> Optional[datetime.time]:
    if value is None or (not isinstance(value, datetime.time) and pd.isna(value)):
        return None
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, datetime.time):
        return value
    if isinstance(value, pd.Timedelta):  # some drivers read TIME as a timedelta
        return (datetime.datetime.min + value.to_pytimedelta()).time()
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%H:%M:%S.%f"):
        try:
            return datetime.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _date(value) -> Optional[datetime.date]:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return pd.Timestamp(value).date()


def _is_true(value) -> bool:
    return str(value).strip().lower() in ("1", "true")


def window_covers(window: Window, day_name: str, on: datetime.date, day_order: List[str]) -> bool:
    """Whether the window applies on this date. DaysOfWeek 0 = not recurring, just its dates."""
    start, end = _date(window.get("StartDate")), _date(window.get("EndDate"))
    days = int(window.get("DaysOfWeek") or 0)
    if not days:
        if start is None:
            return False
        return start <= on <= (end or start)
    if not days & (1 << day_order.index(day_name)):
        return False
    return (start is None or start <= on) and (end is None or on <= end)


def availability_slots(
    windows: Iterable[Window],
    min_duration: int,
    week_start: datetime.datetime,
    config: Mapping[str, Any],
) -> Set[Tuple[int, int]]:
    """(day, start slot) where the whole activity fits inside one of its windows this week."""
    week_start = pd.Timestamp(week_start).to_pydatetime()
    slot_minutes = int(config["MIN_ACTIVITY_DURATION"])
    length = max(1, -(-int(min_duration) // slot_minutes))
    day_order = list(config["DAY_OF_WEEK_ORDER"])
    out = set()
    for d, day_name in enumerate(config["OPEN_DAYS"]):
        on = (week_start + datetime.timedelta(days=day_order.index(day_name))).date()
        opening = datetime.datetime.strptime(config["WORKING_HOURS"][day_name.lower()]["open"], "%H:%M")
        n_slots = config["SLOTS_PER_DAY"].get(day_name) or 0
        for w in windows:
            if not window_covers(w, day_name, on, day_order):
                continue
            start, end = _time(w.get("StartTime")), _time(w.get("EndTime"))
            if start is None or end is None:
                continue
            w_start = datetime.datetime.combine(opening.date(), start)
            w_end = datetime.datetime.combine(opening.date(), end)
            for s in range(n_slots - length + 1):
                slot_start = opening + datetime.timedelta(minutes=slot_minutes * s)
                if slot_start >= w_start and slot_start + datetime.timedelta(minutes=slot_minutes * length) <= w_end:
                    out.add((d, s))
    return out


def format_slots(slots: Iterable[Tuple[int, int]]) -> str:
    return ",".join(f"{d}-{s}" for d, s in sorted(slots))


def _parse(value) -> Set[Tuple[int, int]]:
    if value is None or (not isinstance(value, str) and pd.isna(value)) or not str(value).strip() \
            or str(value).strip().lower() in ("none", "nan"):
        return set()
    return {tuple(int(x) for x in p.strip().split("-")) for p in str(value).split(",")}


def windows_by_activity(rows: pd.DataFrame) -> Dict[int, List[Dict[str, Any]]]:
    out = defaultdict(list)
    for r in rows.to_dict("records"):
        if _is_true(r.get("IsDeleted", False)):
            continue
        out[int(r["CentreActivityID"])].append(r)
    return dict(out)


def apply_availability(
    activities: pd.DataFrame,
    windows: Mapping[int, List[Window]],
    week_start: datetime.datetime,
    config: Mapping[str, Any],
    restrict_flexible: bool = True,
) -> pd.DataFrame:
    """activities with FixedTimeSlots taken from availability where an activity has any."""
    if activities.empty or "CentreActivityID" not in activities.columns or not windows:
        return activities
    out = activities.copy()
    keep = []
    for idx, row in out.iterrows():
        rows = windows.get(int(row["CentreActivityID"])) if pd.notna(row["CentreActivityID"]) else None
        fixed = _is_true(row.get("IsFixed", False))
        if not rows or (not fixed and not restrict_flexible):
            keep.append(idx)
            continue
        slots = availability_slots(rows, row["MinDuration"], week_start, config)
        title = row.get("ActivityTitle", row["CentreActivityID"])
        if not slots:
            logger.info(f"{title!r} has availability but none this week, not scheduled")
            continue
        if fixed and _parse(row.get("FixedTimeSlots")) not in (set(), slots):
            logger.warning(f"{title!r} availability {format_slots(slots)} differs from FixedTimeSlots {row.get('FixedTimeSlots')}, using availability")
        out.at[idx, "FixedTimeSlots"] = format_slots(slots)
        keep.append(idx)
    return out.loc[keep]
