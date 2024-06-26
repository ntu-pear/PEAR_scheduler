from collections import defaultdict
import copy
from typing import List
from colorama import Fore
from fastapi.encoders import jsonable_encoder
from dateutil.parser import parse
import datetime
from pear_schedule.db_utils.views import WeeklyScheduleView, CentreActivityPreferenceView, CentreActivityRecommendationView, ActivitiesExcludedView, RoutineView, MedicationTesterView, ActivityAndCentreActivityView
import pandas as pd
import re

from pydantic import BaseModel, field_validator, model_validator

class AdHocRequest(BaseModel):
    OldActivityID: int
    NewActivityID: int
    PatientID: int
    StartDate: str
    EndDate: str

    @field_validator('StartDate', 'EndDate')
    @classmethod
    def isDate(cls, string, fuzzy=False):
        """
        Return whether the string can be interpreted as a date.

        :param string: str, string to check for date
        :param fuzzy: bool, ignore unknown tokens in string if True
        """
        try: 
            parse(string, fuzzy=fuzzy)
            return string

        except ValueError:
            raise ValueError(f"{string} cannot be parsed to date")
        

    @model_validator(mode="after")
    def check_date_range(self):
        if parse(self.EndDate) < parse(self.StartDate):
            raise ValueError(f"EndDate cannot be before StartDate")
        return self
    

def isWithinDateRange(curDateString, startScheduleDate, endScheduleDate):
    return startScheduleDate.date() <= parse(curDateString).date() <= endScheduleDate.date()

#----------------------------- FOR PATIENT TEST -----------------------------       
def getTablesDF():
    
    weeklyScheduleViewDF = WeeklyScheduleView.get_data()
    centreActivityPreferenceViewDF = CentreActivityPreferenceView.get_data()
    centreActivityRecommendationViewDF = CentreActivityRecommendationView.get_data()
    activitiesExcludedViewDF = ActivitiesExcludedView.get_data()
    routineViewDF = RoutineView.get_data()
    medicationViewDF = MedicationTesterView.get_data()
    activitiesAndCentreActivityViewDF = ActivityAndCentreActivityView.get_data() 
    
    tablesDF = {
        "weeklyScheduleViewDF" : weeklyScheduleViewDF,
        "centreActivityPreferenceViewDF" : centreActivityPreferenceViewDF,
        "centreActivityRecommendationViewDF" : centreActivityRecommendationViewDF,
        "activitiesExcludedViewDF" : activitiesExcludedViewDF,
        "routineViewDF" : routineViewDF,
        "medicationViewDF" : medicationViewDF,
        "activitiesAndCentreActivityViewDF": activitiesAndCentreActivityViewDF,
    }
    
    return tablesDF
    
    
def getPatientWellnessPlan(tablesDF, patientID, config):
    # Extract information from tables
    weekly_schedule = tablesDF['weeklyScheduleViewDF'].loc[tablesDF['weeklyScheduleViewDF']['PatientID'] == patientID]
    schedule_start_datetime = weekly_schedule['StartDate'].min()
    schedule_end_datetime = weekly_schedule['EndDate'].max()
        
    centre_activity_preference = tablesDF['centreActivityPreferenceViewDF'].loc[tablesDF['centreActivityPreferenceViewDF']['PatientID'] == patientID]
    centre_activity_recommendation = tablesDF['centreActivityRecommendationViewDF'].loc[tablesDF['centreActivityRecommendationViewDF']['PatientID'] == patientID]
    medications = tablesDF['medicationViewDF'].loc[tablesDF['medicationViewDF']['PatientID'] == patientID]

    # TYPE 'SHOULD SCHEDULE'
    preferred_activities = centre_activity_preference.loc[centre_activity_preference['IsLike'] == 1]
    preferred_activities = preferred_activities['ActivityTitle'].tolist()
    recommended_activities = centre_activity_recommendation.loc[centre_activity_recommendation['DoctorRecommendation'] == 1]
    recommended_activities = recommended_activities['ActivityTitle'].tolist()
    routines_df = tablesDF['routineViewDF'].loc[(tablesDF['routineViewDF']['PatientID'] == patientID) & tablesDF['routineViewDF']["IncludeInSchedule"]]
    routines = routines_df['ActivityTitle'].tolist()
    
    # To get the fixedtimeslots for each routine activity
    routines_timeslot = {}
    for routine in routines:
        routines_timeslot[routine] = routines_df.loc[routines_df['ActivityTitle'] == routine, 'FixedTimeSlots'].iloc[0]
    
    # TYPE 'SHOULD NOT SCHEDULE'
    non_preferred_activities = centre_activity_preference.loc[centre_activity_preference['IsLike'] == 0]
    non_preferred_activities = non_preferred_activities['ActivityTitle'].tolist()
    non_recommended_activities = centre_activity_recommendation.loc[centre_activity_recommendation['DoctorRecommendation'] == 0]
    non_recommended_activities = non_recommended_activities['ActivityTitle'].tolist()
    activities_excluded = tablesDF['activitiesExcludedViewDF'].loc[tablesDF['activitiesExcludedViewDF']['PatientID'] == patientID]
    activities_excluded = activities_excluded['ActivityTitle'].tolist()
    
    # TYPE 'MEDICATION'
    medication_schedule, medication_incorrect_schedule = prepareMedicationSchedule(medications, schedule_start_datetime, schedule_end_datetime, config['DAYS'])
    
    patient_wellness_plan = {
        'patientID' : patientID,
        'DAYS' : config['DAYS'],
        'DAY_OF_WEEK_ORDER' : config['DAY_OF_WEEK_ORDER'],
        'weekly_schedule': weekly_schedule,
        'schedule_start_datetime' : schedule_start_datetime,
        'schedule_end_datetime': schedule_end_datetime,
        'routines_timeslot' : routines_timeslot,
        'should_be_scheduled_activities': {
            'preferred': preferred_activities,
            'recommended': recommended_activities,
            'routines': routines,
            'error_check': {  # Duplicate lists for further processing
                'preferred': preferred_activities.copy(),
                'recommended': recommended_activities.copy(),
                'routines': routines.copy(),
            }
        },
        'should_not_be_scheduled_activities':{
            'non_preferred': non_preferred_activities,
            'non_recommended': non_recommended_activities,
            'excluded': activities_excluded,
            'error_check': {  # Initializing empty lists for further processing
                'non_preferred': [],
                'non_recommended': [],
                'excluded': [],
            }
        },
        'medication_info': {
            'medication_schedule' : medication_schedule,
            'error_check': { # Initializing empty dictionary for further processing
                "medication_schedule" : medication_incorrect_schedule
            }
        }
    }
    
    return patient_wellness_plan
    
    
