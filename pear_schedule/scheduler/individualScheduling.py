import datetime
from functools import partial
import logging
from typing import Dict, List, Mapping, Optional, Set

import pandas as pd
from sqlalchemy import Connection, Result, Select, and_, func, select
from pear_schedule.db import DB

from pear_schedule.db_utils.views import ActivitiesExcludedView, ActivitiesView, DisrecommendedActivitiesView, PatientsUnpreferredView, PatientsView, RecommendedActivitiesView, ValidRoutineActivitiesView
from pear_schedule.db_utils.writer import ScheduleWriter
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.scheduler.utils import checkActivityExcluded, parseFixedTimeArr, rescheduleActivity
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
    def _get_patient_data(cls, conn: Connection = None, week_end: datetime.datetime = None) -> Mapping[str, Mapping[str, Dict[str, str]]]:
        if not week_end:
            today = datetime.datetime.now()
            week_end = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(days=6)
            week_end = week_end.replace(hour=23, minute=59, second=59)

        patients: Mapping[str, Mapping[str, Dict[str, str]]] = {}

        # consolidate patient data
        for _, p in PatientsView.get_data(conn=conn).iterrows():
            pid = p["PatientID"]
            if pid not in patients:
                patients[pid] = {
                    "preferences":dict(), "exclusions": dict(), "dispreferences": dict()  # recommendations handled in compulsory scheduling
                }

            if p["ActivityEndDate"] <= week_end:
                continue

            patients[pid]["preferences"][p["PreferredActivityID"]] = True

        # add unpreferred activities
        for _, p in PatientsUnpreferredView.get_data(conn=conn).iterrows():
            pid = p["PatientID"]
            if pid not in patients:
                patients[pid] = {
                    "preferences":dict(), "exclusions": dict(), "dispreferences": dict()  # recommendations handled in compulsory scheduling
                }

            patients[pid]["dispreferences"][p["DispreferredActivityID"]] = True

        # add activity exclusions to patient data
        for _ , e in ActivitiesExcludedView.get_data(conn=conn).iterrows():
            pid = e["PatientID"]
            if pid not in patients:
                patients[pid] = {
                    "preferences":dict(), "exclusions": dict(), "dispreferences": dict()  # recommendations handled in compulsory scheduling
                }
            activity_id = e["ActivityID"]
            if e["ActivityID"] not in patients[pid]["exclusions"]:
                patients[pid]["exclusions"][activity_id] = e["EndDateTime"]
            else:
                patients[pid]["exclusions"][activity_id] = _get_max_enddate(
                    e["EndDateTime"], patients[pid]["exclusions"][activity_id]
                )

        # for the purposes of individual scheduling disrecommendations classified as exclusions also
        for _, r in DisrecommendedActivitiesView.get_data(conn=conn).iterrows():
            pid = r["PatientID"]
            if pid not in patients:
                patients[pid] = {
                    "preferences":dict(), "exclusions": dict(), "dispreferences": dict()  # recommendations handled in compulsory scheduling
                }
            activity_id = r["ActivityID"]
            patients[pid]["exclusions"][activity_id] = week_end

        return patients


