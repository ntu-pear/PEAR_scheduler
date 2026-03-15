import logging
import datetime
import pandas as pd
from typing import List, Mapping, Dict
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.db_utils.views import MedicationView, CaregiverAllocatedView, ExistingScheduleView

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
            end_day_counter = len(cls.config["OPEN_DAYS"])-1
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
                end_day_counter = (len(cls.config["OPEN_DAYS"]) - 1) - (end_of_week - endDateTime).days
            # print(f"Medication ends on {end_day_counter}")

            
            # ======== Inserting medication into the scheduler ========
            slots = administerTime.split(",")
            allocation_row: pd.DataFrame = allocationDF[allocationDF['patientId'] == pid]
            assigned_caregiver: str = (allocation_row.iloc[0]['caregiverId'].strip() or allocation_row.iloc[0]['tempCaregiverId'] or allocation_row.iloc[0]['supervisorId']) if not allocation_row.empty \
                else "UNASSIGNED"
            
            for slot in slots:
                # full_hour = cls.config["DAY_TIMESLOTS"][hour]
                
                for day in range(start_day_counter, end_day_counter+1):
                    # full_day = cls.config["DAY_OF_WEEK_ORDER"][day]
                    # Record days of the week to administer medication
                    i_day: datetime.date = start_of_week.date() + datetime.timedelta(days=day)
                    
                    day_of_week = cls.config["DAY_OF_WEEK_ORDER"][day]
                    hour = getTimeSlot(cls, day_of_week, slot)
                    # end_day_counter is already < len(config["OPEN_DAYS"]); only schedule on days where possible
                    if hour <= -1 or hour >= cls.config["SLOTS_PER_DAY"].get(day_of_week):
                        continue

                    medicationSchedules.setdefault(pid, []).append(
                        {
                            "MedicationID": row['MedicationID'],
                            "day": day,
                            # "full_day": full_day,
                            "hour": hour,
                            # "full_hour": full_hour,
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
    
    def reformatMedicationScheduleData(self, cls) -> Mapping[int, Dict[datetime.date, List[Dict]]]:
        # reformat into pid -> Day -> ...
        reformatted_data = {}
        for pid, meds in self.medicationSchedules.items():
          reformatted_data[pid] = {}
          for med in meds:
            # schema: MedicationID, ScheduleID, AdministerTime (separate), AdministerDate, AssignedTo, Status
            # datetime cannot be used as a key in JSON, have to convert to string. Standardise format to YYYY-MM-DD
            reformatted_data[pid].setdefault(med["date"].strftime(cls.config["STD_DATE_FORMAT"]), []).append({
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
    
    """
    This function is an alternative, meant to be called by the /MedicationSchedule/get/ endpoint to retrieve the medication schedules
    only for the day for convenience (without having to call /generate or /regenerate to get the latest schedules)
    """
    @classmethod
    def generateTodayMedSchedule(cls) -> Mapping[int, List[Dict]]:
        # startDateTime to endDateTime range contains today
        medicationDF = MedicationView.get_data(curDate=True)
        allocationDF = CaregiverAllocatedView.get_data()
        today = datetime.datetime.now()

        # note that there may be multiple medications for the same patient
        medicationSchedules = {}
        for row in medicationDF.itertuples():
            pid = row.PatientID
            mid = row.MedicationID
            sid = None
            administerTimes = row.AdministerTime

            # if there is already a schedule generated for the week, use that schedule id
            existingSchedule = ExistingScheduleView.get_data(patient_id=pid, start_dateTime=today)
            if not existingSchedule.empty:
                sid = existingSchedule.iloc[0]['ScheduleID']

            allocation_row: pd.DataFrame = allocationDF[allocationDF['patientId'] == pid]
            assigned_caregiver: str = (allocation_row.iloc[0]['caregiverId'].strip() or allocation_row.iloc[0]['tempCaregiverId'] or allocation_row.iloc[0]['supervisorId']) if not allocation_row.empty \
                else "UNASSIGNED"
            administerTimes: list = administerTimes.split(",")
            for time in administerTimes:
                qualified_day = today.strftime("%A")
                if qualified_day not in cls.config["OPEN_DAYS"]:
                    continue
                slot = getTimeSlot(cls, qualified_day, time)
                if slot <= -1 or slot >= cls.config["SLOTS_PER_DAY"].get(qualified_day):
                    continue
                medicationSchedules.setdefault(pid, []).append({
                    "MedicationID": mid,
                    "AdministerTime": time,
                    "AdministerDate": today.strftime(cls.config["STD_DATE_FORMAT"]),
                    "AssignedTo": assigned_caregiver,
                    "ScheduleID": sid
                })
            
        return medicationSchedules


def getTimeSlot(cls, day, time):
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
    timeDiff_fromOpening: datetime.timedelta = parsed_time-datetime.datetime.strptime(cls.config["WORKING_HOURS"].get(day.lower()).get("open"), "%H:%M")
    numSlotsFromOpening: int = (timeDiff_fromOpening // -datetime.timedelta(minutes=cls.config["MIN_ACTIVITY_DURATION"]-1)) * -1
    return 0 if timeDiff_fromOpening == datetime.timedelta() else numSlotsFromOpening - 1