def prepareMedicationSchedule(medications, schedule_start_datetime, schedule_end_datetime, DAYS):
    medication_schedule = {}
    medication_incorrect_schedule = {}
    
    medication_start_datetime = medications['StartDateTime'].min()
    medication_end_datetime = medications['EndDateTime'].max()
    # print(f"Medication start date: {week_start_datetime} | Medication end date: {week_end_datetime}")
    # print(f"Week start date: {week_start_datetime} | Week end date: {week_end_datetime}")
    
    # Assign NaT if week_end/start_datetime is NaN
    if pd.isna(medication_end_datetime):
        medication_end_datetime = pd.NaT
    if pd.isna(medication_start_datetime):
        medication_start_datetime = pd.NaT
    
    if medication_end_datetime > schedule_end_datetime:
        medication_end_datetime = schedule_end_datetime
        medication_end_datetime -= datetime.timedelta(days=2) ## NOTE: MINUS 2 TO GET THE DATETIME FOR FRIDAY OF THE WEEK
    if medication_start_datetime < schedule_start_datetime:
        medication_start_datetime = schedule_start_datetime
    
    for date in date_range(medication_start_datetime, medication_end_datetime, DAYS):
        medication_schedule[date.weekday()] = []
        medication_incorrect_schedule[date.weekday()] = []
        
        for index, medication_row in medications.iterrows():
            if medication_row['StartDateTime'] <= date <= medication_row['EndDateTime']:
                slots = medication_row['AdministerTime'].split(",")
                for slot in slots:
                    if medication_row['Instruction'] is None or medication_row['Instruction'].strip() == "" or medication_row['Instruction'] in ["Nil", "nil" "-"]:
                        medication_schedule[date.weekday()].append(f"Give Medication@{slot}: {medication_row['PrescriptionName']}({medication_row['Dosage']})")
                    else:
                        medication_schedule[date.weekday()].append(f"Give Medication@{slot}: {medication_row['PrescriptionName']}({medication_row['Dosage']})**{medication_row['Instruction']}")
                        
    # Sort the medication schedules for each day based on time
    for day, meds in medication_schedule.items():
        medication_schedule[day] = sorted(meds, key=sort_by_time) 
                        
    return medication_schedule, medication_incorrect_schedule
    
    
def sort_by_time(med_schedule):
    return int(med_schedule.split('@')[1].split(':')[0])
    
    
def date_range(start_date, end_date, DAYS):
    current_date = start_date
    counter = 1
    while current_date <= end_date:
        yield current_date
        counter += 1
        if counter > DAYS:
            break
        current_date += datetime.timedelta(days=1)
    
    
def prepareJsonResponse(json_response, patient_wellness_plan):
    # Create a deep copy of the patient_wellness_plan at the start. This is because list and dicts are mutable objects and are passed by reference. Thus any modification to patient_wellness_plan might affect json_response
    patient_wellness_plan_copy = copy.deepcopy(patient_wellness_plan)

    patientID = patient_wellness_plan_copy['patientID']
    
    # Make sure the patientID key exists in json_response
    json_response[patientID] = json_response.get(patientID, {})
    json_response[patientID]["Schedule start date"] = str(patient_wellness_plan_copy['schedule_start_datetime'])
    json_response[patientID]["Schedule end date"] = str(patient_wellness_plan_copy['schedule_end_datetime'])
    json_response[patientID]["Preferred Activities"] = patient_wellness_plan_copy['should_be_scheduled_activities']['preferred']
    json_response[patientID]["Non-Preferred Activities"] = patient_wellness_plan_copy['should_not_be_scheduled_activities']['non_preferred']
    json_response[patientID]["Activities Excluded"] = patient_wellness_plan_copy['should_not_be_scheduled_activities']['excluded']
    json_response[patientID]["Routines"] = patient_wellness_plan_copy['should_be_scheduled_activities']['routines']
    json_response[patientID]["Doctor Recommended Activities"] = patient_wellness_plan_copy['should_be_scheduled_activities']['recommended']
    json_response[patientID]["Doctor Non-Recommended Activities"] = patient_wellness_plan_copy['should_not_be_scheduled_activities']['non_recommended']
    json_response[patientID]["Medication Schedule"] = {}

    for day, schedule in patient_wellness_plan_copy['medication_info']['medication_schedule'].items():
        json_response[patientID]["Medication Schedule"][patient_wellness_plan['DAY_OF_WEEK_ORDER'][day]] = schedule

    return json_response
    
    