class RecommendedRoutineActivityScheduler(IndividualActivityScheduler):
    @classmethod
    def fillSchedule(cls, schedules: Mapping[str, List[str]], week_start: datetime.datetime = None) -> None:
        week_start = week_start or datetime.datetime.now() - datetime.timedelta(days = datetime.datetime.now().weekday())
        today = datetime.datetime.now()
        week_end = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(days=6)
        week_end = week_end.replace(hour=23, minute=59, second=59)

        with DB.get_engine().begin() as conn:
            # pull recommendations
            recommendations: pd.DataFrame = RecommendedActivitiesView.get_data(conn=conn)
            recommendations.sort_values(by=["PatientID"])
            recommendations["FixedTimeSlots"] = recommendations["FixedTimeSlots"].astype(str)

            # filter out activities that are not available this week
            recommendations = recommendations[recommendations["ActivityEndDate"] > week_end]

            # add an extra row at end for easier handling of final patient
            dummy_row = recommendations.iloc[0:1].copy(deep=True)
            dummy_row["PatientID"] = None
            recommendations = pd.concat([recommendations, dummy_row]).reset_index(drop=True)

            # get patient level data
            patients = cls._get_patient_data(conn=conn)

            # get routine data
            routines = ValidRoutineActivitiesView.get_data(conn=conn)

            start = 0

            for curr, (_, row) in enumerate(recommendations.iterrows()):  # not using iterrows directly since need range indexing later
                if row["PatientID"] == recommendations.loc[start, "PatientID"]:
                    continue

                end = curr

                patient_id = recommendations["PatientID"][start]
                curr_df: pd.DataFrame = recommendations.iloc[start: end]
                patient_schedule = schedules[patient_id]

                fixedTimeSlotIdx = (curr_df["FixedTimeSlots"] != "") & (~curr_df["FixedTimeSlots"].isna())
                patient_routine = routines[routines["PatientID"] == patient_id]

                cls.__fillByFixedTimeSlots(patient_schedule, curr_df[fixedTimeSlotIdx], patients[patient_id], week_start)
                cls.__fillRoutines(patient_schedule, curr_df[fixedTimeSlotIdx], patient_routine, patients[patient_id], week_start)
                cls.__fillFlexibleActivities(patient_schedule, curr_df[~fixedTimeSlotIdx], patients[patient_id], week_start)

                start = end
    
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

            for slot, curr_activity in enumerate(day_schedule):
                if curr_activity:
                    continue
                # scan remaining allowed activities to find most constrained
                # not ideal but no. of activities is expected to be small so O(n2) is acceptable

                least_available = -1
                lowest_availability = float("inf")

                for row, activity in activities[~scheduled_idx].iterrows():
                    if checkActivityExcluded(
                        activity["ActivityID"], patient_info["exclusions"], day, week_start
                    ):
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

    @classmethod
    def __fillRoutines(
        cls, 
        patient_schedule: List[str], 
        activities: pd.DataFrame, 
        patient_routine: pd.DataFrame, 
        patient_info: Mapping[str, Dict[str, str]],
        week_start: datetime.datetime = None
    ):
        # set week_start to current week monday if not given
        week_start = week_start or \
            datetime.datetime.now() - datetime.timedelta(days = datetime.datetime.now().weekday())
        
        # consolidate routines for each time slot (if the routine is not excluded)
        routine_slots = {}
        for _, r in patient_routine.iterrows():
            for (day, time) in parseFixedTimeArr(r["FixedTimeSlots"]):
                if checkActivityExcluded(
                    r["ActivityID"], patient_info["exclusions"], day, week_start
                ):
                    continue

                # potentially if routines clash then it will be overriden
                # but routine activities shouldnt clash for the same patient to begin with
                routine_slots[(day, time)] = r["ActivityTitle"]

        # reformate activities for easier lookup
        activity_map = {
            r["ActivityTitle"]: parseFixedTimeArr(r["FixedTimeSlots"]) 
            for _, r in activities.iterrows()
        }

        # scan each routine_slot to check if it is occupied by an activity given
        for (day, time), routine_activity_title in routine_slots.items():
            current_activity = patient_schedule[day][time]

            if not current_activity:
                patient_schedule[day][time] = routine_activity_title
                continue
            
            if new_slot := rescheduleActivity(patient_schedule, day, time, activity_map[current_activity]):
                patient_schedule[new_slot[0]][new_slot[1]] = current_activity
                patient_schedule[day][time] = routine_activity_title
                continue

    @classmethod
    def __fillFlexibleActivities(
        cls, 
        patient_schedule: List[str], 
        activities: pd.DataFrame, 
        patient_info: Mapping[str, Dict[str, str]],
        week_start: datetime.datetime = None
    ):
        # set week_start to current week monday if not given
        week_start = week_start or \
            datetime.datetime.now() - datetime.timedelta(days = datetime.datetime.now().weekday())

        # prevent scheduling more than necessary
        scheduled_activities = set()

        for day, day_schedule in enumerate(patient_schedule):
            for time, existing_activity in enumerate(day_schedule):
                if existing_activity:
                    continue

                for _, a in activities.iterrows():
                    if a["ActivityID"] in scheduled_activities or \
                        checkActivityExcluded(
                            a["ActivityID"], patient_info["exclusions"], day, week_start
                    ):
                        continue

                    patient_schedule[day][time] = a["ActivityTitle"]
                    scheduled_activities.add(a["ActivityTitle"])

                if len(scheduled_activities) == len(activities):
                    return


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
            dispreferences: Set[str] = patient["dispreferences"]

            avail_activities = activities[~activities["ActivityID"].isin(exclusions)]
            avail_activities = avail_activities[["ActivityID", "ActivityTitle", "FixedTimeSlots", "MinDuration", "MaxDuration"]]

            preference_idx = avail_activities["ActivityID"].isin(preferences)
            non_preference_idx = (~avail_activities["ActivityID"].isin(dispreferences)) & ~preference_idx
            preferred_activities = avail_activities[preference_idx]
            non_preferred_activites = avail_activities[non_preference_idx]

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
                            new_activity = "Free and Easy"
                        curr_day_activities.add(new_activity)
                        day_sched[i] = new_activity
                    i += 1

    @classmethod
    def __findActivityBySlot(
        cls, 
        activities: pd.DataFrame, 
        used_activities: Set[str], 
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
                timeSlots = [t for t in timeSlots if t[0] == day and t[1] == slot and t[1] + minDuration < slot + slot_size]

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
    def getMostUpdatedSchedules(
        cls, 
        patientIDs: List[str], 
        conn: Connection, 
        curr_date: datetime.date = None
    ) -> pd.DataFrame:
        db_tables: DBTABLES = cls.config["DB_TABLES"]
        schedule_table = DB.schema.tables[db_tables.SCHEDULE_TABLE]

        # use datetime to avoid db side issues when comparing date and datetime
        curr_date = curr_date or datetime.date.today()
        curr_week_start = datetime.datetime.combine(curr_date, datetime.time(0, 0, 0))
        curr_week_start = curr_week_start - datetime.timedelta(days = datetime.datetime.now().weekday())
        next_week_start = curr_week_start + datetime.timedelta(days=7)

        latest_sched_cte = select(
            schedule_table.c["PatientID"],
            func.max(schedule_table.c["UpdatedDateTime"]).label("UpdatedDateTime")
        ).where(
            schedule_table.c["StartDate"] >= curr_week_start,
            schedule_table.c["EndDate"] < next_week_start,
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
        update_date = update_date or datetime.date.today()
        week_end = update_date - datetime.timedelta(days=update_date.weekday()) + datetime.timedelta(days=6)
        week_end = datetime.datetime.combine(week_end, datetime.time(23, 59, 59))
        
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

            latest_schedules = cls.getMostUpdatedSchedules(patientIDs, conn, update_date)

            # use the original individual scheduler to update activities
            patient_data = cls._get_patient_data(conn)
            activities = ActivitiesView.get_data(conn)
            activities = activities[activities["EndDate"] > week_end]
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
