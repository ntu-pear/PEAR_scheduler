import datetime
from collections import Counter
from functools import partial
import json
import logging
from typing import Dict, List, Mapping, Optional, Set, NamedTuple
from pandas import Timestamp
import pandas as pd
from sqlalchemy import Connection, Result, Select, and_, func, select
from pear_schedule.db import DB

from pear_schedule.db_utils.utils import day_timeslot_labels
from pear_schedule.db_utils.views import ActivitiesExcludedView, ActivitiesView, DisrecommendedActivitiesView, PatientsUnpreferredView, PatientsView, RecommendedActivitiesView, ValidRoutineActivitiesView
from pear_schedule.db_utils.writer import ScheduleWriter
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.scheduler import trace
from pear_schedule.scheduler.gapFill import PoolActivity, build_candidates, solve_day
from pear_schedule.scheduler.invariants import PatientRules, free_runs, unfillable_reason
from pear_schedule.scheduler.medicationScheduling import medicationScheduler
from pear_schedule.scheduler.utils import checkActivityExcluded, parseFixedTimeArr, rescheduleActivity
from pear_schedule.utils import DBTABLES



logger = logging.getLogger(__name__)


def _get_max_enddate(d1, d2):
    # None/NaT means no end, so it wins
    if d1 is None or pd.isna(d1):
        return None
    if d2 is None or pd.isna(d2):
        return None
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
            p["ActivityEndDate"] = Timestamp(p["ActivityEndDate"])
            if pid not in patients:
                patients[pid] = {
                    "preferences":set(), "exclusions": dict(), "dispreferences": set()  # recommendations handled in compulsory scheduling
                }
            
            # If ActivityEndDate is Null, means the Activity will restart every week. #ToBeConfirmed
            
            if p["ActivityEndDate"] <= week_end:
                continue


            patients[pid]["preferences"].add(p["PreferredActivityID"])

        # add unpreferred/neutral activities
        for _, p in PatientsUnpreferredView.get_data(conn=conn).iterrows():
            pid = p["PatientID"]
            if pid not in patients:
                patients[pid] = {
                    "preferences":set(), "exclusions": dict(), "dispreferences": set()  # recommendations handled in compulsory scheduling
                }
            if Timestamp(p["ActivityEndDate"]) <= week_end:
                continue

            patients[pid]["dispreferences"].add(p["DispreferredActivityID"])

        # add activity exclusions to patient data
        for _ , e in ActivitiesExcludedView.get_data(conn=conn).iterrows():
            pid = e["PatientID"]
            if pid not in patients:
                patients[pid] = {
                    "preferences":set(), "exclusions": dict(), "dispreferences": set()  # recommendations handled in compulsory scheduling
                }
            activity_id = e["ActivityID"]
            if activity_id not in patients[pid]["exclusions"]:
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
                    "preferences":set(), "exclusions": dict(), "dispreferences": set()  # recommendations handled in compulsory scheduling
                }
            activity_id = r["ActivityID"]
            patients[pid]["exclusions"][activity_id] = week_end
            patients[pid].setdefault("not_recommended", set()).add(activity_id)

        return patients


def _no_patient_data() -> Dict:
    # patient with no likes, dislikes or exclusions yet
    return {"preferences": set(), "exclusions": dict(), "dispreferences": set(), "not_recommended": set()}


