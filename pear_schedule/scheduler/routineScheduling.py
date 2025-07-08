
from typing import List, Mapping
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.db_utils.views import PatientsOnlyView, ValidRoutineActivitiesView


class RoutineActivityScheduler(BaseScheduler):
    @classmethod
    def fillSchedule(cls, patientSchedules: Mapping[str, List[str]]):
        routineActivitiesDF = ValidRoutineActivitiesView.get_data()
        for _, row in routineActivitiesDF.iterrows():
            patientID = row["PatientID"]
            activityTitle = row["ActivityTitle"]
            fixedTimeArr = cls.getFixedTimeArr(row["FixedTimeSlots"])

            for day, hour in fixedTimeArr:
                if patientSchedules[patientID][day][hour]:
                    continue
                patientSchedules[patientID][day][hour] = activityTitle

            
        print(patientSchedules)

    @classmethod
    def getFixedTimeArr(cls, fixedTimeSlots):
        arr = []
        fixedTimeArr = fixedTimeSlots.split(",")
        for str in fixedTimeArr:
            temp = str.split("-")
            arr.append((int(temp[0]), int(temp[1])))
        

        return arr