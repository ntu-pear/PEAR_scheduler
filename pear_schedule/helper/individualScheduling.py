from functools import partialmethod
import logging
from typing import Any, List, Mapping, Optional

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
        activities = activities.sample(frac=1)\
            .reset_index(drop=True)

        for pid, sched in schedules.items():
            if pid not in patients:
                logger.error(f"unknown patientID {pid} found in schedules")
            patient = patients[pid]
            exclusions = patient["exclusions"]
            preferences = patient["preferences"]

            avail_activities = activities[~activities["ActivityID"].isin(exclusions)]
            avail_activities = avail_activities[["ActivityID", "fixedTimeSlots", "minDuration", "maxDuration"]]

            preference_idx = avail_activities["ActivityId"].isin(preferences)
            preferred_activities = avail_activities[preference_idx]
            non_preferred_activites = avail_activities[~preference_idx]

            for day, day_sched in enumerate(sched):
                curr_day_activities = set()

                i = 0
                while i < len(day_sched):
                    slot = day_sched[i]
                    i += 1

                    if slot:
                        continue

                    slot_size = 1
                    while (not day_sched[i]):
                        i += 1
                        slot_size += 1

                    find_activity = partialmethod(cls.__find_activity, day=day, slot=slot, slot_size=slot_size)
                    new_activity = \
                        find_activity(preferred_activities, curr_day_activities) or \
                        find_activity(non_preferred_activites, curr_day_activities)

                    if not new_activity:
                        continue

                    curr_day_activities.add(new_activity)
                    day_sched[i] = new_activity

        return schedules

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
        
        out = [0, 1000]

        for i, a in activities.iterrows():
            if a["ActivityID"] in used_activities:
                continue

            minDuration = a["minDuration"]

            if a["fixedTimeSlots"]:
                timeSlots = map(lambda x: x.split("-"), a["fixedTimeSlots"].split(","))
                timeSlots = [t for t in timeSlots if t[0] == day and t[1] >= slot and t[1] + minDuration < slot + slot_size]

                if not timeSlots:
                    continue
                else:
                    earliest_end = min(t[1] + minDuration for t in timeSlots)
            else:
                if activities.iloc[out]["fixedTimeSlots"]:
                    continue
                earliest_end = slot + minDuration

            if earliest_end < out[1]:
                out[0] = i
                out[1] = earliest_end

        return activities.iloc[out[0]]["ActivityID"]