class RecommendedRoutineActivityScheduler(IndividualActivityScheduler):
    @classmethod
    def fillSchedule(cls, schedules: Mapping[str, List[str]], week_start: datetime.datetime = None) -> None:
        week_start = week_start or datetime.datetime.now() - datetime.timedelta(days = datetime.datetime.now().weekday())
        week_end = week_start + datetime.timedelta(days=6)
        week_end = week_end.replace(hour=23, minute=59, second=59)

        with DB.get_engine().begin() as conn:
            # pull recommendations
            recommendations: pd.DataFrame = RecommendedActivitiesView.get_data(conn=conn)
            recommendations = recommendations.sort_values(by=["PatientID"])
            # NULL for flexible activities, astype(str) alone turns it into "None"
            recommendations["FixedTimeSlots"] = recommendations["FixedTimeSlots"].fillna("").astype(str)

            # break down fixedTimeSlots into a list (day,slot) pairs
            proc_fixedTimeSlots:pd.Series = recommendations["FixedTimeSlots"].apply(lambda x: {(int(a),int(b)) for a,b in map(lambda y: y.split('-'), x.split(','))} if pd.notna(x) and x.strip() != "" else set())
            recommendations = recommendations.assign(ProcessedTimeSlots=proc_fixedTimeSlots)

            #convert to pd.timestamp to handle as activityenddate is beyond 2999, and it needs to be datetime
            recommendations["ActivityEndDate"] = recommendations["ActivityEndDate"].apply(pd.Timestamp)
 
            # filter out activities that are not available this week, i.e. only consider activities that run past week_end
            # null ActivityEndDate means indefinite (never expires), so it always passes
            not_expired = recommendations["ActivityEndDate"].isna() | (recommendations["ActivityEndDate"] > week_end)
            for _, r in recommendations[~not_expired].iterrows():
                trace.record(trace.STAGE_RECOMMENDED, r["PatientID"], trace.FILTERED, "expired",
                             activity=r["ActivityTitle"], end_date=str(r["ActivityEndDate"]))
            recommendations = recommendations[not_expired]

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
                # grab multiple recommended activities for the same patient in one go
                if row["PatientID"] == recommendations.loc[start, "PatientID"]:
                    continue

                end = curr

                patient_id = recommendations["PatientID"][start]
                try:
                    curr_df: pd.DataFrame = recommendations.iloc[start: end]
                    patient_schedule = schedules[patient_id]

                    fixedTimeSlotIdx = (curr_df["FixedTimeSlots"] != "") & (~curr_df["FixedTimeSlots"].isna())
                    patient_routine = routines[routines["PatientID"] == patient_id]
                    patient_info = patients.get(patient_id) or _no_patient_data()

                    cls.__fillByFixedTimeSlots(patient_schedule, curr_df[fixedTimeSlotIdx], patient_info, week_start, patient_id=patient_id)
                    cls.__fillRoutines(patient_schedule, curr_df[fixedTimeSlotIdx], patient_routine, patient_info, week_start, patient_id=patient_id)
                    cls.__fillFlexibleActivities(patient_schedule, curr_df[~fixedTimeSlotIdx], patient_info, week_start, patient_id=patient_id)
                except Exception as e:
                    logger.exception(f"Recommended/routine scheduling failed for patient {patient_id}, skipping")
                    trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.ERROR, "stage_exception", error=repr(e))

                start = end

            # patients with a routine but no recommendations never hit the loop above, so
            # they need their own pass here
            no_fixed_activities = pd.DataFrame(columns=["ActivityTitle", "FixedTimeSlots"])
            recommended_patient_ids = set(recommendations["PatientID"].dropna().unique())
            routine_only_patient_ids = set(routines["PatientID"].unique()) - recommended_patient_ids

            for patient_id in routine_only_patient_ids:
                try:
                    patient_schedule = schedules[patient_id]
                    patient_routine = routines[routines["PatientID"] == patient_id]
                    patient_info = patients.get(patient_id) or _no_patient_data()

                    cls.__fillRoutines(patient_schedule, no_fixed_activities, patient_routine, patient_info, week_start, patient_id=patient_id)
                except Exception as e:
                    logger.exception(f"Routine scheduling failed for patient {patient_id}, skipping")
                    trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.ERROR, "stage_exception", error=repr(e))

    @classmethod
    def __fillByFixedTimeSlots(
        cls, 
        patient_schedule: List[List[str]], 
        activities: pd.DataFrame, 
        patient_info: Mapping[str, Dict[str, str]],
        week_start: datetime.datetime = None,
        patient_id = None,
    ):
        # set week_start to current week monday if not given
        week_start = week_start or \
            datetime.datetime.now() - datetime.timedelta(days = datetime.datetime.now().weekday())
        series_timeslots = activities["ProcessedTimeSlots"]
        timeslots_set = set.union(*series_timeslots) if len(series_timeslots) else set()

        scheduled_idx = pd.Series(False, index=activities.index) # refers to all activities recommended to a specific patient
        placed_rows = set()
        
        for (day, slot) in timeslots_set:
            if scheduled_idx.all():
                break

            if day >= len(cls.config["OPEN_DAYS"]) or slot >= cls.config["SLOTS_PER_DAY"].get(cls.config["OPEN_DAYS"][day]) \
                or patient_schedule[day][slot]:
                continue
            # scan remaining allowed activities to find most constrained (fewer available time slots)
            # not ideal but no. of activities is expected to be small so O(n2) is acceptable

            least_available = -1
            lowest_availability = float("inf")

            available_activities: pd.DataFrame = activities[~scheduled_idx]
            for row, activity in available_activities.iterrows():
                if checkActivityExcluded(
                    activity["ActivityID"], patient_info["exclusions"], day, week_start
                ):
                    continue

                # curr_availability: activity can be scheduled at this slot or at later slots (it has higher availability if the number of said slots is high)
                curr_availability: int = calculate_activity_availabillity(cls, day, slot, activity["ProcessedTimeSlots"])

                # if activity can scheduled at a starting slot, first check whether there are enough consecutive slots for a 1hr or longer activity
                if curr_availability < float("inf"):
                    num_slots = activity["MinDuration"] // -cls.config["MIN_ACTIVITY_DURATION"] * -1
                    for i in range(1, num_slots):
                        if (num_slots > 1 and slot+i >= cls.config["SLOTS_PER_DAY"].get(cls.config["OPEN_DAYS"][day])) or patient_schedule[day][slot+i]:
                            curr_availability = float("inf")
                            break

                # if there are no such slots (0), we are done with this activity, i.e. cannot be scheduled anymore, or was scheduled
                if not curr_availability:
                    scheduled_idx.loc[row] = True

                if curr_availability < lowest_availability:
                    least_available = row
                    lowest_availability = curr_availability
                # if tie in availability, prioritise activity with longer duration
                elif curr_availability == lowest_availability and lowest_availability != float("inf"):
                    least_available = row if activity["MinDuration"] > activities.loc[least_available, "MinDuration"] else least_available
                    
            if least_available < 0:
                continue

            # attempt to schedule the most constrained activity first, because other activities have higher availability and should thus be able to be scheduled later
            # availability should apply to activities that can be scheduled at this slot or later
            scheduled_idx.loc[least_available] = True
                
            # if the activity determined to be scheduled at this starting slot > MIN_DURATION, fill adjacent slots with activity title
            selected_activity_row = activities.loc[least_available]
            selected_activity = selected_activity_row["ActivityTitle"]
            for i in range((selected_activity_row["MinDuration"] // -cls.config["MIN_ACTIVITY_DURATION"]) * -1):
                patient_schedule[day][slot + i] = selected_activity
            placed_rows.add(least_available)
            trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.PLACED,
                         "recommended_over_dislike" if selected_activity_row["ActivityID"] in patient_info.get("dispreferences", set())
                         else "most_constrained_fixed_slot",
                         activity=selected_activity, day=day, slot=slot,
                         remaining_slots=None if lowest_availability == float("inf") else int(lowest_availability))

        for row, activity in activities.iterrows():
            if row not in placed_rows:
                days = {d for d, _ in activity["ProcessedTimeSlots"]}
                excluded = bool(days) and all(
                    checkActivityExcluded(activity["ActivityID"], patient_info["exclusions"], d, week_start) for d in days)
                trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.DROPPED,
                             "excluded" if excluded else "no_valid_fixed_slot",
                             activity=activity["ActivityTitle"],
                             fixed_slots=sorted(activity["ProcessedTimeSlots"]))

    @classmethod
    def __fillRoutines(
        cls, 
        patient_schedule: List[List[str]], 
        activities: pd.DataFrame, 
        patient_routine: pd.DataFrame, 
        patient_info: Mapping[str, Dict[str, str]],
        week_start: datetime.datetime = None,
        patient_id = None,
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
                    trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.SKIPPED, "routine_excluded",
                                 activity=r["ActivityTitle"], day=day, slot=time)
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
            if day >= len(patient_schedule) or time >= len(patient_schedule[day]):
                trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.DROPPED, "routine_out_of_bounds",
                             activity=routine_activity_title, day=day, slot=time)
                continue

            current_activity = patient_schedule[day][time]

            if not current_activity:
                patient_schedule[day][time] = routine_activity_title
                trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.PLACED, "routine_slot",
                             activity=routine_activity_title, day=day, slot=time)
                continue

            # only fixed recommended activities can be moved, compulsory ones can't
            if current_activity not in activity_map:
                trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.DROPPED, "routine_slot_held_by_higher_priority",
                             activity=routine_activity_title, day=day, slot=time, occupied_by=current_activity)
                continue

            if new_slot := rescheduleActivity(patient_schedule, day, time, activity_map[current_activity]):
                patient_schedule[new_slot[0]][new_slot[1]] = current_activity
                patient_schedule[day][time] = routine_activity_title
                trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.MOVED, "displaced_by_routine",
                             activity=current_activity, day=new_slot[0], slot=new_slot[1], from_day=day, from_slot=time)
                trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.PLACED, "routine_slot",
                             activity=routine_activity_title, day=day, slot=time)
                continue

            trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.DROPPED, "routine_cannot_reschedule_occupant",
                         activity=routine_activity_title, day=day, slot=time, occupied_by=current_activity)

    @classmethod
    def __fillFlexibleActivities(
        cls, 
        patient_schedule: List[List[str]], 
        activities: pd.DataFrame, 
        patient_info: Mapping[str, Dict[str, str]],
        week_start: datetime.datetime = None,
        patient_id = None,
    ):
        """
        Fill in recommended activities that do not have fixedTimeSlots, i.e. fixedTimeSlots is empty
        Assumed to be schedulable at any time. Iterates through schedule and fills in the first available slot.
        """
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

                    num_slots = (a["MinDuration"] // -cls.config["MIN_ACTIVITY_DURATION"]) * -1
                    if time + num_slots > len(day_schedule) or \
                        any(patient_schedule[day][time + i] for i in range(num_slots)):
                        continue

                    for i in range(num_slots):
                        patient_schedule[day][time+i] = a["ActivityTitle"]
                    scheduled_activities.add(a["ActivityID"])
                    trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.PLACED,
                                 "recommended_over_dislike" if a["ActivityID"] in patient_info.get("dispreferences", set())
                                 else "first_free_run",
                                 activity=a["ActivityTitle"], day=day, slot=time)
                    # slot taken, move on
                    break

                if len(scheduled_activities) == len(activities):
                    return

        for _, a in activities.iterrows():
            if a["ActivityID"] not in scheduled_activities:
                excluded = all(checkActivityExcluded(a["ActivityID"], patient_info["exclusions"], d, week_start)
                               for d in range(len(patient_schedule)))
                trace.record(trace.STAGE_RECOMMENDED, patient_id, trace.DROPPED,
                             "excluded" if excluded else "no_free_run",
                             activity=a["ActivityTitle"], min_duration=int(a["MinDuration"]))