def printWellnessPlan(patient_wellness_plan):
    print(f"Schedule start date: {patient_wellness_plan['schedule_start_datetime']} | Schedule end date: {patient_wellness_plan['schedule_end_datetime']}")
    print(f"Preferred Activities: {patient_wellness_plan['should_be_scheduled_activities']['preferred']}")
    print(f"Non-Preferred Activities: {patient_wellness_plan['should_not_be_scheduled_activities']['non_preferred']}")
    print(f"Activities Excluded: {patient_wellness_plan['should_not_be_scheduled_activities']['excluded']}")
    print(f"Routines: {patient_wellness_plan['should_be_scheduled_activities']['routines']}")
    print(f"Doctor Recommended Activities: {patient_wellness_plan['should_be_scheduled_activities']['recommended']}")
    print(f"Doctor Non-Recommended Activities: {patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended']}")
    print(f"Medication Schedule:")
    
    for day, schedule in patient_wellness_plan['medication_info']['medication_schedule'].items():
        print(f"\t {patient_wellness_plan['DAY_OF_WEEK_ORDER'][day]}: ", end = '')
        print(schedule) 
    
    print()
    return
    
    
def checkWeeklyScheduleCorrectness(mondayIndex, patientInfo, patient_wellness_plan, json_response, activity_count_dict):
    """
    Validates the scheduled daily activities and medication of a patient against the patient's wellness plan.
    This function iterates through each day of the patient's schedule, comparing scheduled activities and medications
    against what is recommended or not recommended within the wellness plan. It updates the json_response with the
    activities scheduled for each day and performs error checking for both activities and medications, identifying
    discrepancies between the wellness plan and the actual schedule.

    Parameters:
    - mondayIndex: The index representing the start of the week within the patient's schedule data.
    - patientInfo: A series object containing the patient's weekly schedule, where each entry represents a day's activities and possibly medication instructions.
    - patient_wellness_plan: A structured dictionary detailing the patient's wellness plan, including which activities should or should not be scheduled, and the planned medication schedule.
    - json_response: A dictionary intended to be populated with the patient's schedule details for external output, structured by day of the week.
    - activity_count_dict: A dictionary used to count occurrences of each activity and medication administration event, aiding in validation and error reporting.

    The function performs the following operations:
    - Splits daily schedules into individual activities and checks them against the wellness plan's recommendations.
    - Differentiates between activities that should be scheduled (e.g., preferred, recommended, routines) and those that should not (e.g., non-preferred, non-recommended, excluded).
    - Tracks medications that are to be administered each day and validates these against the actual activities scheduled for medication administration.
    - Updates an 'error_check' sub-dictionary within both activity categories in the wellness plan to reflect any discrepancies found during the validation process.
    - Records any incorrectly scheduled medications in a dedicated error list for further analysis.
    
    For activities that are found and correctly scheduled, it removes them from the 'error_check' list of the corresponding category (indicating they were successfully planned). 
    Conversely, activities found that should not have been scheduled, or medications incorrectly administered, are added to their respective 'error_check' lists, highlighting scheduling errors.
    
    This detailed check aims to ensure adherence to the wellness plan, facilitating adjustments to the patient's schedule where necessary and improving the overall management of the patient's health and activities.
    
    Note: This function directly modifies the json_response and activity_count_dict parameters to reflect its findings and does not return any value.
    """
    DAYS = patient_wellness_plan['DAYS']
    DAY_OF_WEEK_ORDER = patient_wellness_plan['DAY_OF_WEEK_ORDER']
    patientID = patient_wellness_plan['patientID']
    
    should_be_scheduled_activities = patient_wellness_plan['should_be_scheduled_activities']
    should_not_be_scheduled_activities = patient_wellness_plan['should_not_be_scheduled_activities']
    medication_schedule = patient_wellness_plan['medication_info']['medication_schedule']
    medication_incorrect_schedule = patient_wellness_plan['medication_info']['error_check']['medication_schedule']
    
    ## ITERATE OVER EVERYDAY IN THE WEEKLY SCHEDULE 
    for day in range(mondayIndex, DAYS+mondayIndex):
        print(f"{DAY_OF_WEEK_ORDER[day-mondayIndex]}: {patientInfo.iloc[day]}")
        json_response[patientID][f"{DAY_OF_WEEK_ORDER[day-mondayIndex]} Activities"] = patientInfo.iloc[day]
        
        activities_in_a_day = patientInfo.iloc[day].split("--") # get a list of all the activities in a day. Example: ["String beads", "Breathing+Vital Check | Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses" , "Cup Stacking Game", "Lunch"] 
        
        medications_to_give = [] # prepare a list of all the medications that should be given in the day
        if (day-mondayIndex) in medication_schedule:
            medications_to_give = medication_schedule[(day-mondayIndex)]
            
        ## ITERATE OVER EACH ACTIVITY IN THE DAY AND VALIDATE IT AGAINST THE PATIENT WELLNESS PLAN
        for activity in activities_in_a_day:
            '''
            FOR SHOULD SCHEDULE ACTIVITIES:
                The error_check lists (initially a duplicated list of its original) is meant to store only the activities that are meant to be scheduled but are somehow not scheduled.
                Therefore, when we iterate through each item in the should_be_scheduled_activities, if the item corresponds to the current activity, 
                it suggests that it has been scheduled and hence we will remove it from the error_check lists. This means that whatever activities that are left in the 
                error_check lists, there are not scheduled when they should be.
            
            'should_be_scheduled_activities': {
                'preferred': preferred_activities,
                'recommended': recommended_activities,
                'routines': routines,
                'error_check': {  # Duplicate lists for further processing
                    'preferred': preferred_activities,
                    'recommended': recommended_activities,
                    'routines': routines,
                    }
                }
                
            '''
            for activity_type in should_be_scheduled_activities['error_check']:
                for item in should_be_scheduled_activities['error_check'][activity_type]:
                    if (item in activity) and (item in should_be_scheduled_activities['error_check'][activity_type]):
                        should_be_scheduled_activities['error_check'][activity_type].remove(item)
                        
            '''
            FOR SHOULD NOT SCHEDULE ACTIVITIES:
                The error_check lists (initially an empty list) is meant to store only the activities that are meant to NOT be scheduled but are somehow scheduled.
                Therefore, when we iterate through each item in the should_not_be_scheduled_activities, if the item corresponds to the current activity, 
                it suggests that it HAS been wrongly scheduled and hence we will add it to the error_check lists. This means that whatever activities that are left in the 
                error_check lists, are activities that are scheduled when they should not be.
                
            'should_not_be_scheduled_activities':{
                'non_preferred': non_preferred_activities,
                'non_recommended': non_recommended_activities,
                'excluded': activities_excluded,
                'error_check': {  # Initializing empty lists for further processing
                    'non_preferred': [],
                    'non_recommended': [],
                    'excluded': [],
                }
            }
            '''
            for activity_type in should_not_be_scheduled_activities['error_check']:
                for item in should_not_be_scheduled_activities[activity_type]:
                    if (item in activity) and (item not in should_not_be_scheduled_activities['error_check'][activity_type]):
                        should_not_be_scheduled_activities['error_check'][activity_type].append(item)
            
            '''
            FOR MEDICATION: 
                Checks the scheduled medications against the medications_to_give and if it is correctly scheduled, we remove it from medication_schedule. This means that
                if all medications are given correctly, medication_schedule should be empty. Conversely, if an incorrect medication has been scheduled, we add it to medication_incorrect_schedule
            '''
            if len(medications_to_give) != 0 and "Give Medication" in activity:
                activity_name = activity.split(' | ')[0]  # "Breathing+Vital Check | Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses"
                activity_count_dict[activity_name] += 1
                
                # print(f"Current activity: {activity}")
                pattern = r'Give Medication@\d{4}: [^,]+'
                matches = re.findall(pattern, activity)
                for match in matches:
                    if match in medications_to_give:
                        medication_schedule[(day-mondayIndex)].remove(match)
                    else:         
                        if medication_incorrect_schedule[(day-mondayIndex)] is None:
                            medication_incorrect_schedule[(day-mondayIndex)] = []    
                        medication_incorrect_schedule[(day-mondayIndex)].append(match)
                # print(f"Current state of medication_schedule: {medication_schedule[(day-2)]}")
            else:
                activity_count_dict[activity] += 1
                
    return
    
