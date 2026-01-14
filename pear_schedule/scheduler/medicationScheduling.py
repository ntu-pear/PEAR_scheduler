import logging
import datetime
from typing import List, Mapping
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.db_utils.views import MedicationView

logger = logging.getLogger(__name__)

class medicationScheduler(BaseScheduler):
    @classmethod
    def fillSchedule(cls, patientSchedules: Mapping[str, List[str]]):
        medicationDF = MedicationView.get_data()
        
        for index, row, in medicationDF.iterrows():
            
            # ======== Variables ========
            start_day_counter = 0
            end_day_counter = cls.config["DAYS"] - 1
            administerTime = row['AdministerTime']
            pid = row["PatientID"]
            startDateTime = row["StartDateTime"]
            endDateTime = row['EndDateTime']
            instruction = row['Instruction']
            # print(f"PatientID: {pid} | Medication: {row['PrescriptionName']}")
            
            # ======== Check what is the start and end date of the medication in the given week ========
            today = datetime.datetime.now()
            start_of_week = today - datetime.timedelta(days=today.weekday(), hours=0, minutes=0, seconds=0, microseconds=0)  # Monday -> 00:00:00
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_week = start_of_week + datetime.timedelta(days=4, hours=23, minutes=59, seconds=59, microseconds=0)  # Sunday -> 23:59:59
            
            if startDateTime <= start_of_week: # Medication starts either before or start of this week
                pass
            elif startDateTime > start_of_week and startDateTime <= end_of_week: # Medication starts sometime this week
                start_day_counter = (startDateTime - start_of_week).days
            else: # Medication does not start this week
                continue
            # print(f"Medication starts on {start_day_counter}")
            
            if endDateTime <= end_of_week: # Medication will end sometime during the week
                end_day_counter = (cls.config["DAYS"]-1) - (end_of_week - endDateTime).days
            # print(f"Medication ends on {end_day_counter}")
            
            
            # ======== Inserting medication into the scheduler ========
            slots = administerTime.split(",")
            
            for slot in slots:
                hour = getTimeSlot(cls, int(slot))
                full_hour = cls.config["DAY_TIMESLOTS"][hour]
                if hour == -1: # Invalid time-slot
                    continue
                
                for day in range(start_day_counter, end_day_counter+1):
                    full_day = cls.config["DAY_OF_WEEK_ORDER"][day]
                    s = "{begin}@{slot}: {prescription}({dosage}){end}"
                    s = s.format(
                        begin = " | Give Medication" if "Give Medication" not in patientSchedules[pid][day][hour] else ", Give Medication",
                        slot = slot,
                        prescription = row['PrescriptionName'],
                        dosage = row['Dosage'],
                        end = "" if instruction is None or not instruction.strip() or instruction.lower() in ["nil", "-"] else f"**{instruction}"
                    )
                    
                    patientSchedules[pid][day][hour] += s


def getTimeSlot(cls, time):
    """
    getTimeSlot() returns the index of the time slot based on the given time.
    
    Args:
        cls: class in order to access config variables
        time: administration time of medicine
    
    Returns:
        Index of time slot, -1 if invalid time-slot, >len(cls.config["DAY_TIMESLOTS"]) if beyond closing hours, both would be out of bounds on access
        E.g. 1730 administration time returns 8, 0830 returns -1
    """
    parsed_time = datetime.datetime.strptime(str(time), "%H%M")
    timeDiff_fromOpening: datetime.timedelta = parsed_time-datetime.datetime.strptime(cls.config["OPENING_HOUR"], "%I%p")
    numSlotsFromOpening: int = (timeDiff_fromOpening // -datetime.timedelta(minutes=cls.config["MIN_ACTIVITY_DURATION"])) * -1
    return numSlotsFromOpening - 1

    # if (900 <= time < 1000):
    #     return 0
    # elif (1000 <= time < 1100):
    #     return 1
    # elif (1100 <= time < 1200):
    #     return 2
    # elif (1200 <= time < 1300):
    #     return 3
    # elif (1300 <= time < 1400):
    #     return 4
    # elif (1400 <= time < 1500):
    #     return 5
    # elif (1500 <= time < 1600):
    #     return 6
    # elif (1600 <= time < 1700):
    #     return 7
    # else:
    #     print("Invalid time-slot")
    #     return -1