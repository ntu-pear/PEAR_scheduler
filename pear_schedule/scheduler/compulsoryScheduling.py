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
                num_slots = row["MinDuration"] // cls.config["MIN_ACTIVITY_DURATION"]

                for pid in patientSchedules.keys():
                    # skip over time slots that are out of bounds
                    if day >= len(patientSchedules[pid]) or hour + num_slots > len(patientSchedules[pid][day]):
                        continue

                    # handling for accidental conflicting compulsory activities:
                    # only write if every slot this activity would occupy is currently free
                    targetSlots = patientSchedules[pid][day][hour:hour + num_slots]
                    if all(not slot for slot in targetSlots):
                        for d in range(num_slots):
                            patientSchedules[pid][day][hour + d] = row["ActivityTitle"]
                    else:
                        logger.warning(
                            f"Skipping compulsory activity {row['ActivityTitle']!r} for patient {pid} "
                            f"on day {day} at hour {hour}: target slot(s) already occupied"
                        )