# Test 1: Activities excluded are not scheduled
def activitiesExcludedPatientTest(patient_wellness_plan, json_response):
    patientID = patient_wellness_plan['patientID']
    activities_excluded = patient_wellness_plan['should_not_be_scheduled_activities']['excluded']
    duplicated_activities_excluded = patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['excluded']
    
    print("Test 1: Activities excluded are not scheduled ", end = '')
    json_response[patientID]["Test 1"] = {"Title" : "Activities excluded are not scheduled", "Result" : None, "Reason":[]}
    
    patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['excluded']
    if len(duplicated_activities_excluded) == 0:
        print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        json_response[patientID]["Test 1"]["Result"] = "Passed"
    else:
        print(Fore.RED + f"(Failed)" + Fore.RESET)
        json_response[patientID]["Test 1"]["Result"] = "Failed"
        
        print(Fore.RED + f"\tThe following activities excluded are scheduled: {duplicated_activities_excluded}" + Fore.RESET)
        json_response[patientID]["Test 1"]["Reason"].append(f"The following activities excluded are scheduled: {duplicated_activities_excluded}")

# Test 2: Patient preferred activities are scheduled
def preferredActivitiesPatientTest(patient_wellness_plan, json_response):
    patientID = patient_wellness_plan['patientID']
    preferred_activities = patient_wellness_plan['should_be_scheduled_activities']['preferred']
    activities_excluded = patient_wellness_plan['should_not_be_scheduled_activities']['excluded']
    non_recommended_activities = patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended']
    duplicated_preferred_activities = patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred']
    
    print(f"Test 2: Patient preferred activities are scheduled ", end = '')
    json_response[patientID]["Test 2"] = {"Title" : "Patient preferred activities are scheduled", "Result" : None, "Reason":[]}
    
    if len(duplicated_preferred_activities) == 0:
        print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        json_response[patientID]["Test 2"]["Result"] = "Passed"
    else:
        common_exclusion_and_preferred = list(set(activities_excluded) & set(duplicated_preferred_activities))
        common_non_recommended_and_preferred = list(set(non_recommended_activities) & set(duplicated_preferred_activities))
        not_in_exclusion_or_non_recommended = list(set(duplicated_preferred_activities) - (set(activities_excluded) | set(non_recommended_activities)))
        
        if len(not_in_exclusion_or_non_recommended) != 0:
            print(Fore.RED + f"(Failed)" + Fore.RESET)
            json_response[patientID]["Test 2"]["Result"] = "Failed"
            
            if len(common_exclusion_and_preferred) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                json_response[patientID]["Test 2"]["Reason"].append(f"(Exception) {common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded")
                
            if len(common_non_recommended_and_preferred) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities" + Fore.RESET)
                json_response[patientID]["Test 2"]["Reason"].append(f"(Exception) {common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities")
                
            print(Fore.RED + f"\tThe following preferred activities are not scheduled: {not_in_exclusion_or_non_recommended}" + Fore.RESET)
            json_response[patientID]["Test 2"]["Reason"].append(f"The following preferred activities are not scheduled: {not_in_exclusion_or_non_recommended}")
        else:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
            json_response[patientID]["Test 2"]["Result"] = "Passed"
            
            if len(common_exclusion_and_preferred) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                json_response[patientID]["Test 2"]["Reason"].append(f"(Exception) {common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded")
                
            if len(common_non_recommended_and_preferred) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities" + Fore.RESET)
                json_response[patientID]["Test 2"]["Reason"].append(f"(Exception) {common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities")
                
