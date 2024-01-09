import datetime
from typing import List, Mapping
from pear_schedule.db_views.views import CompulsoryActivitiesOnlyView
from pear_schedule.scheduler.baseScheduler import BaseScheduler
from pear_schedule.db_views.views import PrescriptionView
from config import MEDICATION_TIMESLOT

class CompulsoryActivityScheduler(BaseScheduler):
    @classmethod
    def fillSchedule(cls, patientSchedules: Mapping[str, List[str]]):
        compulsoryActivitiesDF = CompulsoryActivitiesOnlyView.get_data()
        prescriptionDF = PrescriptionView.get_data()
        
        print("Printing presctiptionDF: ", prescriptionDF)
        
        patientMedication = {} # patient id: ["", ""]
        # Medication Schedule 
        for index, row, in prescriptionDF.iterrows():
            
            days_to_prescript = 5
            frequencyPerDay = row['FrequencyPerDay']
            pid = row["PatientID"]
            endDate = row['EndDate']
            dosage = row['Dosage']
            medicationName = row["Value"]
            
            today = datetime.datetime.now()
            start_of_week = today - datetime.timedelta(days=today.weekday())  # Monday
            end_of_week = start_of_week + datetime.timedelta(days=4)  # Friday
            
            if endDate < end_of_week: # Prescription will end sometime during the week
                days_to_prescript = (end_of_week - endDate).days
                print(f"Prescription ends in {days_to_prescript} days starting from Monday")
            elif endDate == end_of_week: # Prescription will end exactly on the Friday 
                print(f"Prescription will end exactly on a Friday")
                days_to_prescript = 4
            else:
                print("Prescription will not end this week")
                
            if frequencyPerDay == 1 or frequencyPerDay == 2:
                for day in range(days_to_prescript):
                    second_slot = MEDICATION_TIMESLOT[1]
                    
                    if patientSchedules[pid][day][second_slot] == "":
                        patientSchedules[pid][day][second_slot] = "Give Medication: " + medicationName + " (" + dosage + ")"
                    else:
                        patientSchedules[pid][day][second_slot] += ", " + medicationName + " (" + dosage + ")"
            elif frequencyPerDay == 3 or frequencyPerDay == 4:
                for day in range(days_to_prescript):
                    first_slot = MEDICATION_TIMESLOT[0]
                    second_slot = MEDICATION_TIMESLOT[1]
                    
                    if patientSchedules[pid][day][first_slot] == "" and patientSchedules[pid][day][second_slot] == "":
                        patientSchedules[pid][day][first_slot] = "Give Medication: " + medicationName + " (" + dosage + ")"
                        patientSchedules[pid][day][second_slot] = "Give Medication: " + medicationName + " (" + dosage + ")"
                    else:
                        patientSchedules[pid][day][first_slot] += ", " + medicationName + " (" + dosage + ")"
                        patientSchedules[pid][day][second_slot] += ", " + medicationName + " (" + dosage + ")"
        
        # Compulsory Activity 
        for activityTitle in compulsoryActivitiesDF["ActivityTitle"]:
            fixedSlotString = compulsoryActivitiesDF.query(f"ActivityTitle == '{activityTitle}'").iloc[0]['FixedTimeSlots']

            fixedSlotArr = fixedSlotString.split(",")
            for slot in fixedSlotArr:
                day = int(slot.split("-")[0])
                hour = int(slot.split("-")[1])

                for pid in patientSchedules.keys():
                    patientSchedules[pid][day][hour] = activityTitle
        
        print("CHECKING ============================================")    
        for p, slots in patientSchedules.items():
            print(f"{p} Schedule: {slots}")
        print("CHECKING ============================================")    

