import datetime
import logging
from typing import Dict, List, Optional, Tuple
from pear_schedule.db_utils.views import PatientsOnlyView

logger = logging.getLogger(__name__)


def build_schedules(config, patientSchedules: Dict) -> Dict:
    # local imports since the schedulers each likely import this file
    from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
    from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
    from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler, RecommendedRoutineActivityScheduler
    from pear_schedule.scheduler.medicationScheduling import medicationScheduler
    patientDF = PatientsOnlyView.get_data()

    for id in patientDF["PatientID"]:
        patientSchedules[id] = [["" for _ in range(config["HOURS"])] for _ in range(config["DAYS"])]


    # Schedule compulsory activities
    CompulsoryActivityScheduler.fillSchedule(patientSchedules)

    # Schedule individual recommended and routine activities
    RecommendedRoutineActivityScheduler.fillSchedule(patientSchedules)

    # Schedule group activities
    groupSchedule = GroupActivityScheduler.fillSchedule(patientSchedules)
    for patientID, scheduleArr in groupSchedule.items():
        for i, activity in enumerate(scheduleArr):
            if activity == "-": # routine activity alr scheduled
                continue
            day,hour = config["GROUP_TIMESLOT_MAPPING"][i]
            patientSchedules[patientID][day][hour] = activity

    # Schedule individual preferred activities
    PreferredActivityScheduler.fillSchedule(patientSchedules)
    
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


def parseFixedTimeArr(fixedTimeSlots: str) -> List[Tuple[int, int]]:
    arr = []
    fixedTimeArr = fixedTimeSlots.split(",")
    for str in fixedTimeArr:
        temp = str.split("-")
        arr.append((int(temp[0]), int(temp[1])))

    return arr


def checkActivityExcluded(
        activityID: int, 
        patientExclusions: Dict[int, datetime.datetime], 
        day_slot: int, 
        week_start: datetime.datetime
    ) -> bool:
        if activityID not in patientExclusions:
            return False

        exclusion_end = patientExclusions[activityID]
        slot_datetime = week_start + datetime.timedelta(days=day_slot)

        # if activity exclusion has not yet ended then ignore
        # include current day since it can be unsafe to perform activities on the
        # day exclusion ends (eg remove leg cast then walk same day)
        return exclusion_end is None or exclusion_end >= slot_datetime


def rescheduleActivity(patient_schedule: List, day: int, time: int, potential_slots: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
    for slot in potential_slots:
        slot_day, slot_time = slot
        if patient_schedule[slot_day][slot_time]:
            continue
        return slot

    return None