# Test 3: Patient non-preferred activities are not scheduled        
def nonPreferredActivitiesPatientTest(patient_wellness_plan, json_response):
    patientID = patient_wellness_plan['patientID']
    recommended_activities = patient_wellness_plan['should_be_scheduled_activities']['recommended']
    routines = patient_wellness_plan['should_be_scheduled_activities']['routines']
    duplicated_non_preferred_activities = patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_preferred']
    
    print(f"Test 3: Patient non-preferred activities are not scheduled ", end = '')
    json_response[patientID]["Test 3"] = {"Title" : "Patient non-preferred activities are not scheduled", "Result" : None, "Reason":[]}
    
    if len(duplicated_non_preferred_activities) == 0:
        print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        json_response[patientID]["Test 3"]["Result"] = "Passed"
    else:
        common_recommended_and_non_preferred = list(set(recommended_activities) & set(duplicated_non_preferred_activities))
        common_routines_and_non_preferred = list(set(routines) & set(duplicated_non_preferred_activities))
        not_in_recommended_or_routines = list(set(duplicated_non_preferred_activities) - (set(recommended_activities) | set(routines)))
        
        if len(not_in_recommended_or_routines) != 0:
            print(Fore.RED + f"(Failed)" + Fore.RESET)
            json_response[patientID]["Test 3"]["Result"] = "Failed"
            
            if len(common_recommended_and_non_preferred) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
                json_response[patientID]["Test 3"]["Reason"].append(f"(Exception) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities")
            
            if len(common_routines_and_non_preferred) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_routines_and_non_preferred} are scheduled because there are part of Routines Activities" + Fore.RESET)
                json_response[patientID]["Test 3"]["Reason"].append(f"(Exception) {common_routines_and_non_preferred} are scheduled because there are part of Routines Activities")
                
            print(Fore.RED + f"\tThe following non-preferred activities are scheduled: {not_in_recommended_or_routines}" + Fore.RESET)
            json_response[patientID]["Test 3"]["Reason"].append(f"The following non-preferred activities are scheduled: {not_in_recommended_or_routines}")
            
        else:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
            json_response[patientID]["Test 3"]["Result"] = "Passed"
            
            if len(common_recommended_and_non_preferred) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
                json_response[patientID]["Test 3"]["Reason"].append(f"(Exception) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities")
    
# Test 4: Doctor recommended activities are scheduled
def recommendedActivitiesPatientTest(patient_wellness_plan, json_response):   
    patientID = patient_wellness_plan['patientID']
    activities_excluded = patient_wellness_plan['should_not_be_scheduled_activities']['excluded']
    duplicated_recommended_activities = patient_wellness_plan['should_be_scheduled_activities']['error_check']['recommended']
    
    print(f"Test 4: Doctor recommended activities are scheduled ", end = '')
    json_response[patientID]["Test 4"] = {"Title" : "Doctor recommended activities are scheduled", "Result" : None, "Reason":[]}
    
    if len(duplicated_recommended_activities) == 0:
        print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        json_response[patientID]["Test 4"]["Result"] = "Passed"
    else:
        common_excluded_and_recommended = list(set(activities_excluded) & set(duplicated_recommended_activities))
        not_in_excluded = list(set(duplicated_recommended_activities) - set(activities_excluded))
        
        if len(not_in_excluded) != 0:
            print(Fore.RED + f"(Failed)" + Fore.RESET)
            json_response[patientID]["Test 4"]["Result"] = "Failed"
            
            if len(common_excluded_and_recommended) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded"  + Fore.RESET)
                json_response[patientID]["Test 4"]["Reason"].append(f"(Exception) {common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded")
                
            print(Fore.RED + f"\tThe following doctor recommended activities are not scheduled: {not_in_excluded}" + Fore.RESET)
            json_response[patientID]["Test 4"]["Reason"].append(f"The following doctor recommended activities are not scheduled: {not_in_excluded}")
        else:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
            json_response[patientID]["Test 4"]["Result"] = "Passed"
            
            if len(common_excluded_and_recommended) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded"  + Fore.RESET)
                json_response[patientID]["Test 4"]["Reason"].append(f"(Exception) {common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded")
                
# Test 5: Doctor non-recommended activities are not scheduled
def nonRecommendedActivitiesPatientTest(patient_wellness_plan, json_response):  
    patientID = patient_wellness_plan['patientID']
    duplicated_non_recommended_activities = patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_recommended']
    
    print(f"Test 5: Doctor non-recommended activities are not scheduled ", end = '')
    json_response[patientID]["Test 5"] = {"Title" : "Doctor non-recommended activities are not scheduled", "Result" : None, "Reason":[]}

    if len(duplicated_non_recommended_activities) == 0:
        print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        json_response[patientID]["Test 5"]["Result"] = "Passed"
    else:
        print(Fore.RED + f"(Failed)" + Fore.RESET)
        json_response[patientID]["Test 5"]["Result"] = "Failed"
        
        print(Fore.RED + f"\tThe following doctor non-recommended activities are scheduled: {duplicated_non_recommended_activities}" + Fore.RESET)
        json_response[patientID]["Test 5"]["Reason"].append(f"The following doctor non-recommended activities are scheduled: {duplicated_non_recommended_activities}")
                
