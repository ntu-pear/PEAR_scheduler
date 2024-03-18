import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.encoders import jsonable_encoder
from typing import Optional
from pear_schedule.db_utils.views import ValidRoutineActivitiesView, ActivityNameView, AdHocScheduleView, GroupActivitiesOnlyView, WeeklyScheduleView, CentreActivityPreferenceView, CentreActivityRecommendationView, ActivitiesExcludedView, RoutineView, MedicationTesterView, ActivityAndCentreActivityView, CompulsoryActivitiesOnlyView,PatientsOnlyView,AllActivitiesView
import pandas as pd
import re

from pear_schedule.db import DB
from sqlalchemy.orm import Session
import datetime
from pear_schedule.db_utils.writer import ScheduleWriter

from pear_schedule.api.utils import AdHocRequest, isWithinDateRange, getDaysFromDates, date_range, replaceActivitiesInSchedule, allPatientScheduleGeneratedSystemTest, allCompulsoryActivitiesAtCorrectSlotSystemTest,nonExpiredCentreActivitiesSystemTest,fixedActivitiesScheduledCorrectlySystemTest, groupActivitiesMinSizeSystemTest, groupActivitiesCorrectTimeslotSystemTest, systemLevelStatistics,clashInFixedTimeSlotWarning
from pear_schedule.scheduler.scheduleUpdater import ScheduleRefresher
from pear_schedule.scheduler.utils import build_schedules
from pear_schedule.utils import DBTABLES


logger = logging.getLogger(__name__)

from colorama import init, Fore

init(autoreset=True)


router = APIRouter()


@router.api_route("/generate/", methods=["GET"])
def generate_schedule(request: Request):
    config = request.app.state.config
    
    # Set up patient schedule structure
    patientSchedules = {} # patient id: [[],[],[],[],[]]

    try:
        build_schedules(config, patientSchedules)

        if ScheduleWriter.write(patientSchedules, overwriteExisting=False):
            responseData = {"Status": "200", "Message": "Generated Schedule Successfully", "Data": ""} 
            return JSONResponse(jsonable_encoder(responseData))
        else:
            responseData = {"Status": "500", "Message": "Error in writing schedule to DB. Check scheduler logs", "Data": ""} 
            return JSONResponse(jsonable_encoder(responseData))
            
    except Exception as e:
        logger.exception(e)
        responseData = {"Status": "400", "Message": str(e), "Data": ""}
        return JSONResponse(jsonable_encoder(responseData))


@router.api_route("/regenerate/", methods=["GET"])
def generate_schedule(request: Request):
    config = request.app.state.config
    
    # Set up patient schedule structure
    patientSchedules = {} # patient id: [[],[],[],[],[]]

    try:
        build_schedules(config, patientSchedules)

        if ScheduleWriter.write(patientSchedules, overwriteExisting=True):
            responseData = {"Status": "200", "Message": "Generated Schedule Successfully", "Data": ""} 
            return JSONResponse(jsonable_encoder(responseData))
        else:
            responseData = {"Status": "500", "Message": "Error in writing schedule to DB. Check scheduler logs", "Data": ""} 
            return JSONResponse(jsonable_encoder(responseData))
            
    except Exception as e:
        logger.exception(e)
        responseData = {"Status": "400", "Message": str(e), "Data": ""}
        return JSONResponse(jsonable_encoder(responseData))


