import logging
import datetime
import pandas as pd
from typing import List, Mapping, Dict
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.db_utils.views import MedicationView, CaregiverAllocatedView

logger = logging.getLogger(__name__)

class medicationScheduleData:
    def __init__(self, cls):
        self.medicationSchedules: Mapping[int, List[Dict]] = self.__getMedicationSchedulingData(cls)
    
    def __getMedicationSchedulingData(self, cls):
        medicationDF = MedicationView.get_data()
        allocationDF = CaregiverAllocatedView.get_data()

        medicationSchedules: Mapping[int, List[Dict]] = {}
        
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
            start_of_week = today - datetime.timedelta(days=today.weekday())  # Monday -> 00:00:00
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
            allocation_row: pd.DataFrame = allocationDF[allocationDF['patientId'] == pid]
            assigned_caregiver: str = allocation_row.at[0, 'caregiverId'].strip() | allocation_row.at[0, 'tempCaregiverId']
            
            for slot in slots:
                hour = getTimeSlot(cls, slot)
                
                if hour == -1 or hour >= cls.config["HOURS"]: # Invalid time-slot
                    continue
                full_hour = cls.config["DAY_TIMESLOTS"][hour]
                
                for day in range(start_day_counter, end_day_counter+1):
                    full_day = cls.config["DAY_OF_WEEK_ORDER"][day]
                    # Record days of the week to administer medication
                    i_day: datetime.date = start_of_week.date() + datetime.timedelta(days=day)
                    medicationSchedules.setdefault(pid, []).append(
                        {
                            "MedicationID": row['MedicationID'],
                            "day": day,
                            "full_day": full_day,
                            "hour": hour,
                            "full_hour": full_hour,
                            "date": i_day,
                            "administerTime": slot,
                            "prescription": row['PrescriptionName'],
                            "dosage": row['Dosage'],
                            "instruction": instruction,
                            "assignedTo": assigned_caregiver,
                            "status": 0 # 0: Not taken, 1: Taken
                        }
                    )
        
        return medicationSchedules
    
    def reformatMedicationScheduleData(self) -> Mapping[int, Dict[datetime.date, List[Dict]]]:
        # reformat into pid -> Day -> ...
        reformatted_data = {}
        for pid, meds in self.medicationSchedules.items():
          reformatted_data[pid] = {}
          for med in meds:
             # schema: MedicationID, ScheduleID, AdministerTime (separate), AdministerDate, AssignedTo, Status
            reformatted_data[pid].setdefault(med["date"], []).append({
                "MedicationID": med["MedicationID"],
                "AdministerTime": med["administerTime"],
                "AssignedTo": med["assignedTo"],
                "Status": med["status"],
            })
        return reformatted_data

class medicationScheduler(BaseScheduler):
    """
    The fillSchedule() function fills in medication information into the corresponding time-slots of the patient schedule,
    based on medicationScheduleData.medicationSchedules.
    """
    @classmethod
    def fillSchedule(cls, patientSchedules: Mapping[str, List[str]]) -> medicationScheduleData:
        # create medication schedule instance
        medicationSchedule_ref = medicationScheduleData(cls)
        medicationSchedules: Mapping[int, List[Dict]] = medicationSchedule_ref.medicationSchedules
        for pid, med in medicationSchedules.items():
            for med_info in med:
              # unpack
              day, hour, slot, prescription, dosage, instruction = (
                  med_info['day'],
                  med_info['hour'],
                  med_info['administerTime'],
                  med_info['prescription'],
                  med_info['dosage'],
                  med_info['instruction']
              )

              # fill schedule
              s = "{begin}@{slot}: {prescription}({dosage}){end}"
              s = s.format(
                begin = " | Give Medication" if "Give Medication" not in patientSchedules[pid][day][hour] else ", Give Medication",
                slot = slot,
                prescription = prescription,
                dosage = dosage,
                end = "" if instruction is None or not instruction.strip() or instruction.lower() in ["nil", "-"] else f"**{instruction}"
              )
                            
              patientSchedules[pid][day][hour] += s
        
        return medicationSchedule_ref


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
    if (not time.strip()): return -1
    parsed_time = datetime.datetime.strptime(time, "%H%M")
    timeDiff_fromOpening: datetime.timedelta = parsed_time-datetime.datetime.strptime(cls.config["OPENING_HOUR"], "%I%p")
    numSlotsFromOpening: int = (timeDiff_fromOpening // -datetime.timedelta(minutes=cls.config["MIN_ACTIVITY_DURATION"])) * -1
    return numSlotsFromOpening - 1