# Test 6: Patient routines are scheduled   
def routinesPatientTest(patient_wellness_plan, json_response):
    patientID = patient_wellness_plan['patientID']
    activities_excluded = patient_wellness_plan['should_not_be_scheduled_activities']['excluded']
    non_recommended_activities = patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended']
    duplicated_routines = patient_wellness_plan['should_be_scheduled_activities']['error_check']['routines']
    
    print(f"Test 6: Patient routines are scheduled ", end = '')
    json_response[patientID]["Test 6"] = {"Title" : "Patient routines are scheduled", "Result" : None, "Reason":[]}
    
    if len(duplicated_routines) == 0:
        print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        json_response[patientID]["Test 6"]["Result"] = "Passed"
    else:
        common_excluded_and_routines = list(set(activities_excluded) & set(duplicated_routines))
        common_non_recommend_and_routines = list(set(non_recommended_activities) & set(duplicated_routines))
        not_in_excluded_or_non_recommended = list(set(duplicated_routines) - (set(activities_excluded) | set(non_recommended_activities)))
        
        if len(not_in_excluded_or_non_recommended) != 0:
            print(Fore.RED + f"(Failed)" + Fore.RESET)
            json_response[patientID]["Test 6"]["Result"] = "Failed"
                
            if len(common_excluded_and_routines) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                json_response[patientID]["Test 6"]["Reason"].append(f"(Exception) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded")
            
            if len(common_non_recommend_and_routines) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_non_recommend_and_routines} are not scheduled because there are part of Doctor Non Recommended Activities" + Fore.RESET)
                json_response[patientID]["Test 6"]["Reason"].append(f"(Exception) {common_non_recommend_and_routines} are not scheduled because there are part of Doctor Non Recommended Activities")
                        
            print(Fore.RED + f"\tThe following routines are not scheduled: {not_in_excluded_or_non_recommended}" + Fore.RESET)
            json_response[patientID]["Test 6"]["Reason"].append(f"The following routines are not scheduled: {not_in_excluded_or_non_recommended}")
        else:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
            json_response[patientID]["Test 6"]["Result"] = "Passed"
            
            if len(common_excluded_and_routines) != 0:
                print(Fore.YELLOW + f"\t(Exception) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                json_response[patientID]["Test 6"]["Reason"].append(f"(Exception) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded")      

# Test 7: All medications are administered correctly
def medicationPatientTest(patient_wellness_plan, json_response):
    DAY_OF_WEEK_ORDER = patient_wellness_plan['DAY_OF_WEEK_ORDER']
    patientID = patient_wellness_plan['patientID']
    medication_schedule = patient_wellness_plan['medication_info']['medication_schedule']
    medication_incorrect_schedule = patient_wellness_plan['medication_info']['error_check']['medication_schedule']
    
    print(f"Test 7: All medications are administered correctly ", end = '')
    json_response[patientID]["Test 7"] = {"Title" : "All medications are administered correctly", "Result" : None, "Reason":{}}
    
    correct_medications_scheduled = True
    for day, correct_medications in medication_schedule.items():
        if len(correct_medications) != 0:
            correct_medications_scheduled = False
            print(Fore.RED + f"(Failed)" + Fore.RESET)
            json_response[patientID]["Test 7"]["Result"] = "Failed"
            
            print(Fore.RED + f"\tFor {DAY_OF_WEEK_ORDER[day]}:")
            json_response[patientID]["Test 7"]["Reason"][f"{DAY_OF_WEEK_ORDER[day]}"] = []
            
            print(Fore.RED + f"\t(Incorrect) The following medications were scheduled incorrectly: {medication_incorrect_schedule[day]}" + Fore.RESET)
            json_response[patientID]["Test 7"]["Reason"][f"{DAY_OF_WEEK_ORDER[day]}"].append(f"(Incorrect) The following medications were scheduled incorrectly: {medication_incorrect_schedule[day]}")
            
            print(Fore.YELLOW + f"\t(Correct) The medications that are supposed to be scheduled are: {medication_schedule[day]}" + Fore.RESET)   
            json_response[patientID]["Test 7"]["Reason"][f"{DAY_OF_WEEK_ORDER[day]}"].append(f"(Correct) The medications that are supposed to be scheduled are: {medication_schedule[day]}")            
    if correct_medications_scheduled:
        print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        json_response[patientID]["Test 7"]["Result"] = "Passed"                
    
    
def generateStatistics(tablesDF, patient_wellness_plan, json_response, activity_count_dict):
    patientID = patient_wellness_plan['patientID']
    
    print(Fore.CYAN + "PATIENT REPORT" + Fore.RESET)
    print(f'Scheduled Activities Count: ')
    print(f'{activity_count_dict}')
    json_response[patientID]["Scheduled Activities Count"] = activity_count_dict
    
    top_5_activities = sorted(activity_count_dict.items(), key=lambda x: x[1], reverse=True)[:5]
    btm_5_activities = sorted(activity_count_dict.items(), key=lambda x: x[1], reverse=False)[:5]
    
    print("\nTop 5 most scheduled activities:")
    for activity, occurrences in top_5_activities:
        print(f"\t{activity}: {occurrences}")
    
    print("\nBottom 5 least scheduled activities:")
    for activity, occurrences in btm_5_activities:
        print(f"\t{activity}: {occurrences}")
        
    group_activity_count = sum(activity_count_dict.get(activity, 0) for activity in tablesDF['activitiesAndCentreActivityViewDF'].loc[tablesDF['activitiesAndCentreActivityViewDF']['IsGroup'] == 1, 'ActivityTitle'])
    json_response[patientID]["Group Activities Count"] = group_activity_count
    
    solo_activity_count = sum(activity_count_dict.get(activity, 0) for activity in tablesDF['activitiesAndCentreActivityViewDF'].loc[tablesDF['activitiesAndCentreActivityViewDF']['IsGroup'] == 0, 'ActivityTitle'])
    json_response[patientID]["Solo Activities Count"] = solo_activity_count
    
    print(f"\nNumber of group activities: {group_activity_count}")
    print(f"Number of solo-group activities: {solo_activity_count}\n\n")
    
#--------------------------------------------------------------------------       

def getDaysFromDates(startDateString, endDateString, week_order: List[str]):
    startDayIdx = parse(startDateString).weekday()
    endDayIdx = parse(endDateString).weekday()

    return week_order[startDayIdx: endDayIdx+1]

def replaceActivitiesInSchedule(filteredAdHocDF, oldActivityName, newActivityName, chosenDays):
    for i, record in filteredAdHocDF.iterrows():
        for col in chosenDays:
            originalSchedule = record[col]
            if originalSchedule != "":
                if oldActivityName not in originalSchedule:
                    return False  
                newSchedule = originalSchedule.replace(oldActivityName, newActivityName)
                filteredAdHocDF.at[i,col] = newSchedule

    return True



def allPatientScheduleGeneratedSystemTest(weeklyScheduleViewDF, patientsDF):
    testName = "All patient weekly schedule is generated"
    testRemarks = []
    testResult = "Pass"

    patientSet = set()

    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSet.add(scheduleRecord["PatientID"])
    
    result = True
    for _, patientRecord in patientsDF.iterrows():
        if patientRecord["PatientID"] not in patientSet:
            result = False
            testRemarks.append(f"{patientRecord['PatientID']} does not have a weekly schedule")
    
    if not result:
        testResult = "Fail"

    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}


