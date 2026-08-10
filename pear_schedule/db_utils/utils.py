from sqlalchemy import Select
from datetime import datetime, timedelta
from typing import List, Mapping

def compile_query(query: Select) -> str:
    # literal binds might cause errors if datetime is ever used
    return query.compile(compile_kwargs={"literal_binds": True})

def get_monday():
    today=datetime.now()
    monday = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    return monday

def get_next_sunday():
    today = datetime.now()
    if today.weekday() == 6:  # If today is Sunday
        days_until_sunday = 7  # Add 7 days to get the date of the following Sunday
    else:
        days_until_sunday = (6 - today.weekday()) % 7  # Calculate the number of days until Sunday
    next_sunday = today + timedelta(days=days_until_sunday)  # Add days to today's date to get the next Sunday
    next_sunday = next_sunday.replace(hour=23, minute=59, second = 59)
    return next_sunday

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