@router.api_route("/patientTest/", methods=["GET"])
async def test_schedule(request: Request, patientID: Optional[int] = None): 
    try:
        json_response = {}
        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        weeklyScheduleViewDF = WeeklyScheduleView.get_data()
        centreActivityPreferenceViewDF = CentreActivityPreferenceView.get_data()
        centreActivityRecommendationViewDF = CentreActivityRecommendationView.get_data()
        activitiesExcludedViewDF = ActivitiesExcludedView.get_data()
        routineViewDF = RoutineView.get_data()
        medicationViewDF = MedicationTesterView.get_data()
        
        activitiesAndCentreActivityViewDF = ActivityAndCentreActivityView.get_data() 
        activity_count_dict = {activity: 0 for activity in activitiesAndCentreActivityViewDF['ActivityTitle'].unique()}
        
        print(weeklyScheduleViewDF['PatientID'].unique().tolist())
        if patientID is not None:
            if int(patientID) in weeklyScheduleViewDF['PatientID'].unique().tolist():
                weeklyScheduleViewDF = weeklyScheduleViewDF.loc[weeklyScheduleViewDF['PatientID'] == int(patientID)]
            else:
                responseData = {"Status": "400", "Message": f"Patient {patientID} does not exist in the schedule", "Data": ""} 
                return JSONResponse(jsonable_encoder(responseData))
            
        
        for index, row, in weeklyScheduleViewDF.iterrows():
            print(Fore.CYAN + f"=========================================== Checking patient {row['PatientID']} schedule now ===========================================" + Fore.RESET)
            
            patientID = row['PatientID']
            json_response[patientID] = {}
            
            for activity in activity_count_dict:
                activity_count_dict[activity] = 0
            weekly_schedule_for_patient = weeklyScheduleViewDF.loc[weeklyScheduleViewDF['PatientID'] == patientID]
            centre_activity_preference_for_patient = centreActivityPreferenceViewDF.loc[centreActivityPreferenceViewDF['PatientID'] == patientID]
            centre_activity_recommendation_for_patient = centreActivityRecommendationViewDF.loc[centreActivityRecommendationViewDF['PatientID'] == patientID]
            activities_excluded_for_patient = activitiesExcludedViewDF.loc[activitiesExcludedViewDF['PatientID'] == patientID]
            routine_for_patient = routineViewDF.loc[(routineViewDF['PatientID'] == patientID) & routineViewDF["IncludeInSchedule"]]
            medication_for_patient = medicationViewDF.loc[medicationViewDF['PatientID'] == patientID]
            centre_activity_likes = centre_activity_preference_for_patient.loc[centre_activity_preference_for_patient['IsLike'] == True]
            centre_activity_dislikes = centre_activity_preference_for_patient.loc[centre_activity_preference_for_patient['IsLike'] == False]
            centre_activity_recommended = centre_activity_recommendation_for_patient.loc[centre_activity_recommendation_for_patient['DoctorRecommendation'] == True]
            centre_activity_non_recommended = centre_activity_recommendation_for_patient.loc[centre_activity_recommendation_for_patient['DoctorRecommendation'] == False]
            
            # Lists created for comparison later on
            # TYPE 'SHOULD SCHEDULE'
            ori_centre_activity_likes = centre_activity_likes['ActivityTitle'].tolist()
            dup_centre_activity_likes = centre_activity_likes['ActivityTitle'].tolist()
            ori_routine_for_patient = routine_for_patient['ActivityTitle'].tolist()
            dup_routine_for_patient = routine_for_patient['ActivityTitle'].tolist()
            ori_centre_activity_recommended = centre_activity_recommended['ActivityTitle'].tolist()
            dup_centre_activity_recommended = centre_activity_recommended['ActivityTitle'].tolist()
            
            # TYPE 'SHOULD NOT SCHEDULE'
            ori_centre_activity_dislikes = centre_activity_dislikes['ActivityTitle'].tolist()
            dup_centre_activity_dislikes = []
            ori_activities_excluded_for_patient = activities_excluded_for_patient['ActivityTitle'].tolist()
            dup_activities_excluded_for_patient = []
            ori_activity_non_recommended = centre_activity_non_recommended['ActivityTitle'].tolist()
            dup_activity_non_recommended = []
            
            medication_schedule = {}
            medication_incorrect_schedule = {}
            week_start_datetime = medication_for_patient['StartDateTime'].min()
            week_end_datetime = medication_for_patient['EndDateTime'].max()
            schedule_start_datetime = weekly_schedule_for_patient['StartDate'].min()
            schedule_end_datetime = weekly_schedule_for_patient['EndDate'].max()
            # print(f"Medication start date: {week_start_datetime} | Medication end date: {week_end_datetime}")
            # print(f"Week start date: {week_start_datetime} | Week end date: {week_end_datetime}")
            
            # Assign NaT if week_end/start_datetime is NaN
            if pd.isna(week_end_datetime):
                week_end_datetime = pd.NaT
            if pd.isna(week_start_datetime):
                week_start_datetime = pd.NaT
            
            if week_end_datetime > schedule_end_datetime:
                week_end_datetime = schedule_end_datetime
                week_end_datetime -= datetime.timedelta(days=2) ## NOTE: MINUS 2 TO GET THE DATETIME FOR FRIDAY OF THE WEEK
            if week_start_datetime < schedule_start_datetime:
                week_start_datetime = schedule_start_datetime
            
            print(f"Schedule start date: {schedule_start_datetime} | Schedule end date: {schedule_end_datetime}")
            json_response[patientID]["Schedule start date"] = f"{schedule_start_datetime}"
            json_response[patientID]["Schedule end date"] = f"{schedule_end_datetime}"
            print(f"Preferred Activities: {dup_centre_activity_likes}")
            json_response[patientID]["Preferred Activities"] = dup_centre_activity_likes
            print(f"Non-Preferred Activities: {ori_centre_activity_dislikes}")
            json_response[patientID]["Non-Preferred Activities"] = ori_centre_activity_dislikes
            print(f"Activities Excluded: {ori_activities_excluded_for_patient}")
            json_response[patientID]["Activities Excluded"] = ori_activities_excluded_for_patient
            print(f"Routines: {dup_routine_for_patient}")
            json_response[patientID]["Routines"] = dup_routine_for_patient
            print(f"Doctor Recommended Activities: {dup_centre_activity_recommended}")
            json_response[patientID]["Doctor Recommended Activities"] = dup_centre_activity_recommended
            print(f"Doctor Non-Recommended Activities: {ori_activity_non_recommended}")
            json_response[patientID]["Doctor Non-Recommended Activities"] = ori_activity_non_recommended
            
            
            print(f"Medication Schedule:")
            json_response[patientID]["Medication Schedule"] = {}
            for date in date_range(week_start_datetime, week_end_datetime, request.app.state.config["DAYS"]):
                medication_schedule[date.weekday()] = []
                medication_incorrect_schedule[date.weekday()] = []
                json_response[patientID]["Medication Schedule"][days_of_week[date.weekday()]] = []
                
                print(f"\t {days_of_week[date.weekday()]}: ", end = '')
                for index, medication_row in medication_for_patient.iterrows():
                    if medication_row['StartDateTime'] <= date <= medication_row['EndDateTime']:
                        slots = medication_row['AdministerTime'].split(",")
                        for slot in slots:
                            if medication_row['Instruction'] is None or medication_row['Instruction'].strip() == "" or medication_row['Instruction'] in ["Nil", "nil" "-"]:
                                medication_schedule[date.weekday()].append(f"Give Medication@{slot}: {medication_row['PrescriptionName']}({medication_row['Dosage']})")
                                json_response[patientID]["Medication Schedule"][days_of_week[date.weekday()]].append(f"Give Medication@{slot}: {medication_row['PrescriptionName']}({medication_row['Dosage']})")
                            else:
                                medication_schedule[date.weekday()].append(f"Give Medication@{slot}: {medication_row['PrescriptionName']}({medication_row['Dosage']})**{medication_row['Instruction']}")
                                json_response[patientID]["Medication Schedule"][days_of_week[date.weekday()]].append(f"Give Medication@{slot}: {medication_row['PrescriptionName']}({medication_row['Dosage']})**{medication_row['Instruction']}")
                print(medication_schedule[date.weekday()])  
            
            # Custom sorting function to sort the medication schedules by time
            def sort_by_time(med_schedule):
                return int(med_schedule.split('@')[1].split(':')[0])

            # Sort the medication schedules for each day based on time
            for day, meds in medication_schedule.items():
                json_response[patientID]["Medication Schedule"][days_of_week[day]] = sorted(meds, key=sort_by_time) 
            
            print()
            
            
            for day in range(2, request.app.state.config["DAYS"]+2):
                print(f"{days_of_week[day-2]}: {row.iloc[day]}")
                json_response[patientID][f"{days_of_week[day-2]} Activities"] = row.iloc[day]
                
                activities_in_a_day = row.iloc[day].split("--")
                
                medications_to_give = []
                if (day-2) in medication_schedule:
                    medications_to_give = medication_schedule[(day-2)]
                
                for index, activity in enumerate(activities_in_a_day):
                    # TYPE 'SHOULD SCHEDULE'
                    # if the preferred activity/ recommended activities/ routine activities are in the activities_in_a_day, we remove that activity from the list
                    dup_centre_activity_likes = [item for item in dup_centre_activity_likes if item not in activity] 
                    dup_centre_activity_recommended = [item for item in dup_centre_activity_recommended if item not in activity] 
                    dup_routine_for_patient = [item for item in dup_routine_for_patient if item not in activity] 
                    
                    # TYPE 'SHOULD NOT SCHEDULE'                
                    # if the non-preferred activities/ non-recommended activities/ activities excluded are in the activities_in_a_day, we keep that activity in the list
                    dup_centre_activity_dislikes = [item for item in ori_centre_activity_dislikes if item in activity]
                    dup_activity_non_recommended = [item for item in ori_activity_non_recommended if item in activity]
                    dup_activities_excluded_for_patient = [item for item in ori_activities_excluded_for_patient if item in activity]
                    
                    # medication schedule check
                    if len(medications_to_give) != 0 and "Give Medication" in activity:
                        activity_name = activity.split(' | ')[0]
                        activity_count_dict[activity_name] += 1
                        
                        # print(f"Current activity: {activity}")
                        pattern = r'Give Medication@\d{4}: [^,]+'
                        matches = re.findall(pattern, activity)
                        for match in matches:
                            if match in medications_to_give:
                                medication_schedule[(day-2)].remove(match)
                            else:         
                                if medication_incorrect_schedule[(day-2)] is None:
                                    medication_incorrect_schedule[(day-2)] = []    
                                medication_incorrect_schedule[(day-2)].append(match)
                        # print(f"Current state of medication_schedule: {medication_schedule[(day-2)]}")
                    else:
                        activity_count_dict[activity] += 1
                    
            ## ========================= FOR TESTING CASES =========================
            
            # Test 1
            # dup_activities_excluded_for_patient = ["Mahjong", "Physiotherapy"]
            
            # Test 2
            # ori_activity_non_recommended = ["Mahjong", "Cutting"]
            # dup_centre_activity_likes = ["Mahjong","Cutting","Piano", "Dancing", "Cooking"]
            # ori_activities_excluded_for_patient = ["Mahjong", "Piano"]
            
            # Test 3
            # dup_centre_activity_dislikes = ["Mahjong"]
            # ori_centre_activity_recommended = ["Mahjong", "Cutting"]
            
            # Test 4
            # dup_centre_activity_recommended = ["Clip Coupons", "Cutting"]
            # ori_activities_excluded_for_patient = ["Clip Coupons", "Piano"]
            
            # Test 5
            # dup_activity_non_recommended = ["Clip Coupons"]
            
            # Test 6
            # dup_routine_for_patient = ["Sewing", "Piano"]
            # ori_activities_excluded_for_patient = ["Clip Coupons", "Piano", "Sewing"]
            
            # Test 7
            # medication_schedule[2] = ['Give Medication@0945: Galantamine(2 tabs)*']
            # medication_incorrect_schedule[2] = ['Give Medication@0930: Galantamine(2 puffs)']
            # medication_schedule[1] = ['Give Medication@0945: Galantamine(2 tabs)*']
            # medication_incorrect_schedule[1] = ['Give Medication@0930: Galantamine(2 puffs)']
            
            # =======================================================================
            
            ## INDIVIDUAL CHECKS 
            print(Fore.CYAN + "\nCHECKING TEST CASES" + Fore.RESET)
            
            
            # Test 1
            print("Test 1: Activities excluded are not scheduled ", end = '')
            json_response[patientID]["Test 1"] = {"Title" : "Activities excluded are not scheduled", "Result" : None, "Reason":[]}
            
            if len(dup_activities_excluded_for_patient) == 0:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 1"]["Result"] = "Passed"
            else:
                print(Fore.RED + f"(Failed)" + Fore.RESET)
                json_response[patientID]["Test 1"]["Result"] = "Failed"
                
                print(Fore.RED + f"\tThe following activities excluded are scheduled: {dup_activities_excluded_for_patient}" + Fore.RESET)
                json_response[patientID]["Test 1"]["Reason"].append(f"The following activities excluded are scheduled: {dup_activities_excluded_for_patient}")
                
                
            # Test 2
            print(f"Test 2: Patient preferred activities are scheduled ", end = '')
            json_response[patientID]["Test 2"] = {"Title" : "Patient preferred activities are scheduled", "Result" : None, "Reason":[]}
            
            if len(dup_centre_activity_likes) == 0:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 2"]["Result"] = "Passed"
            else:
                common_exclusion_and_preferred = list(set(ori_activities_excluded_for_patient) & set(dup_centre_activity_likes))
                common_non_recommended_and_preferred = list(set(ori_activity_non_recommended) & set(dup_centre_activity_likes))
                not_in_exclusion_or_non_recommended = list(set(dup_centre_activity_likes) - (set(ori_activities_excluded_for_patient) | set(ori_activity_non_recommended)))
                
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
                    
                    
            # Test 3        
            print(f"Test 3: Patient non-preferred activities are not scheduled ", end = '')
            json_response[patientID]["Test 3"] = {"Title" : "Patient non-preferred activities are not scheduled", "Result" : None, "Reason":[]}
            
            if len(dup_centre_activity_dislikes) == 0:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 3"]["Result"] = "Passed"
            else:
                common_recommended_and_non_preferred = list(set(ori_centre_activity_recommended) & set(dup_centre_activity_dislikes))
                not_in_recommended = list(set(dup_centre_activity_dislikes) - set(ori_centre_activity_recommended))
                
                if len(not_in_recommended) != 0:
                    print(Fore.RED + f"(Failed)" + Fore.RESET)
                    json_response[patientID]["Test 3"]["Result"] = "Failed"
                    
                    if len(common_recommended_and_non_preferred) != 0:
                        print(Fore.YELLOW + f"\t(Exception) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
                        json_response[patientID]["Test 3"]["Reason"].append(f"(Exception) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities")
                        
                    print(Fore.RED + f"\tThe following non-preferred activities are scheduled: {not_in_recommended}" + Fore.RESET)
                    json_response[patientID]["Test 3"]["Reason"].append(f"The following non-preferred activities are scheduled: {not_in_recommended}")
                    
                else:
                    print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                    json_response[patientID]["Test 3"]["Result"] = "Passed"
                    
                    if len(common_recommended_and_non_preferred) != 0:
                        print(Fore.YELLOW + f"\t(Exception) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
                        json_response[patientID]["Test 3"]["Reason"].append(f"(Exception) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities")
                    
                    
            # Test 4        
            print(f"Test 4: Doctor recommended activities are scheduled ", end = '')
            json_response[patientID]["Test 4"] = {"Title" : "Doctor recommended activities are scheduled", "Result" : None, "Reason":[]}
            
            if len(dup_centre_activity_recommended) == 0:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 4"]["Result"] = "Passed"
            else:
                common_excluded_and_recommended = list(set(ori_activities_excluded_for_patient) & set(dup_centre_activity_recommended))
                not_in_excluded = list(set(dup_centre_activity_recommended) - set(ori_activities_excluded_for_patient))
                
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
                    
                    
            # Test 5        
            print(f"Test 5: Doctor non-recommended activities are not scheduled ", end = '')
            json_response[patientID]["Test 5"] = {"Title" : "Doctor non-recommended activities are not scheduled", "Result" : None, "Reason":[]}

            if len(dup_activity_non_recommended) == 0:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 5"]["Result"] = "Passed"
            else:
                print(Fore.RED + f"(Failed)" + Fore.RESET)
                json_response[patientID]["Test 5"]["Result"] = "Failed"
                
                print(Fore.RED + f"\tThe following doctor non-recommended activities are scheduled: {dup_activity_non_recommended}" + Fore.RESET)
                json_response[patientID]["Test 5"]["Reason"].append(f"The following doctor non-recommended activities are scheduled: {dup_activity_non_recommended}")
                
                
            # Test 6    
            print(f"Test 6: Patient routines are scheduled ", end = '')
            json_response[patientID]["Test 6"] = {"Title" : "Patient routines are scheduled", "Result" : None, "Reason":[]}
            
            if len(dup_routine_for_patient) == 0:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 6"]["Result"] = "Passed"
            else:
                common_excluded_and_routines = list(set(ori_activities_excluded_for_patient) & set(dup_routine_for_patient))
                not_in_excluded = list(set(dup_routine_for_patient) - set(ori_activities_excluded_for_patient))
                
                if len(not_in_excluded) != 0:
                    print(Fore.RED + f"(Failed)" + Fore.RESET)
                    json_response[patientID]["Test 6"]["Result"] = "Failed"
                    
                    if len(common_excluded_and_routines) != 0:
                        print(Fore.YELLOW + f"\t(Exception) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                        json_response[patientID]["Test 6"]["Reason"].append(f"(Exception) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded")
                        
                    print(Fore.RED + f"\tThe following routines are not scheduled: {not_in_excluded}" + Fore.RESET)
                    json_response[patientID]["Test 6"]["Reason"].append(f"The following routines are not scheduled: {not_in_excluded}")
                else:
                    print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                    json_response[patientID]["Test 6"]["Result"] = "Passed"
                    
                    if len(common_excluded_and_routines) != 0:
                        print(Fore.YELLOW + f"\t(Exception) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                        json_response[patientID]["Test 6"]["Reason"].append(f"(Exception) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded")
                
                
            # Test 7  
            print(f"Test 7: All medications are administered correctly ", end = '')
            json_response[patientID]["Test 7"] = {"Title" : "All medications are administered correctly", "Result" : None, "Reason":{}}
            
            correct_medications_scheduled = True
            for day, correct_medications in medication_schedule.items():
                if len(correct_medications) != 0:
                    correct_medications_scheduled = False
                    print(Fore.RED + f"(Failed)" + Fore.RESET)
                    json_response[patientID]["Test 7"]["Result"] = "Failed"
                    
                    print(Fore.RED + f"\tFor {days_of_week[day]}:")
                    json_response[patientID]["Test 7"]["Reason"][f"{days_of_week[day]}"] = []
                    
                    print(Fore.RED + f"\t(Incorrect) The following medications were scheduled incorrectly: {medication_incorrect_schedule[day]}" + Fore.RESET)
                    json_response[patientID]["Test 7"]["Reason"][f"{days_of_week[day]}"].append(f"(Incorrect) The following medications were scheduled incorrectly: {medication_incorrect_schedule[day]}")
                    
                    print(Fore.YELLOW + f"\t(Correct) The medications that are supposed to be scheduled are: {medication_schedule[day]}" + Fore.RESET)   
                    json_response[patientID]["Test 7"]["Reason"][f"{days_of_week[day]}"].append(f"(Correct) The medications that are supposed to be scheduled are: {medication_schedule[day]}")            
            if correct_medications_scheduled:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 7"]["Result"] = "Passed"
                
            print()
            
            ## PATIENT REPORT
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
                
            group_activity_count = sum(activity_count_dict.get(activity, 0) for activity in activitiesAndCentreActivityViewDF.loc[activitiesAndCentreActivityViewDF['IsGroup'] == 1, 'ActivityTitle'])
            json_response[patientID]["Group Activities Count"] = group_activity_count
            
            solo_activity_count = sum(activity_count_dict.get(activity, 0) for activity in activitiesAndCentreActivityViewDF.loc[activitiesAndCentreActivityViewDF['IsGroup'] == 0, 'ActivityTitle'])
            json_response[patientID]["Solo Activities Count"] = solo_activity_count
            
            print()
            print(f"Number of group activities: {group_activity_count}")
            print(f"Number of solo-group activities: {solo_activity_count}")
            
            print()
            print()
            
        # json_response = json.dumps(json_response, sort_keys=False, indent=2)   
        # return Response(json_response, mimetype='application/json', status=200)
        responseData = {"Status": "200", "Message": "Tester Ran Successfully", "Data": json_response} 
        return JSONResponse(jsonable_encoder(responseData))
    
    except Exception as e:
        logger.exception(f"Error occurred when conducting patientTest: {e}")
        responseData = {"Status": "400", "Message": "Patient Test Error", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))


@router.api_route("/adhoc/", methods=["PUT"])
def adhoc_change_schedule(request: Request, data: AdHocRequest):
    # find original activity name
    originalDF = ActivityNameView.get_data(arg1=data.OldActivityID)
    if len(originalDF) == 0: # invalid activity
        responseData = {"Status": "400", "Message": "Invalid old activity ID", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))
        

    oldActivityName = originalDF["ActivityTitle"].iloc[0]

    # find new activity name
    newDF = ActivityNameView.get_data(arg1=data.NewActivityID)
    if len(newDF) == 0: # invalid activity
        responseData = {"Status": "400", "Message": "Invalid new activity ID", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))

    newActivityName = newDF["ActivityTitle"].iloc[0]

    # Get schedule
    adHocDF = AdHocScheduleView.get_data(arg1=data.PatientID)
    if len(adHocDF.index) == 0:
        responseData = {"Status": "404", "Message": "Patient Schedule not found/generated", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))
    
    scheduleStartDate = adHocDF["StartDate"].iloc[0]
    scheduleEndDate = adHocDF["EndDate"].iloc[0]

    if not isWithinDateRange(data.StartDate, scheduleStartDate, scheduleEndDate) or not isWithinDateRange(data.EndDate, scheduleStartDate, scheduleEndDate):
        responseData = {"Status": "400", "Message": "Invalid start date or end date", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))


    chosenDays = getDaysFromDates(data.StartDate, data.EndDate, request.app.state.config["DAY_OF_WEEK_ORDER"])

    filteredAdHocDF = adHocDF[[c for c in adHocDF.columns if c in chosenDays + ["ScheduleID"]]]
    
    # replace activities
    isSuccess = replaceActivitiesInSchedule(filteredAdHocDF, oldActivityName, newActivityName, chosenDays)
    if not isSuccess:
        responseData = {"Status": "400", "Message": f"{oldActivityName} (old activity) cannnot be found in some/all days of patient schedule for {data.StartDate.split('T')[0]} to {data.EndDate.split('T')[0]}", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))
                
    
    # Update db
    db_tables: DBTABLES = request.app.state.config["DB_TABLES"]
    schedule_table = DB.schema.tables[db_tables.SCHEDULE_TABLE]
    responseData = ScheduleWriter.updateDB(schedule_table, filteredAdHocDF, chosenDays)
    
    return JSONResponse(jsonable_encoder(responseData))