def allCompulsoryActivitiesAtCorrectSlotSystemTest(weeklyScheduleViewDF, compulsoryActivitiesDF, request):
    testName = "All compulsory activities are scheduled at correct time slots for all patients"
    testRemarks = []
    testResult = "Pass"
    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]

        for _, compActivityRecord, in compulsoryActivitiesDF.iterrows():
            fixedTimeSlots = compActivityRecord["FixedTimeSlots"].split(",")
            fixedTimeSlots = [(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots]
            compActivityName = compActivityRecord["ActivityTitle"]

            allCompulsoryScheduled = True
            for day, timeslot in fixedTimeSlots:
                if compActivityName not in patientSchedule[day][timeslot]:
                    allCompulsoryScheduled = False
                    testRemarks.append(f"{compActivityName} not scheduled at correct time slot for patient ID {scheduleRecord['PatientID']}. Scheduled timeslot is {request.app.state.config['DAY_OF_WEEK_ORDER'][day]} {request.app.state.config['DAY_TIMESLOTS'][timeslot]}")

    if not allCompulsoryScheduled:
        testResult = "Fail"

    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}


def nonExpiredCentreActivitiesSystemTest(activitiesDF, weeklyScheduleViewDF):
    testName = "Only centre activities 'not expired' are scheduled"
    testRemarks = []
    testResult = "Pass"

    validityMap = {}
    for _, activityRecord, in activitiesDF.iterrows():
        if activityRecord["ActivityTitle"] not in validityMap:
            validityMap[activityRecord["ActivityTitle"]] = [activityRecord["StartDate"], activityRecord["EndDate"]]

    result = True
    startScheduleDate = weeklyScheduleViewDF["StartDate"].iloc[0]
    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        addDays = 0
        for daySchedule in patientSchedule:
            dateOfActivity = startScheduleDate + datetime.timedelta(days=addDays)
            if len(daySchedule) <= 1:
                continue

            for activity in daySchedule:
                activityTitle = activity.split(" |")[0]
                
                if activityTitle == "Free and Easy":
                    continue
                
                if not (validityMap[activityTitle][0] <= dateOfActivity <= validityMap[activityTitle][1]):
                    result = False
                    testRemarks.append(f"{activityTitle} for patient ID {scheduleRecord['PatientID']} on {dateOfActivity.strftime('%Y-%m-%d')} has expired and is not valid")
            addDays += 1
    
    if not result:
        testResult = "Fail"
            
    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}



