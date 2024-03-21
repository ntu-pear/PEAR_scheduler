from sqlalchemy import Select
from datetime import datetime, timedelta

def compile_query(query: Select) -> str:
    # literal binds might cause errors if datetime is ever used
    return query.compile(compile_kwargs={"literal_binds": True})


def get_next_sunday():
    today = datetime.now()
    if today.weekday() == 6:  # If today is Sunday
        days_until_sunday = 7  # Add 7 days to get the date of the following Sunday
    else:
        days_until_sunday = (6 - today.weekday()) % 7  # Calculate the number of days until Sunday
    next_sunday = today + timedelta(days=days_until_sunday)  # Add days to today's date to get the next Sunday
    next_sunday = next_sunday.replace(hour=23, minute=59, second = 59)
    return next_sunday