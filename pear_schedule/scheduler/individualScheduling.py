import datetime
from functools import partial
import logging
from typing import Dict, List, Mapping, Optional, Set

import pandas as pd
from sqlalchemy import Connection, Result, Select, and_, func, select
from pear_schedule.db import DB

from pear_schedule.db_utils.views import ActivitiesExcludedView, ActivitiesView, PatientsView, RecommendedActivitiesView
from pear_schedule.db_utils.writer import ScheduleWriter
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.utils import DBTABLES



logger = logging.getLogger(__name__)


def _get_max_enddate(d1, d2):
    if d1 is None:
        return d1
    if d2 is None:
        return d2
    return max(d1, d2)


class IndividualActivityScheduler(BaseScheduler):
    @classmethod
    def _get_patient_data(cls, conn: Connection = None) -> Mapping[str, Mapping[str, Dict[str, str]]]:
        patients: Mapping[str, Mapping[str, Dict[str, str]]] = {}

        # consolidate patient data
        for _, p in PatientsView.get_data(conn=conn).iterrows():
            pid = p["PatientID"]
            if pid not in patients:
                patients[pid] = {
                    "preferences":dict(), "exclusions": dict()  # recommendations handled in compulsory scheduling
                }

            patients[pid]["preferences"][p["PreferredActivityID"]] = True

        # add activity exclusions to patient data
        for _ , e in ActivitiesExcludedView.get_data().iterrows():
            pid = e["PatientID"]
            activity_id = e["ActivityID"]
            if e["ActivityID"] not in patients[pid]["exclusions"]:
                patients[pid]["exclusions"][activity_id] = e["EndDateTime"]
            else:
                patients[pid]["exclusions"][activity_id] = _get_max_enddate(
                    e["EndDateTime"], patients[pid]["exclusions"][activity_id]
                )


        return patients


class RecommendedActivityScheduler(IndividualActivityScheduler):
    @classmethod
    def fillSchedule(cls, schedules: Mapping[str, List[str]], week_start: datetime.datetime = None) -> None:
        with DB.get_engine().begin() as conn:
            # pull recommendations
            recommendations: pd.DataFrame = RecommendedActivitiesView.get_data(conn=conn)
            recommendations.sort_values(by=["PatientID"])
            recommendations["FixedTimeSlots"] = recommendations["FixedTimeSlots"].astype(str)

            # add an extra row at end for easier handling of final patient
            dummy_row = recommendations.iloc[0:1].copy(deep=True)
            dummy_row["PatientID"] = None
            recommendations = pd.concat([recommendations, dummy_row]).reset_index(drop=True)

            # get patient level data
            patients = cls._get_patient_data(conn=conn)

            start = 0

            for curr, (_, row) in enumerate(recommendations.iterrows()):  # not using iterrows directly since need range indexing later
                if row["PatientID"] == recommendations.loc[start, "PatientID"]:
                    continue

                end = curr

                patient_id = recommendations["PatientID"][start]
                curr_df: pd.DataFrame = recommendations.iloc[start: end]
                patient_schedule = schedules[patient_id]

                cls.__fillByFixedTimeSlots(patient_schedule, curr_df, patients[patient_id], week_start)

                start = curr
    
    @classmethod
    def __fillByFixedTimeSlots(
        cls, 
        patient_schedule: List[str], 
        activities: pd.DataFrame, 
        patient_info: Mapping[str, Dict[str, str]],
        week_start: datetime.datetime = None
    ):
        # set week_start to current week monday if not given
        week_start = week_start or \
            datetime.datetime.now() - datetime.timedelta(days = datetime.datetime.now().weekday())

        scheduled_idx = pd.Series(False, index=activities.index)
        for day, day_schedule in enumerate(patient_schedule):

            if scheduled_idx.all():
                break

            day_date = week_start + datetime.timedelta(days=day)

            for slot, curr_activity in enumerate(day_schedule):
                if curr_activity:
                    continue
                # scan remaining allowed activities to find most constrained
                # not ideal but no. of activities is expected to be small so O(n2) is acceptable

                least_available = -1
                lowest_availability = float("inf")

                for row, activity in activities[~scheduled_idx].iterrows():
                    if (activity["ActivityID"] in patient_info["exclusions"]):
                        exclusion_end = patient_info["exclusions"][activity["ActivityID"]]

                        # if activity exclusion has not yet ended then ignore
                        # include current day since it can be unsafe to perform activities on the
                        # day exclusion ends (eg remove leg cast then walk same day)
                        if exclusion_end is None or exclusion_end >= day_date:
                            continue

                    curr_availability = calculate_activity_availabillity(day, slot, activity["FixedTimeSlots"])

                    if not curr_availability:
                        scheduled_idx.loc[row] = True

                    if curr_availability < lowest_availability:
                        least_available = row
                        lowest_availability = curr_availability

                if least_available < 0:
                    break

                scheduled_idx.loc[least_available] = True

                day_schedule[slot] = activities.loc[least_available, "ActivityTitle"]