def fixedActivitiesScheduledCorrectlySystemTest(activitiesDF, validRoutinesDF, weeklyScheduleViewDF, request):
    testName = "Fixed time centre activities are scheduled in the correct timeslot (fixed and routine activities)"
    testRemarks = []
    testResult = "Pass"

    fixedActivitiesDF = activitiesDF.query("IsFixed == True")
    fixedActivityMap = {} #activityTitle: set(fixedTimeSlots)
    for _, activityRecord in fixedActivitiesDF.iterrows():
        fixedTimeSlots = activityRecord["FixedTimeSlots"].split(",")
        fixedTimeSlots = set([(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots])
        fixedActivityMap[activityRecord["ActivityTitle"]] = fixedTimeSlots

    routineActivityMap = {} #routine activityTitle: set(fixedTimeSlots)
    for _, routineRecord in validRoutinesDF.iterrows():
        fixedTimeSlots = routineRecord["FixedTimeSlots"].split(",")
        fixedTimeSlots = set([(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots])
        routineActivityMap[routineRecord["ActivityTitle"]] = fixedTimeSlots
    

    result = True
    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        for day, daySchedule in enumerate(patientSchedule):
            if len(daySchedule) <= 1:
                continue
            for timeslot, activity in enumerate(daySchedule):
                activityTitle = activity.split(" |")[0]
                if activityTitle in fixedActivityMap and (day, timeslot) not in fixedActivityMap[activityTitle] and activityTitle in routineActivityMap and (day, timeslot) not in routineActivityMap[activityTitle]:
                    result = False
                    testRemarks.append(f"{activityTitle} for patient ID {scheduleRecord['PatientID']} is not scheduled in one of its fixed time slots. Scheduled Time Slot is {request.app.state.config['DAY_OF_WEEK_ORDER'][day]} {request.app.state.config['DAY_TIMESLOTS'][timeslot]}")

    if not result:
        testResult = "Fail"
            
    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}


def groupActivitiesMinSizeSystemTest(groupActivitiesDF,weeklyScheduleViewDF):
    testName = "Group activities meet the minimum number of people"
    testRemarks = []
    testResult = "Pass"
    minSizeMap = {} #activityTitle: min size req

    result = True
    for _, grpActivityRecord in groupActivitiesDF.iterrows():
        minSizeMap[grpActivityRecord["ActivityTitle"]] = [grpActivityRecord["MinPeopleReq"],grpActivityRecord["MinPeopleReq"]]

    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        for _, daySchedule in enumerate(patientSchedule):
            if len(daySchedule) <= 1:
                continue
    
            for _, activity in enumerate(daySchedule):
                activityTitle = activity.split(" |")[0]
                if activityTitle in minSizeMap:
                    minSizeMap[activityTitle][0] -= 1
                    if minSizeMap[activityTitle][0] == 0:
                        minSizeMap.pop(activityTitle)


    for activityTitle, sizeList in minSizeMap.items():
        result = False
        testRemarks.append(f"{activityTitle} did not hit minumum size of {sizeList[1]}")

    if not result:
        testResult = "Fail"
            
    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}

def groupActivitiesCorrectTimeslotSystemTest(groupActivitiesDF, weeklyScheduleViewDF, request):
    testName = "Group activities are scheduled in the correct timeslot"
    testRemarks = []
    testResult = "Pass"
    groupActivitySet = set()

    result = True
    for _, grpActivityRecord in groupActivitiesDF.iterrows():
        groupActivitySet.add(grpActivityRecord["ActivityTitle"])

    timeSlotSet = set(request.app.state.config["GROUP_TIMESLOT_MAPPING"])

    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        for day, daySchedule in enumerate(patientSchedule):
            if len(daySchedule) <= 1:
                continue
            for timeslot, activity in enumerate(daySchedule):
                activityTitle = activity.split(" |")[0] 
                if activityTitle in groupActivitySet:
                    if (day, timeslot) not in timeSlotSet:
                        result = False
                        testRemarks.append(f"{activityTitle} for patient ID {scheduleRecord['PatientID']} is not scheduled in one of the fixed group time slots. Scheduled Time Slot is {request.app.state.config['DAY_OF_WEEK_ORDER'][day]} {request.app.state.config['DAY_TIMESLOTS'][timeslot]}")

    if not result:
        testResult = "Fail"
            
    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}


def systemLevelStatistics(activitiesDF, weeklyScheduleViewDF):
    activityCountMap = defaultdict(int)
    activityCountMap['Free and Easy'] = 0
    for _, activityRecord, in activitiesDF.iterrows():
        activityCountMap[activityRecord["ActivityTitle"]] = 0

    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        for _, daySchedule in enumerate(patientSchedule):
            if len(daySchedule) <= 1:
                continue
            for _, activity in enumerate(daySchedule):
                activityTitle = activity.split(" |")[0] 
                activityCountMap[activityTitle] += 1



    maxActivities = []
    maxActivityCount = max(activityCountMap.values())
    minActivities = []
    minActivityCount = min(activityCountMap.values())

    statsResult = []
    for activity, count in activityCountMap.items():
        statsResult.append(f"{activity}: {count}")
        if count == maxActivityCount:
            maxActivities.append(activity)
        if count == minActivityCount:
            minActivities.append(activity)


    return statsResult, minActivities, maxActivities


def clashInFixedTimeSlotWarning(activitiesDF, validRoutinesDF, request):
    warningName = "Clash in Fixed Time Slots"
    warningRemarks = []

    timeSlotMap = {} # map fixed time slots to activity
    fixedActivitiesDF = activitiesDF.query("IsFixed == True")

    for _, activityRecord in fixedActivitiesDF.iterrows():
        fixedTimeSlots = activityRecord["FixedTimeSlots"].split(",")
        fixedTimeSlots = [(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots]
        activityTitle = activityRecord["ActivityTitle"] + "(normal)"
        for ts in fixedTimeSlots:
            if ts not in timeSlotMap:
                timeSlotMap[ts] = [activityTitle]
            else:
                timeSlotMap[ts].append(activityTitle)

    for _, routineRecord in validRoutinesDF.iterrows():
        fixedTimeSlots = routineRecord["FixedTimeSlots"].split(",")
        fixedTimeSlots = [(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots]
        activityTitle = routineRecord["ActivityTitle"] + "(routine)"
        for ts in fixedTimeSlots:
            if ts not in timeSlotMap:
                timeSlotMap[ts] = [activityTitle]
            else:
                timeSlotMap[ts].append(activityTitle)

    for timeslot, activityList in timeSlotMap.items():
        warningStatement = ""
        if len(activityList) > 1:
            warningStatement += f"These activities have clashing fixed timeslots on {request.app.state.config['DAY_OF_WEEK_ORDER'][timeslot[0]]} {request.app.state.config['DAY_TIMESLOTS'][timeslot[1]]}: "
            for activity in activityList:
                warningStatement += f"{activity}, "

        if warningStatement:
            warningRemarks.append(warningStatement[:-1])

    return {"warningName": warningName, "warningRemarks": warningRemarks}