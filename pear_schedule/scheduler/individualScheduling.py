from functools import partial
import logging
from typing import List, Mapping, Optional

import pandas as pd

from pear_schedule.db_views.views import ActivitiesView, PatientsView
from pear_schedule.scheduler.baseScheduler import BaseScheduler


logger = logging.getLogger(__name__)


class IndividualActivityScheduler(BaseScheduler):
    @classmethod
    def fillSchedule(cls, schedules: Mapping[str, List[str]]):
        patients: Mapping[str, Mapping[str, set[str]]] = {}

        # consolidate patient data
        for _, p in PatientsView.get_data().iterrows():  # TODO: split patientsview into activity level view instead
            pid = p["PatientID"]
            if pid not in patients:
                patients[pid] = {
                    "preferences":set(), "exclusions": set()  # recommendations handled in compulsory scheduling
                }

            # patients[pid].add(p["RecommendedActivityID"])
            patients[pid]["exclusions"].add(p["ExcludedActivityID"])
            patients[pid]["preferences"].add(p["PreferredActivityID"])

        # consolidate activity data
        activities: pd.DataFrame = ActivitiesView.get_data()  # non compulsory individual activities
        # activities = activities.sample(frac=1)\
        #     .reset_index(drop=True)

        for pid, sched in schedules.items():
            if pid not in patients:
                logger.error(f"unknown patientID {pid} found in schedules")
                continue
            patient = patients[pid]

            exclusions = patient["exclusions"]
            preferences = patient["preferences"]

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

                        find_activity = partial(cls.__find_activity, day=day, slot=i, slot_size=j-i)
                        new_activity = \
                            find_activity(preferred_activities, curr_day_activities) or \
                            find_activity(non_preferred_activites, curr_day_activities)

                        if not new_activity:
                            continue
                        curr_day_activities.add(new_activity)
                        day_sched[i] = new_activity
                    i += 1



    @classmethod
    def __find_activity(
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