class PreferredActivityScheduler(IndividualActivityScheduler):
    @classmethod
    def fillSchedule(cls, schedules: Mapping[str, List[str]]) -> None:
        cls.fillPreferences(schedules)

    @classmethod
    def fillPreferences(cls, schedules: Mapping[str, List[str]], conn: Connection = None, patients: Mapping = None):
        patients = patients or cls._get_patient_data(conn=conn)

        # consolidate activity data
        activities: pd.DataFrame = ActivitiesView.get_data(conn=conn)  # non compulsory individual activities
        # activities = activities.sample(frac=1)\
        #     .reset_index(drop=True)

        for pid, sched in schedules.items():
            if pid not in patients:
                logger.error(f"unknown patientID {pid} found in schedules")
                continue
            patient = patients[pid]

            exclusions: Set[str] = patient["exclusions"]
            preferences: Set[str] = patient["preferences"]

            avail_activities = activities[~activities["ActivityID"].isin(exclusions)]
            avail_activities = avail_activities[["ActivityID", "ActivityTitle", "FixedTimeSlots", "MinDuration", "MaxDuration"]]

            preference_idx = avail_activities["ActivityID"].isin(preferences)
            preferred_activities = avail_activities[preference_idx]
            non_preferred_activites = avail_activities[~preference_idx]

            for day, day_sched in enumerate(sched):
                curr_day_activities = set()

                i = 0
                while i < len(day_sched):
                    if not day_sched[i]:
                        j = i + 1
                        while (j < len(day_sched) and not day_sched[j]):
                            j += 1
                        if i >= len(day_sched):
                            break

                        find_activity = partial(cls.__findActivityBySlot, day=day, slot=i, slot_size=j-i)
                        new_activity = \
                            find_activity(preferred_activities, curr_day_activities) or \
                            find_activity(non_preferred_activites, curr_day_activities)

                        if not new_activity:
                            continue
                        curr_day_activities.add(new_activity)
                        day_sched[i] = new_activity
                    i += 1

    @classmethod
    def __findActivityBySlot(
        cls, 
        activities: pd.DataFrame, 
        used_activities: set[str], 
        day: int, 
        slot: int,
        slot_size: int,
    ) -> Optional[str]:
        if activities.empty:
            return
        
        activities = activities.sample(frac=1)\
            .reset_index(drop=True)
        
        out = [-1, 1000, False]

        for i, a in activities.iterrows():
            if a["ActivityTitle"] in used_activities:
                continue

            minDuration = max(1, a["MinDuration"])

            if a["FixedTimeSlots"]:
                timeSlots = map(lambda x: x.split("-"), a["FixedTimeSlots"].split(","))
                timeSlots = [t for t in timeSlots if t[0] == day and t[1] >= slot and t[1] + minDuration < slot + slot_size]

                if not timeSlots:
                    continue
                else:
                    earliest_end = min(t[1] + minDuration for t in timeSlots)
            else:
                if out[2]:
                    continue
                earliest_end = slot + minDuration

            if earliest_end < out[1] and bool(a["FixedTimeSlots"]) >= out[2]:
                out[0] = i
                out[1] = earliest_end
                out[2] = bool(a["FixedTimeSlots"])
        
        if out[0] < 0:
            return None

        return activities.iloc[out[0]]["ActivityTitle"]

    @classmethod
    def _get_most_updated_schedules(
        cls, 
        patientIDs: List[str], 
        conn: Connection, 
        curr_date: datetime.date = None
    ) -> pd.DataFrame:
        db_tables: DBTABLES = cls.config["DB_TABLES"]
        schedule_table = DB.schema.tables[db_tables.SCHEDULE_TABLE]

        # use datetime to avoid db side issues when comparing date and datetime
        curr_date = curr_date or datetime.date.today()
        curr_day_start = datetime.datetime.combine(curr_date, datetime.time(0, 0, 0))
        next_day_start = curr_day_start + datetime.timedelta(days=1)

        latest_sched_cte = select(
            schedule_table.c["PatientID"],
            func.max(schedule_table.c["UpdatedDateTime"]).label("UpdatedDateTime")
        ).where(
            schedule_table.c["StartDate"] >= curr_day_start,
            schedule_table.c["StartDate"] < next_day_start,
            schedule_table.c["PatientID"].in_(patientIDs),
            schedule_table.c["IsDeleted"] == False,
        ).group_by(schedule_table.c["PatientID"]).cte("latest_schedules")

        stmt = select(schedule_table).join(
            latest_sched_cte, and_(
                latest_sched_cte.c["PatientID"] == schedule_table.c["PatientID"],
                latest_sched_cte.c["UpdatedDateTime"] == schedule_table.c["UpdatedDateTime"],
            )
        ).where(
            schedule_table.c["IsDeleted"] == False,
        )

        return pd.read_sql(stmt, conn)

    @classmethod
    def update_schedules(cls, patientIDs: List[str] = None, update_date: datetime.date = None):
        db_tables: DBTABLES = cls.config["DB_TABLES"]
        patient_table = DB.schema.tables[db_tables.PATIENT_TABLE]

        # this entire chunk needs to be a single transaction
        with DB.get_engine().begin() as conn:
            if not len(patientIDs):
                stmt: Select = select(
                    patient_table.c["PatientID"]
                ).where(patient_table.c["IsDeleted"] == False)

                res: Result = conn.execute(stmt)
                patientIDs = set(pid for (pid,) in res.all())

            logger.info(f"updating schedules for patients {patientIDs}")

            latest_schedules = cls._get_most_updated_schedules(patientIDs, conn, update_date)

            # use the original individual scheduler to update activities
            patient_data = cls._get_patient_data(conn)
            activities = ActivitiesView.get_data(conn)
            activities_title_lookup = {
                row["ActivityTitle"]: row["ActivityID"] for _, row in activities.iterrows()
            }

            def check_excluded(pid, activityTitle):
                activityTitle = activityTitle.strip()
                return activities_title_lookup.get(activityTitle, None) in patient_data[pid]["exclusions"]

            formatted_schedules = {}
            schedule_meta = {}
            for _, row in latest_schedules.iterrows():
                formatted_schedules[row["PatientID"]] = [
                    [i if not check_excluded(row["PatientID"], i.split("|")[0]) else "" 
                        for i in row[day].split("-")
                    ]
                    for day in cls.config["DAY_OF_WEEK_ORDER"]
                ]

                schedule_meta[row["PatientID"]] = {\
                    "CreatedDateTime": row["CreatedDateTime"],
                    "ScheduleID": row["ScheduleID"],
                    "StartDate": row["StartDate"],
                    "EndDate": row["EndDate"],
                }

            cls.fillPreferences(formatted_schedules, conn, patient_data)

            # recombine the updated and original schedules
            for _, row in latest_schedules.iterrows():
                new_schedule = formatted_schedules[row["PatientID"]]
                for d, day in enumerate(cls.config["DAY_OF_WEEK_ORDER"]):
                    old_schedule = row[day].split("-")
                    # put medication back into the schedule
                    new_schedule[d] = [
                        "|".join((new_activity, *old_activity.split("|")[1:2]))
                        for (new_activity, old_activity) in zip(new_schedule[d], old_schedule)
                    ]

            write_result = ScheduleWriter.write(
                formatted_schedules, overwriteExisting=True, conn=conn, schedule_meta=schedule_meta,
            )
            if not write_result:
                logger.error("Schedule updating failed")



def calculate_activity_availabillity(day: int, slot: int, fixedTimeSlots: str):
    if not fixedTimeSlots:
        return 1000

    time_slots = fixedTimeSlots.split(",")

    def validate(ts: str):
        d, s = ts.split("-")
        return int(d) > day or (int(d) == day and int(s) >= slot)
    
    tally = sum(map(validate, time_slots))
    
    return tally
