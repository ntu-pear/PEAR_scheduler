# configprod.py can't just be imported into tests - OPEN_DAYS, SLOTS_PER_DAY, WORKING_HOURS,
# and GROUP_TIMESLOT_MAPPING only get computed at FastAPI startup in create_app(), so there's
# no static dict to grab. This builds an equivalent one by hand instead.

import pandas as pd

def make_scheduler_config(**overrides) -> dict:
    open_days = overrides.pop("OPEN_DAYS", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    slots_per_day = overrides.pop("SLOTS_PER_DAY", {day: 8 for day in open_days})
    min_activity_duration = overrides.pop("MIN_ACTIVITY_DURATION", 30)
    max_activity_duration = overrides.pop("MAX_ACTIVITY_DURATION", 60)
    group_timeslots = overrides.pop("GROUP_TIMESLOTS", 15)
    group_timeslot_mapping = overrides.pop(
        "GROUP_TIMESLOT_MAPPING",
        [(day_idx % len(open_days), 2 + (i % 3)) for i, day_idx in enumerate(range(group_timeslots))],
    )
    target_weekly_group_activities = overrides.pop("TARGET_WEEKLY_GROUP_ACTIVITIES", 2)
    day_of_week_order = overrides.pop(
        "DAY_OF_WEEK_ORDER", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    )
    days = overrides.pop("DAYS", len(open_days))
    working_hours = overrides.pop(
        "WORKING_HOURS", {day.lower(): {"open": "09:00", "close": "13:00"} for day in open_days}
    )
    day_timeslots = overrides.pop(
        "DAY_TIMESLOTS", [f"{9 + i // 2:02d}:{'00' if i % 2 == 0 else '30'}-{9 + (i + 1) // 2:02d}:{'00' if (i + 1) % 2 == 0 else '30'}" for i in range(slots_per_day.get(open_days[0], 8))]
    )
    std_date_format = overrides.pop("STD_DATE_FORMAT", "%Y-%m-%d")

    config = {
        "OPEN_DAYS": open_days,
        "SLOTS_PER_DAY": slots_per_day,
        "MIN_ACTIVITY_DURATION": min_activity_duration,
        "MAX_ACTIVITY_DURATION": max_activity_duration,
        "GROUP_TIMESLOTS": group_timeslots,
        "GROUP_TIMESLOT_MAPPING": group_timeslot_mapping,
        "TARGET_WEEKLY_GROUP_ACTIVITIES": target_weekly_group_activities,
        "DAY_OF_WEEK_ORDER": day_of_week_order,
        "DAYS": days,
        "WORKING_HOURS": working_hours,
        "DAY_TIMESLOTS": day_timeslots,
        "STD_DATE_FORMAT": std_date_format,
    }
    config.update(overrides)
    return config


def empty_view_df(columns) -> pd.DataFrame:
    """Empty DataFrame with the right columns, for views a given test doesn't care about."""
    return pd.DataFrame({col: [] for col in columns})
