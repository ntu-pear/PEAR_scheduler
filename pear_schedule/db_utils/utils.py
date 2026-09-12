from sqlalchemy import Select
from datetime import datetime, timedelta
from typing import List, Mapping, Optional
import logging

logger = logging.getLogger(__name__)

def compile_query(query: Select) -> str:
    # literal binds might cause errors if datetime is ever used
    return query.compile(compile_kwargs={"literal_binds": True})

def get_week_start() -> datetime:
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)

def get_week_end() -> datetime:
    today = datetime.now()
    days_until_sunday = 6 - today.weekday()
    sunday = today + timedelta(days=days_until_sunday)
    return sunday.replace(hour=23, minute=59, second=59, microsecond=0)

def timeslot_index(offset: timedelta, duration_minutes: int) -> int:
    """Floor-divide a clock-time offset by a slot duration to get a 0-based slot index.

    E.g. offset=45min, duration_minutes=30 -> 1 (the second 30-minute slot).
    """
    return offset // timedelta(minutes=duration_minutes)

def day_timeslot_label(day: str, index: int, working_hours: Mapping, min_activity_duration: int) -> str:
    """"HH:MM-HH:MM" label for one slot on one day, built from real opening hours.

    E.g. day="Monday", index=1, working_hours={"monday": {"open": "09:00", ...}},
    min_activity_duration=30 -> "09:30-10:00".
    """
    open_time = datetime.strptime(working_hours[day.lower()]["open"], "%H:%M")
    start = open_time + timedelta(minutes=min_activity_duration * index)
    end = start + timedelta(minutes=min_activity_duration)
    return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"

def day_timeslot_labels(day: str, slots_per_day: int, working_hours: Mapping, min_activity_duration: int) -> List[str]:
    """List of day_timeslot_label(), one per slot in the day"""
    return [day_timeslot_label(day, i, working_hours, min_activity_duration) for i in range(slots_per_day)]

def decode_day_of_week_bitmask(day_of_week: Optional[int], day_of_week_order: List[str]) -> List[str]:
    """day_of_week is a bitmask, bit 1<<i = day_of_week_order[i]. Returns the matched day names."""
    if not day_of_week:
        return []
    return [day for i, day in enumerate(day_of_week_order) if day_of_week & (1 << i)]

def routine_time_slots(
    day_of_week: Optional[int],
    start_time: str,
    end_time: str,
    day_of_week_order: List[str],
    open_days: List[str],
    working_hours: Mapping,
    min_activity_duration: int,
) -> Optional[str]:
    """Builds a "day-slot,day-slot" FixedTimeSlots-style string from a routine's day_of_week
    bitmask and start/end time. Drops days not in open_days. Expands multi-slot spans.
    Returns None if nothing matches.
    """
    matched_days = [day for day in decode_day_of_week_bitmask(day_of_week, day_of_week_order) if day in open_days]
    if not matched_days or not start_time or not end_time:
        return None

    start_dt = datetime.strptime(start_time, "%H:%M:%S")
    end_dt = datetime.strptime(end_time, "%H:%M:%S")
    num_slots = (end_dt - start_dt) // timedelta(minutes=min_activity_duration)
    if num_slots < 1:
        logger.warning(f"Routine end_time {end_time} does not exceed start_time {start_time} by a full slot, defaulting to 1 slot")
        num_slots = 1

    pairs = []
    for day in matched_days:
        day_idx = open_days.index(day)
        opening_time = datetime.strptime(working_hours[day.lower()]["open"], "%H:%M")
        start_slot = timeslot_index(start_dt - opening_time, min_activity_duration)
        pairs.extend(f"{day_idx}-{start_slot + i}" for i in range(num_slots))

    return ",".join(pairs)