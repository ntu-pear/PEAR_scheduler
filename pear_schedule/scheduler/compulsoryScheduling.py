from typing import List, Mapping
from pear_schedule.db_views.views import CompulsoryActivitiesOnlyView
from pear_schedule.scheduler.baseScheduler import BaseScheduler


class CompulsoryActivityScheduler(BaseScheduler):
    @classmethod
    def fill_schedule(patientSchedules: Mapping[str, List[str]]):
        compulsoryActivitiesDF = CompulsoryActivitiesOnlyView.get_data()
        
        for activityTitle in compulsoryActivitiesDF["ActivityTitle"]:
            fixedSlotString = compulsoryActivitiesDF.query(f"ActivityTitle == '{activityTitle}'").iloc[0]['FixedTimeSlots']

            fixedSlotArr = fixedSlotString.split(",")
            for slot in fixedSlotArr:
                day = int(slot.split("-")[0])
                hour = int(slot.split("-")[1])

                for pid in patientSchedules.keys():
                    patientSchedules[pid][day][hour] = activityTitle
