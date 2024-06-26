from typing import List, Mapping
from pear_schedule.db_utils.views import CompulsoryActivitiesOnlyView
from pear_schedule.scheduler.baseScheduler import BaseScheduler

class CompulsoryActivityScheduler(BaseScheduler):
    @classmethod
    def fillSchedule(cls, patientSchedules: Mapping[str, List[str]]):
        compulsoryActivitiesDF = CompulsoryActivitiesOnlyView.get_data()
        
        # Compulsory Activity 
        for activityTitle in compulsoryActivitiesDF["ActivityTitle"]:
            fixedSlotString = compulsoryActivitiesDF.query(f"ActivityTitle == '{activityTitle}'").iloc[0]['FixedTimeSlots']

            fixedSlotArr = fixedSlotString.split(",")
            for slot in fixedSlotArr:
                day = int(slot.split("-")[0])
                hour = int(slot.split("-")[1])

                for pid in patientSchedules.keys():
                    patientSchedules[pid][day][hour] = activityTitle 

