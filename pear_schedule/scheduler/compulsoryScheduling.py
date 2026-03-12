from typing import List, Mapping
from pear_schedule.db_utils.views import CompulsoryActivitiesOnlyView
from pear_schedule.scheduler.baseScheduler import BaseScheduler
import logging

logger = logging.getLogger(__name__)

class CompulsoryActivityScheduler(BaseScheduler):
    @classmethod
    def fillSchedule(cls, patientSchedules: Mapping[str, List[str]]):
        compulsoryActivitiesDF = CompulsoryActivitiesOnlyView.get_data()
        # Compulsory Activity 
        for _, row in compulsoryActivitiesDF.iterrows():
        
            fixedSlotArr = row["FixedTimeSlots"].split(",")
            for slot in fixedSlotArr:
                
                # TODO: placeholder - For activities whose duration is more than 1 slot, assume that the slot in FixedTimeSlots denotes the starting slot
                day = int(slot.split("-")[0])
                hour = int(slot.split("-")[1])
                duration_slots = -(row["MinDuration"] // -cls.config["MIN_ACTIVITY_DURATION"]) - 1

                for pid in patientSchedules.keys():
                    try:
                      patientSchedules[pid][day][hour] = row["ActivityTitle"]
                    except IndexError:
                        logger.error(f"A fixed time slot has been provided which exceeds the opening hours of the centre")
                        return
                    for d in range(1, duration_slots + 1):
                        patientSchedules[pid][day][hour + d] = row["ActivityTitle"] # ? trust activity handling will not go past closing hour


