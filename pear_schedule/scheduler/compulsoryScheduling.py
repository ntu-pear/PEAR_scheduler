from typing import List, Mapping
from pear_schedule.db_utils.views import CompulsoryActivitiesOnlyView
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.scheduler import trace
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
                    try:
                        # skip over time slots that are out of bounds
                        if day >= len(patientSchedules[pid]) or hour + num_slots > len(patientSchedules[pid][day]):
                            trace.record(trace.STAGE_COMPULSORY, pid, trace.DROPPED, "out_of_bounds",
                                         activity=row["ActivityTitle"], day=day, slot=hour, num_slots=num_slots)
                            continue

                        # handling for accidental conflicting compulsory activities:
                        # only write if every slot this activity would occupy is currently free
                        targetSlots = patientSchedules[pid][day][hour:hour + num_slots]
                        if all(not slot for slot in targetSlots):
                            for d in range(num_slots):
                                patientSchedules[pid][day][hour + d] = row["ActivityTitle"]
                            trace.record(trace.STAGE_COMPULSORY, pid, trace.PLACED, "fixed_slot",
                                         activity=row["ActivityTitle"], day=day, slot=hour)
                        else:
                            trace.record(trace.STAGE_COMPULSORY, pid, trace.DROPPED, "slot_occupied",
                                         activity=row["ActivityTitle"], day=day, slot=hour,
                                         occupied_by=[a for a in targetSlots if a])
                            logger.warning(
                                f"Skipping compulsory activity {row['ActivityTitle']!r} for patient {pid} "
                                f"on day {day} at hour {hour}: target slot(s) already occupied"
                            )
                    except Exception as e:
                        logger.exception(f"Compulsory scheduling failed for patient {pid}, skipping")
                        trace.record(trace.STAGE_COMPULSORY, pid, trace.ERROR, "stage_exception", error=repr(e))