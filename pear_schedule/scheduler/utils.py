import datetime
import logging
from typing import Dict, List, Optional, Tuple, Mapping
from pear_schedule.db_utils.views import PatientsOnlyView, GroupActivitiesOnlyView

logger = logging.getLogger(__name__)


def build_schedules(config, patientSchedules: Dict) -> Dict:
    # local imports since the schedulers each likely import this file
    from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
    from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
    from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler, RecommendedRoutineActivityScheduler
    from pear_schedule.scheduler.medicationScheduling import medicationScheduler, medicationScheduleData
    from pear_schedule.scheduler.adhocScheduling import AdhocScheduler
    patientDF = PatientsOnlyView.get_data()
    groupActivityDF = GroupActivitiesOnlyView.get_data()

    for id in patientDF["PatientID"]:
        patientSchedules[id] = [["" for _ in range(config["SLOTS_PER_DAY"].get(day))] for day in config["OPEN_DAYS"]]


    # Schedule compulsory activities
    CompulsoryActivityScheduler.fillSchedule(patientSchedules)

    # Schedule individual recommended and routine activities
    RecommendedRoutineActivityScheduler.fillSchedule(patientSchedules)

    # Schedule group activities
    groupSchedule: Mapping[int, list[list[str]]] = GroupActivityScheduler.fillSchedule(patientSchedules)
    for patientID, scheduleArr in groupSchedule.items():
        for i, activity in enumerate(scheduleArr):
            if activity[0] == "-" or not activity[0]: # routine activity alr scheduled
                continue
            day,hour = config["GROUP_TIMESLOT_MAPPING"][i]
            logger.info(f"Scheduling group activity {activity[0]} for patient {patientID} on day {day} at hour {hour}")
            activityDuration = groupActivityDF.query(f"ActivityTitle == '{activity[0]}'").iloc[0]["MinDuration"]
            for j in range(activityDuration // config["MIN_ACTIVITY_DURATION"]):
                patientSchedules[patientID][day][hour+j] = activity[0]

    # Schedule individual preferred activities
    PreferredActivityScheduler.fillSchedule(patientSchedules)
    AdhocScheduler.fillSchedule(patientSchedules)
    # Insert the medication schedule into scheduler
    medicationSchedule_ref: medicationScheduleData = medicationScheduler.fillSchedule(patientSchedules)
    
    # To print the schedule
    for p, slots in patientSchedules.items():
            logger.info(f"FOR PATIENT {p}")
            
            for day, activities in enumerate(slots):
                logger.info(f"\t {config['OPEN_DAYS'][day]}: ")
                
                for index, hour in enumerate(activities):
                    logger.info(f"\t\t {index}: {hour}")
            
            logger.info("==============================================")

    return medicationSchedule_ref


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