class PreferredActivityScheduler(IndividualActivityScheduler):
    @classmethod
    def fillSchedule(cls, schedules: Mapping[str, List[str]]) -> None:
        cls.fillPreferences(schedules)

    @classmethod
    def fillPreferences(cls, schedules: Mapping[str, List[str]], conn: Connection = None, patients: Mapping = None, week_start: datetime.datetime = None):
        patients = patients or cls._get_patient_data(conn=conn)
        week_start = week_start or \
            datetime.datetime.now() - datetime.timedelta(days = datetime.datetime.now().weekday())

        # consolidate activity data
        activities: pd.DataFrame = ActivitiesView.get_data(conn=conn)  # non compulsory individual activities
        avail_activities = activities[["ActivityID", "ActivityTitle", "FixedTimeSlots", "MinDuration", "MaxDuration"]]

        # to be used in _findActivityBySlot, do preprocessing here instead of for every patient slot
        proc_fixedTimeSlots:pd.Series = avail_activities['FixedTimeSlots'].apply(lambda x: {(int(a),int(b)) for a,b in map(lambda y: y.split('-'), x.split(','))} if pd.notna(x) and x.strip() != "" else set())
        avail_activities = avail_activities.assign(ProcessedTimeSlots=proc_fixedTimeSlots)
        # activities = activities.sample(frac=1)\
        #     .reset_index(drop=True)

        strategy = cls.config.get("GAP_FILL_STRATEGY", "greedy")
        if strategy not in ("greedy", "optimal"):
            logger.warning(f"Unknown GAP_FILL_STRATEGY {strategy!r}, using greedy")
            strategy = "greedy"
        pool = [
            PoolActivity(int(r["ActivityID"]), r["ActivityTitle"], int(r["MinDuration"]), frozenset(r["ProcessedTimeSlots"]))
            for _, r in avail_activities.iterrows()
        ] if strategy == "optimal" else []

        for pid, sched in schedules.items():
            try:
                patient = patients.get(pid) or _no_patient_data()

                exclusions: Set[int] = patient["exclusions"]
                preferences: Set[int] = patient["preferences"]
                dispreferences: Set[int] = patient["dispreferences"]

                preference_idx = avail_activities["ActivityID"].isin(preferences)
                non_preference_idx = (~avail_activities["ActivityID"].isin(dispreferences)) & ~preference_idx
                patient_preferred = avail_activities[preference_idx]
                patient_non_preferred = avail_activities[non_preference_idx]
                before = [list(d) for d in sched]

                for day, day_sched in enumerate(sched):
                    # exclusions only cover their own days
                    excluded_today = {
                        aid for aid in exclusions
                        if checkActivityExcluded(aid, exclusions, day, week_start)
                    }
                    preferred_activities = patient_preferred[~patient_preferred["ActivityID"].isin(excluded_today)]
                    non_preferred_activites = patient_non_preferred[~patient_non_preferred["ActivityID"].isin(excluded_today)]

                    if strategy == "optimal":
                        cls._fillDayOptimal(
                            day_sched, day, pid, sched, pool, avail_activities, preferences, dispreferences,
                            exclusions, week_start, preferred_activities, non_preferred_activites,
                        )
                    else:
                        cls._greedyFillDay(day_sched, day, pid, preferred_activities, non_preferred_activites, avail_activities)

                cls._traceLikedNotPlaced(pid, before, sched, avail_activities, preferences, exclusions,
                                         patient.get("not_recommended", set()), week_start)
            except Exception as e:
                logger.exception(f"Preferred activity scheduling failed for patient {pid}, skipping")
                trace.record(trace.STAGE_PREFERRED, pid, trace.ERROR, "stage_exception", error=repr(e))

    @classmethod
    def _traceLikedNotPlaced(cls, pid, before: List[List[str]], after: List[List[str]], avail_activities: pd.DataFrame,
                             preferences: Set[int], exclusions: Mapping, not_recommended: Set[int],
                             week_start: datetime.datetime) -> None:
        """Liked activities that never made it into the week, and why."""
        if trace.current() is None:
            return
        placed = {v for day in after for v in day}
        for _, a in avail_activities[avail_activities["ActivityID"].isin(preferences)].iterrows():
            if a["ActivityTitle"] in placed:
                continue
            aid = a["ActivityID"]
            length = max(1, -(-int(a["MinDuration"]) // cls.config["MIN_ACTIVITY_DURATION"]))
            days = [d for d in range(len(before)) if not checkActivityExcluded(aid, exclusions, d, week_start)]

            def free(d, s):
                return s + length <= len(before[d]) and not any(before[d][s:s + length])

            if aid in not_recommended:
                reason = "liked_but_not_recommended"
            elif not days:
                reason = "liked_but_excluded"
            elif a["ProcessedTimeSlots"]:
                fits = any(d in days and free(d, s) for d, s in a["ProcessedTimeSlots"])
                reason = "liked_but_gaps_used" if fits else "liked_but_fixed_time_taken"
            else:
                fits = any(free(d, s) for d in days for s in range(len(before[d])))
                reason = "liked_but_gaps_used" if fits else "liked_but_no_gap_long_enough"
            trace.record(trace.STAGE_PREFERRED, pid, trace.SKIPPED, reason, activity=a["ActivityTitle"])

    @classmethod
    def _greedyFillDay(cls, day_sched: List[str], day: int, pid, preferred_activities: pd.DataFrame,
                       non_preferred_activites: pd.DataFrame, avail_activities: pd.DataFrame) -> None:
        """Slot by slot, earliest-ending activity that fits, preferred list first."""
        # include what earlier stages put later in the day, not just what we've passed
        curr_day_activities = {v for v in day_sched if v}

        i = 0
        while i < len(day_sched):
            if not day_sched[i]:
                # find the longest stretch of empty slots
                j = i + 1
                while (j < len(day_sched) and not day_sched[j]):
                    j += 1
                j -= 1 # j is incremented by 1 before the last check fails
                if i >= len(day_sched):
                    break

                find_activity = partial(cls.__findActivityBySlot, day=day, slot=i, slot_size=j-i)
                new_activity: str = \
                    find_activity(preferred_activities, curr_day_activities) or \
                    find_activity(non_preferred_activites, curr_day_activities)
                # min slot duration for replacement with Free and Easy
                new_activity_duration: int = avail_activities[avail_activities["ActivityTitle"] == new_activity].iloc[0]["MinDuration"] if new_activity else cls.config["MIN_ACTIVITY_DURATION"]

                num_slots = new_activity_duration // cls.config["MIN_ACTIVITY_DURATION"]

                if not new_activity or j-i+1 < num_slots:
                    trace.record(trace.STAGE_PREFERRED, pid, trace.FREE_AND_EASY,
                                 "no_candidate_fits" if not new_activity else "candidate_too_long",
                                 activity="Free and Easy", day=day, slot=i, free_run=j-i+1,
                                 preferred_pool=len(preferred_activities),
                                 neutral_pool=len(non_preferred_activites),
                                 used_today=sorted(a for a in curr_day_activities if a != "Free and Easy"))
                    new_activity = "Free and Easy"
                    num_slots = cls.config["MIN_ACTIVITY_DURATION"] // cls.config["MIN_ACTIVITY_DURATION"] # =1
                else:
                    trace.record(trace.STAGE_PREFERRED, pid, trace.PLACED,
                                 "preferred" if new_activity in set(preferred_activities["ActivityTitle"]) else "neutral",
                                 activity=new_activity, day=day, slot=i)

                curr_day_activities.add(new_activity)

                for k in range(num_slots):
                    day_sched[i+k] = new_activity

            else:
                # potentially prevent the same activity from being scheduled again in the same day
                curr_day_activities.add(day_sched[i])

            i += 1

    @classmethod
    def _fillDayOptimal(cls, day_sched: List[str], day: int, pid, week_sched: List[List[str]], pool: List[PoolActivity],
                        avail_activities: pd.DataFrame, preferences: Set[int], dispreferences: Set[int],
                        exclusions: Mapping, week_start: datetime.datetime,
                        preferred_activities: pd.DataFrame, non_preferred_activites: pd.DataFrame) -> None:
        """Best fill for today's gaps from gapFill.solve_day, seeded with the greedy result."""
        free = [not v for v in day_sched]
        if not any(free):
            return

        used_today = {v for v in day_sched if v}
        week_counts = Counter(v for d in week_sched for v in d if v and v != "Free and Easy")
        candidates = build_candidates(
            pool, day,
            min_activity_duration=cls.config["MIN_ACTIVITY_DURATION"],
            week_start=week_start,
            exclusions=exclusions,
            liked=set(preferences),
            blocked=set(dispreferences),
            used_titles_today=used_today,
            week_counts=week_counts,
        )
        by_title = {c.title: c for c in candidates}

        # greedy result as the starting point, in a throwaway trace so it doesn't log
        greedy_day = list(day_sched)
        with trace.tracing(trace.ScheduleTrace()):
            cls._greedyFillDay(greedy_day, day, pid, preferred_activities, non_preferred_activites, avail_activities)
        seed = {}
        for i, v in enumerate(greedy_day):
            if free[i] and v in by_title and (i == 0 or greedy_day[i - 1] != v or not free[i - 1]):
                seed[i] = by_title[v]

        result = solve_day(free, candidates, seed=seed)
        if result.exhausted_budget:
            logger.warning(f"Gap fill search budget hit for patient {pid} day {day}; using best found")

        for start, c in sorted(result.assignment.items()):
            for k in range(c.length):
                day_sched[start + k] = c.title
            trace.record(trace.STAGE_PREFERRED, pid, trace.PLACED, "preferred" if c.liked else "neutral",
                         activity=c.title, day=day, slot=start, strategy="optimal")

        rules = PatientRules(likes=set(preferences), dislikes=set(dispreferences), exclusions=dict(exclusions))
        used_after = {v for v in day_sched if v}
        for run_start, run_end in free_runs([not v for v in day_sched]):
            reason = unfillable_reason(run_end - run_start, day, rules, pool, week_start,
                                       cls.config["MIN_ACTIVITY_DURATION"], used_after)
            for k in range(run_start, run_end):
                day_sched[k] = "Free and Easy"
                trace.record(trace.STAGE_PREFERRED, pid, trace.FREE_AND_EASY, reason,
                             activity="Free and Easy", day=day, slot=k, free_run=run_end - run_start,
                             strategy="optimal")

    @classmethod
    def __findActivityBySlot(
        cls, 
        activities: pd.DataFrame, 
        used_activities: Set[str], 
        day: int, 
        slot: int,
        slot_size: int,
    ) -> Optional[str]:
        """ 
        Find the activity that can be scheduled closest to the given slot and day
        Used_activities: activities that have already been scheduled for each patient that day 
        """
        if activities.empty:
            return
        
        # generate a random sample, having frac=1 shuffles rows, reset_index re-indexes rows and drop=True stops old index from being added as new column
        activities = activities.sample(frac=1)\
            .reset_index(drop=True)
        
        out = [-1, 1000, False]
        o = cls.config["OPEN_DAYS"]

        for i, a in activities.iterrows():
            if a["ActivityTitle"] in used_activities:
                continue

            # may change, but technically min duration is 30 mins; for now, 60 minutes.
            minDuration = max(1, a["MinDuration"] // cls.config["MIN_ACTIVITY_DURATION"]) 
            minSlots = minDuration - 1 # slots are 1 hour each

            # has to fit the free run, else the slot ends up Free and Easy
            if minSlots > slot_size:
                continue

            if a["FixedTimeSlots"]:
                # e.g. takes in ["1-2","1-3"], map output: [["1","2"],["1","3"]]
                timeSlots = [t for t in a["ProcessedTimeSlots"] if t[0]<len(o) and t[1]<cls.config["SLOTS_PER_DAY"].get(o[t[0]]) and \
                             t[0]==day and t[1]==slot and t[1]+minSlots<=slot+slot_size]

                if not timeSlots:
                    continue
                else:
                    earliest_end = min(t[1] + minSlots for t in timeSlots)
            else:
                # prioritise activities that have slots. Activities with no slots specified can be scheduled anytime
                if out[2]:
                    continue
                earliest_end = slot + minSlots

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
        curr_week_start = curr_week_start - datetime.timedelta(days = curr_date.weekday())
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
                ).where(
                    patient_table.c["IsDeleted"] == False,
                    patient_table.c["IsActive"] == True,
                )

                res: Result = conn.execute(stmt)
                patientIDs = set(pid for (pid,) in res.all())

            logger.info(f"updating schedules for patients {patientIDs}")

            latest_schedules = cls.getMostUpdatedSchedules(patientIDs, conn, update_date)

            # use the original individual scheduler to update activities
            patient_data = cls._get_patient_data(conn)
            activities = ActivitiesView.get_data(conn)
            activities["EndDate"] = activities["EndDate"].apply(pd.Timestamp)
            # Fill null EndDate with week_end as the current weekend (this is because activities who are indefinite have null EndDate)
            #activities = activities[(activities["EndDate"].isna()) | (activities["EndDate"] > week_end)]
            activities = activities[activities["EndDate"] > week_end]
            activities_title_lookup = {
                row["ActivityTitle"]: row["ActivityID"] for _, row in activities.iterrows()
            }

            def check_excluded(pid, activityTitle):
                activityTitle = activityTitle.strip()
                return activities_title_lookup.get(activityTitle, None) in patient_data[pid]["exclusions"]

            def parse_day_cell(day: str, cell: str) -> List[str]:
                # day columns are JSON now, not the old '--' format
                slots_per_day = cls.config["SLOTS_PER_DAY"].get(day, 0)
                if not cell or not slots_per_day:
                    return []
                day_data = json.loads(cell)
                labels = day_timeslot_labels(
                    day, slots_per_day, cls.config["WORKING_HOURS"], cls.config["MIN_ACTIVITY_DURATION"]
                )
                return [day_data.get(label, "") for label in labels]

            formatted_schedules = {}
            schedule_meta = {}
            for _, row in latest_schedules.iterrows():
                formatted_schedules[row["PatientID"]] = [
                    [i if not check_excluded(row["PatientID"], i.split("|")[0]) else ""
                        for i in parse_day_cell(day, row[day])
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

            # same medication step the main pipeline uses, not the old manual copy
            medicationSchedule_ref = medicationScheduler.fillSchedule(formatted_schedules)

            write_result = ScheduleWriter.write(
                formatted_schedules, medicationSchedule_ref, overwriteExisting=True, conn=conn, schedule_meta=schedule_meta,
            )
            if not write_result:
                logger.error("Schedule updating failed")


"""
This function calculates and returns the number of slots that an activity can be scheduled at or later than the given slot and day.
Returns float("inf") if activity cannot be scheduled at the given slot. 1000 if the activity has no fixed time slots.
"""
def calculate_activity_availabillity(cls: RecommendedRoutineActivityScheduler, day: int, slot: int, processedTimeSlots: Set[tuple]) -> int:
    # no fixed time slots at all -> deprioritize but still eligible, not unschedulable
    if not processedTimeSlots:
        return 1000

    # activity can't be scheduled at this slot
    if (day,slot) not in processedTimeSlots:
        return float("inf")
    
    # do not count time slots that are invalid, i.e. exceed opening days and available time slots
    o = cls.config["OPEN_DAYS"]
    tally = sum([1 for d,s in processedTimeSlots if d<len(o) and slot<cls.config["SLOTS_PER_DAY"].get(o[d]) and (d>day or (d==day and s>=slot))])
    
    return tally
