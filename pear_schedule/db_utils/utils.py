from sqlalchemy import Select
from datetime import datetime, timedelta
from typing import List, Mapping

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