import logging
from typing import Dict
from pear_schedule.db_utils.views import PatientsOnlyView
from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
from pear_schedule.scheduler.individualScheduling import IndividualActivityScheduler
from pear_schedule.scheduler.medicationScheduling import medicationScheduler
from pear_schedule.scheduler.routineScheduling import RoutineActivityScheduler

logger = logging.getLogger(__name__)


def build_schedules(config, patientSchedules: Dict) -> Dict:
    patientDF = PatientsOnlyView.get_data()

    for id in patientDF["PatientID"]:
        patientSchedules[id] = [["" for _ in range(config["HOURS"])] for _ in range(config["DAYS"])]


    # Schedule compulsory activities
    CompulsoryActivityScheduler.fillSchedule(patientSchedules)

    # Schedule individual recommended activities
    IndividualActivityScheduler.fillRecommendations(patientSchedules)

    # Schedule routine activities
    RoutineActivityScheduler.fillSchedule(patientSchedules)

    # Schedule group activities
    groupSchedule = GroupActivityScheduler.fillSchedule(patientSchedules)
    for patientID, scheduleArr in groupSchedule.items():
        for i, activity in enumerate(scheduleArr):
            if activity == "-": # routine activity alr scheduled
                continue
            day,hour = config["GROUP_TIMESLOT_MAPPING"][i]
            patientSchedules[patientID][day][hour] = activity

    # Schedule individual preferred activities
    IndividualActivityScheduler.fillPreferences(patientSchedules)
    
    # Insert the medication schedule into scheduler
    medicationScheduler.fillSchedule(patientSchedules)
    
    # To print the schedule
    for p, slots in patientSchedules.items():
            logger.info(f"FOR PATIENT {p}")
            
            for day, activities in enumerate(slots):
                if day == 0:
                    logger.info(f"\t Monday: ")
                elif day == 1:
                    logger.info(f"\t Tuesday: ")
                elif day == 2:
                    logger.info(f"\t Wednesday: ")
                elif day == 3:
                    logger.info(f"\t Thursday: ")
                elif day == 4:
                    logger.info(f"\t Friday: ")
                
                for index, hour in enumerate(activities):
                    logger.info(f"\t\t {index}: {hour}")
            
            logger.info("==============================================")

    return patientSchedules