@router.api_route("/refresh/", methods=["GET"])
def refresh_schedules():
    ScheduleRefresher.refresh_schedules()

    return PlainTextResponse("Successfully updated schedules", status=200)


@router.api_route("/systemTest/", methods=["GET"])
async def system_report(request: Request): 
    
    systemTestArray = []
    statisticsArray = []
    warningArray = []

    weeklyScheduleViewDF = WeeklyScheduleView.get_data()
    compulsoryActivitiesDF = CompulsoryActivitiesOnlyView.get_data()
    patientsDF = PatientsOnlyView.get_data()
    activitiesDF = AllActivitiesView.get_data()
    groupActivitiesDF = GroupActivitiesOnlyView.get_data()
    validRoutinesDF = ValidRoutineActivitiesView.get_data()

    if len(weeklyScheduleViewDF) == 0:
        responseData = {"Status": "404", "Message": "No schedule for the week found", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))
    

    # 1. All patient weekly schedule is generated"
    systemTestArray.append(allPatientScheduleGeneratedSystemTest(weeklyScheduleViewDF, patientsDF))

    # 2. All compulsory activities are scheduled at correct time slots  
    systemTestArray.append(allCompulsoryActivitiesAtCorrectSlotSystemTest(weeklyScheduleViewDF, compulsoryActivitiesDF, request))

    # 3. Only centre activities "not expired" are scheduled
    systemTestArray.append(nonExpiredCentreActivitiesSystemTest(activitiesDF, weeklyScheduleViewDF))

    # 4. Fixed time centre activities are scheduled in the correct timeslot (fixed and routine activities)
    systemTestArray.append(fixedActivitiesScheduledCorrectlySystemTest(activitiesDF, validRoutinesDF, weeklyScheduleViewDF, request))

    # 5. Group activities meet the minimum number of people   
    systemTestArray.append(groupActivitiesMinSizeSystemTest(groupActivitiesDF, weeklyScheduleViewDF))

    # 6. Group activities are scheduled in the correct timeslot
    
    systemTestArray.append(groupActivitiesCorrectTimeslotSystemTest(groupActivitiesDF, weeklyScheduleViewDF, request))

    # statistics
    statsResult, minActivities, maxActivities = systemLevelStatistics(activitiesDF, weeklyScheduleViewDF)

    statisticsArray.append({"statsName": "Number of patients scheduled per activity", "statsResult": statsResult})
    statisticsArray.append({"statsName": "Most scheduled activities", "statsResult": [activity for activity in maxActivities]})
    statisticsArray.append({"statsName": "Least scheduled activities", "statsResult": [activity for activity in minActivities]})
    
    # warnings
    warningArray.append(clashInFixedTimeSlotWarning(activitiesDF, validRoutinesDF, request))

    responseData = {"Status": "200", "Message": "System Report Generated", "Data": {"SystemTest": systemTestArray, "Statistics": statisticsArray, "Warnings": warningArray}} 
    return JSONResponse(jsonable_encoder(responseData))


            



