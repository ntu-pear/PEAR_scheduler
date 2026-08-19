import datetime
import logging
from typing import List, Mapping, Optional

from pear_schedule.db_utils.views import AdhocActivityView
from pear_schedule.scheduler.baseScheduler import BaseScheduler

logger = logging.getLogger(__name__)


def _to_date(value) -> Optional[datetime.date]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    try:
        return value.date()
    except (AttributeError, TypeError):
        return None


class AdhocScheduler(BaseScheduler):
    @classmethod
    def fillSchedule(cls, schedules: Mapping[str, List[str]]) -> None:
        adhoc_df = AdhocActivityView.get_data()
        if adhoc_df.empty:
            return

        today = datetime.datetime.now()
        week_start = (today - datetime.timedelta(days=today.weekday())).date()
        week_end = week_start + datetime.timedelta(days=len(cls.config["OPEN_DAYS"]) - 1)
        replacements_applied = 0

        for _, row in adhoc_df.iterrows():
            patient_id = row.get("PatientID")
            if patient_id not in schedules:
                continue

            old_activity = row.get("OldActivityTitle")
            new_activity = row.get("NewActivityTitle")
            if not old_activity or not new_activity:
                continue

            start_date = _to_date(row.get("StartDate"))
            end_date = _to_date(row.get("EndDate"))

            if start_date is None or end_date is None:
                continue

            if start_date > week_end or end_date < week_start:
                continue

            overlap_start = max(start_date, week_start)
            overlap_end = min(end_date, week_end)
            start_idx = (overlap_start - week_start).days
            end_idx = (overlap_end - week_start).days

            for day_idx in range(start_idx, end_idx + 1):
                for slot_idx, activity in enumerate(schedules[patient_id][day_idx]):
                    if activity == old_activity:
                        schedules[patient_id][day_idx][slot_idx] = new_activity
                        replacements_applied += 1
        if replacements_applied:
            logger.info(f"Applied {replacements_applied} adhoc slot replacements")
