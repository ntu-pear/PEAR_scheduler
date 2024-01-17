from flask import Blueprint, jsonify, current_app, request, Response
from pear_schedule.db_views.views import PatientsOnlyView, ValidRoutineActivitiesView, ActivityNameView, AdHocScheduleView, ExistingScheduleView, WeeklyScheduleView, CentreActivityPreferenceView, CentreActivityRecommendationView, ActivitiesExcludedView, RoutineView, MedicationTesterView, ActivityAndCentreActivityView
import pandas as pd
import re
import json

from pear_schedule.db import DB
from sqlalchemy.orm import Session
from sqlalchemy import Select, Table, select
import datetime

from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
from pear_schedule.scheduler.individualScheduling import IndividualActivityScheduler
from pear_schedule.scheduler.medicationScheduling import medicationScheduler
from pear_schedule.scheduler.routineScheduling import RoutineActivityScheduler
from utils import DBTABLES

from colorama import init, Fore

init(autoreset=True)


blueprint = Blueprint("scheduling", __name__)


@blueprint.route("/generate", methods=["GET"])
def generate_schedule():
    config = current_app.config
    
    # Set up patient schedule structure
    patientSchedules = {} # patient id: [[],[],[],[],[]]

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
            print(f"FOR PATIENT {p}")
            
            for day, activities in enumerate(slots):
                if day == 0:
                    print(f"\t Monday: ")
                elif day == 1:
                    print(f"\t Tuesday: ")
                elif day == 2:
                    print(f"\t Wednesday: ")
                elif day == 3:
                    print(f"\t Thursday: ")
                elif day == 4:
                    print(f"\t Friday: ")
                
                for index, hour in enumerate(activities):
                    print(f"\t\t {index}: {hour}")
            
            print("==============================================")
    
    ## ------------------------------------------------------------------------------------------------
    # COMMENT THE FOLLOWING IF YOU DO NOT WANT TO INSERT INTO SCHEDULE TABLE
    # Inserting into Schedule Table
    session = Session(bind=DB.engine)
    
    # Reflect the database tables
    schedule_table = Table('Schedule', DB.schema, autoload=True, autoload_with= DB.engine)
        
    today = datetime.datetime.now()
    start_of_week = today - datetime.timedelta(days=today.weekday(), hours=0, minutes=0, seconds=0, microseconds=0)  # Monday -> 00:00:00
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=0)  # Sunday -> 23:59:59
    
    try:
        for p, slots in patientSchedules.items():
            
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
            converted_schedule = {}
            
            # check if have existing schedule
            existingScheduleDF = ExistingScheduleView.get_data(start_of_week, p)
            if len(existingScheduleDF) > 0: 
                continue   
                # check_counter = 0
                # for i, day in enumerate(days):
                #     activities = "--".join(['Free and Easy' if activity == '' else activity for activity in slots[i]])
                #     converted_schedule[day] = activities
                #     if existingScheduleDF[day].tolist() == activities: # if the existing schedule activities are the same as the new activities created -> increment counter by 1
                #         check_counter += 1
                # if check_counter == 5:
                #     continue
            for i, day in enumerate(days):
                activities = "--".join(['Free and Easy' if activity == '' else activity for activity in slots[i]])
                converted_schedule[day] = activities
                
            schedule_data = {
                ## "ScheduleID": _ (not necessary as it is a primary key which will automatically be created)
                "PatientID": p,
                "StartDate": start_of_week,
                "EndDate": end_of_week,
                "Monday": converted_schedule["Monday"],
                "Tuesday": converted_schedule["Tuesday"],
                "Wednesday": converted_schedule["Wednesday"],
                "Thursday": converted_schedule["Thursday"],
                "Friday": converted_schedule["Friday"],
                "Saturday": "",
                "Sunday": "",
                "IsDeleted": 0, ## Mandatory Field 
                "CreatedDateTime": today, ## Mandatory Field 
                "UpdatedDateTime": today ## Mandatory Field 
            }
            
            # Use the add method to add data to the session
            schedule_instance = schedule_table.insert().values(schedule_data)
            session.execute(schedule_instance)
            
            # Commit the changes to the database
            session.commit()
            
    except Exception as e:
        session.rollback()
        print(f"Error occurred when inserting \n{e}Data attempted: \n{schedule_data}")
        
    # Close the session
    session.close()
    ## ------------------------------------------------------------------------------------------------
    
    return Response(
        "Generated Schedule Successfully",
        status=200,
    ) 


@blueprint.route("/test", methods=["GET"])
def test_schedule():
    
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
        ori_centre_activity_likes = centre_activity_likes['ActivityTitle'].tolist()
        dup_centre_activity_likes = centre_activity_likes['ActivityTitle'].tolist()
        
        ori_centre_activity_dislikes = centre_activity_dislikes['ActivityTitle'].tolist()
        dup_centre_activity_dislikes = []
        
        ori_activities_excluded_for_patient = activities_excluded_for_patient['ActivityTitle'].tolist()
        dup_activities_excluded_for_patient = []
        
        ori_routine_for_patient = routine_for_patient['ActivityTitle'].tolist()
        dup_routine_for_patient = routine_for_patient['ActivityTitle'].tolist()
        
        ori_centre_activity_recommended = centre_activity_recommended['ActivityTitle'].tolist()
        dup_centre_activity_recommended = centre_activity_recommended['ActivityTitle'].tolist()
        
        ori_activity_non_recommended = centre_activity_non_recommended['ActivityTitle'].tolist()
        dup_activity_non_recommended = []
        
        medication_schedule = {}
        medication_incorrect_schedule = {}
        week_start_datetime = medication_for_patient['StartDateTime'].min()
        week_end_datetime = medication_for_patient['EndDateTime'].max()
        schedule_start_datetime = weekly_schedule_for_patient['StartDate'].min()
        schedule_end_datetime = weekly_schedule_for_patient['EndDate'].max()
        # print(f"Medication start date: {week_start_datetime} | Medication end date: {week_end_datetime}")
        
        if week_end_datetime > schedule_end_datetime:
            week_end_datetime = schedule_end_datetime
            week_end_datetime -= datetime.timedelta(days=2) ## NOTE: MINUS 2 TO GET THE DATETIME FOR FRIDAY OF THE WEEK
        if week_start_datetime < schedule_start_datetime:
            week_start_datetime = schedule_start_datetime
        
        # print(f"Week start date: {week_start_datetime} | Week end date: {week_end_datetime}")
        def date_range(start_date, end_date):
            current_date = start_date
            while current_date <= end_date:
                yield current_date
                current_date += datetime.timedelta(days=1)
        
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
        for date in date_range(week_start_datetime, week_end_datetime):
            medication_schedule[date.weekday()] = []
            json_response[patientID]["Medication Schedule"][days_of_week[date.weekday()]] = []
            
            print(f"\t {days_of_week[date.weekday()]}: ", end = '')
            for index, medication_row in medication_for_patient.iterrows():
                if medication_row['StartDateTime'] <= date <= medication_row['EndDateTime']:
                    slots = medication_row['AdministerTime'].split(",")
                    for slot in slots:
                        medication_schedule[date.weekday()].append(f"Give Medication@{slot}: {medication_row['PrescriptionName']}({medication_row['Dosage']})")
                        json_response[patientID]["Medication Schedule"][days_of_week[date.weekday()]].append(f"Give Medication@{slot}: {medication_row['PrescriptionName']}({medication_row['Dosage']})")
            print(medication_schedule[date.weekday()])            
            
        print()
        
        
        for day in range(2,7):
            print(f"{days_of_week[day-2]}: {row.iloc[day]}")
            json_response[patientID][f"{days_of_week[day-2]} Activities"] = row.iloc[day]
            
            activities_in_a_day = row.iloc[day].split("--")
            
            if (day-2) in medication_schedule:
                medications_to_give = medication_schedule[(day-2)]
            
            for index, activity in enumerate(activities_in_a_day):
                # if the preferred activity/ recommended activities/ routine activities are in the activities_in_a_day, we remove that activity from the list
                dup_centre_activity_likes = [item for item in dup_centre_activity_likes if item not in activity] 
                dup_centre_activity_recommended = [item for item in dup_centre_activity_recommended if item not in activity] 
                dup_routine_for_patient = [item for item in dup_routine_for_patient if item not in activity] 
                
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
        # dup_centre_activity_likes = ["Mahjong","Cutting","Dancing","Piano", "Killing"]
        # ori_activities_excluded_for_patient = ["Dancing", "Piano"]
        
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
        # medication_schedule[2] = ['Give Medication@0945: Galantamine(2 tabs)']
        # medication_incorrect_schedule[2] = ['Give Medication@0930: Galantamine(2 puffs)']
        
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
                    print(Fore.YELLOW + f"\t{common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                    json_response[patientID]["Test 2"]["Reason"].append(f"{common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded")
                    
                if len(common_non_recommended_and_preferred) != 0:
                    print(Fore.YELLOW + f"\t{common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities" + Fore.RESET)
                    json_response[patientID]["Test 2"]["Reason"].append(f"{common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities")
                    
                print(Fore.RED + f"\tThe following preferred activities are not scheduled: {not_in_exclusion_or_non_recommended}" + Fore.RESET)
                json_response[patientID]["Test 2"]["Reason"].append(f"The following preferred activities are not scheduled: {not_in_exclusion_or_non_recommended}")
            else:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 2"]["Result"] = "Passed"
                
                if len(common_exclusion_and_preferred) != 0:
                    print(Fore.YELLOW + f"\t(Warning) {common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                    json_response[patientID]["Test 2"]["Reason"].append(f"(Warning) {common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded")
                    
                if len(common_non_recommended_and_preferred) != 0:
                    print(Fore.YELLOW + f"\t(Warning) {common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities" + Fore.RESET)
                    json_response[patientID]["Test 2"]["Reason"].append(f"(Warning) {common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities")
                
                
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
                    print(Fore.YELLOW + f"\t{common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
                    json_response[patientID]["Test 3"]["Reason"].append(f"{common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities")
                    
                print(Fore.RED + f"\tThe following non-preferred activities are scheduled: {not_in_recommended}" + Fore.RESET)
                json_response[patientID]["Test 3"]["Reason"].append(f"The following non-preferred activities are scheduled: {not_in_recommended}")
                
            else:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 3"]["Result"] = "Passed"
                
                if len(common_recommended_and_non_preferred) != 0:
                    print(Fore.YELLOW + f"\t(Warning) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
                    json_response[patientID]["Test 3"]["Reason"].append(f"(Warning) {common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities")
                
                
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
                    print(Fore.YELLOW + f"\t{common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded"  + Fore.RESET)
                    json_response[patientID]["Test 4"]["Reason"].append(f"{common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded")
                    
                print(Fore.RED + f"\tThe following doctor recommended activities are not scheduled: {not_in_excluded}" + Fore.RESET)
                json_response[patientID]["Test 4"]["Reason"].append(f"The following doctor recommended activities are not scheduled: {not_in_excluded}")
            else:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 4"]["Result"] = "Passed"
                
                if len(common_excluded_and_recommended) != 0:
                    print(Fore.YELLOW + f"\t(Warning) {common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded"  + Fore.RESET)
                    json_response[patientID]["Test 4"]["Reason"].append(f"(Warning) {common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded")
                
                
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
                    print(Fore.YELLOW + f"\t{common_excluded_and_routines} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                    json_response[patientID]["Test 6"]["Reason"].append(f"{common_excluded_and_routines} are not scheduled because there are part of Activities Excluded")
                    
                print(Fore.RED + f"\tThe following routines are not scheduled: {not_in_excluded}" + Fore.RESET)
                json_response[patientID]["Test 6"]["Reason"].append(f"The following routines are not scheduled: {not_in_excluded}")
            else:
                print(Fore.GREEN + f"(Passed)" + Fore.RESET)
                json_response[patientID]["Test 6"]["Result"] = "Passed"
                
                if len(common_excluded_and_routines) != 0:
                    print(Fore.YELLOW + f"\t(Warning) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                    json_response[patientID]["Test 6"]["Reason"].append(f"(Warning) {common_excluded_and_routines} are not scheduled because there are part of Activities Excluded")
            
            
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
                
                print(Fore.RED + f"\tThe following medications were scheduled incorrectly: {medication_incorrect_schedule[day]}" + Fore.RESET)
                json_response[patientID]["Test 7"]["Reason"][f"{days_of_week[day]}"].append(f"The following medications were scheduled incorrectly: {medication_incorrect_schedule[day]}")
                
                print(Fore.YELLOW + f"\tThe medications that are supposed to be scheduled are: {medication_incorrect_schedule[day]}" + Fore.RESET)   
                json_response[patientID]["Test 7"]["Reason"][f"{days_of_week[day]}"].append(f"The medications that are supposed to be scheduled are: {medication_incorrect_schedule[day]}")            
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
        
    json_response = json.dumps(json_response, sort_keys=False, indent=2)   
    return Response(json_response, mimetype='application/json')


@blueprint.route("/adhoc", methods=["PUT"])
def adhoc_change_schedule():
    # example request body = {
    #     "originalActivityID": 0,
    #     "newActivityID": 1,
    #     "patientIDList": [1,3], (if empty means replace for all patients)
    #     "dayList": ["Monday", "Tuesday"], (if empty means replace for all days)
    # }

    data = request.get_json()

    # check request body
    errorRes = checkRequestBody(data)
    if errorRes != None:
        return errorRes
    
    # find original activity name
    originalDF = ActivityNameView.get_data(data["originalActivityID"])
    if len(originalDF) == 0: # invalid activity
        return Response(
            "Invalid original activity ID",
            status=400,
        )

    originalActivityName = originalDF["ActivityTitle"].iloc[0]

    # find new activity name
    newDF = ActivityNameView.get_data(data["newActivityID"])
    if len(newDF) == 0: # invalid activity
        return Response(
            "Invalid new activity ID",
            status=400,
        )

    newActivityName = newDF["ActivityTitle"].iloc[0]

    adHocDF = AdHocScheduleView.get_data(data["patientIDList"])
    chosenDays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    if len(data["dayList"]) != 0:
        chosenDays = data["dayList"]

    filteredAdHocDF = adHocDF[[c for c in adHocDF.columns if c in chosenDays + ["ScheduleID"]]]
    
    # replace activities
    for i, record in filteredAdHocDF.iterrows():
        for col in chosenDays:
            originalSchedule = record[col]
            if originalSchedule != "":
                newSchedule = originalSchedule.replace(originalActivityName, newActivityName)
                filteredAdHocDF.at[i,col] = newSchedule

    # Start transaction
    session = Session(bind=DB.engine)
    # Reflect the database tables
    schedule_table = Table('Schedule', DB.schema, autoload=True, autoload_with= DB.engine)
    today = datetime.datetime.now()

    try:

        for i, record in filteredAdHocDF.iterrows():
            schedule_data = {
                "UpdatedDateTime": today
            }
            for col in chosenDays:
                schedule_data[col] = record[col]

            schedule_instance = schedule_table.update().values(schedule_data).where(schedule_table.c["ScheduleID"] == record["ScheduleID"])
            session.execute(schedule_instance)

        # Commit the changes to the database
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Error occurred when inserting \n{e}\nData attempted: \n{schedule_data}")
        return Response(
            "Schedule update error. Check Logs",
            status=500,
        )
            
    return Response(
        "Updated Schedule Successfully",
        status=200,
    )


@blueprint.route("/test2", methods=["GET"])
def test2():
    routineActivitiesDF = ValidRoutineActivitiesView.get_data()
    # x = GroupActivitiesRecommendationView.get_data()
    # preferredDF = groupPreferenceDF.query(f"CentreActivityID == 4 and IsLike == 1")
    
    # for id in preferredDF["PatientID"]:
    #     print(id)
    
    print(routineActivitiesDF)

    data = {"data": "Hello test2"} 
    return jsonify(data) 


def checkRequestBody(data):
    if "originalActivityID" not in data or "newActivityID" not in data or "patientIDList" not in data or "dayList" not in data:
        
        return Response(
            "Invalid Request Body",
            status = 400
        )
    
    if not isinstance(data["originalActivityID"], int) or not isinstance(data["newActivityID"], int):
        
        return Response(
            "Invalid Request Body",
            status = 400
        )
    
    if not isinstance(data["patientIDList"], list) or not isinstance(data["dayList"], list):
        
        return Response(
            "Invalid Request Body",
            status = 400
        )
    

    for val in data["patientIDList"]:
        if not isinstance(val, int):
            return Response(
                "Invalid Request Body",
                status = 400
            )
    
    days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"}
    for val in data["dayList"]:
        if val not in days:
            return Response(
                "Invalid Request Body",
                status = 400
            )

    return None