from flask import Blueprint, jsonify, current_app, request, Response
from pear_schedule.db_views.views import PatientsOnlyView, ValidRoutineActivitiesView, ActivityNameView, AdHocScheduleView, ExistingScheduleView, WeeklyScheduleView, CentreActivityPreferenceView, CentreActivityRecommendationView, ActivitiesExcludedView, RoutineView, MedicationView
import pandas as pd

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
    start_of_week = today - datetime.timedelta(days=today.weekday(), hours=0, minutes=0, seconds=0)  # Monday -> 00:00:00
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0)
    end_of_week = start_of_week + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)  # Sunday -> 23:59:59
    
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
        print(f"Error occurred when inserting \n{e}\nData attempted: \n{schedule_data}")
        
    # Close the session
    session.close()
    ## ------------------------------------------------------------------------------------------------
    
    return Response(
        "Generated Schedule Successfully",
        status=200,
    ) 


@blueprint.route("/test", methods=["GET"])
def test_schedule():
    
    weeklyScheduleViewDF = WeeklyScheduleView.get_data()
    centreActivityPreferenceViewDF = CentreActivityPreferenceView.get_data()
    centreActivityRecommendationViewDF = CentreActivityRecommendationView.get_data()
    activitiesExcludedViewDF = ActivitiesExcludedView.get_data()
    routineViewDF = RoutineView.get_data()
    medicationViewDF = MedicationView.get_data()
    
    for index, row, in weeklyScheduleViewDF.iterrows():
        print(f"=========================================== Checking patient {row['PatientID']} schedule now ===========================================")
        
        centre_activity_preference_for_patient = centreActivityPreferenceViewDF.loc[centreActivityPreferenceViewDF['PatientID'] == row['PatientID']]
        centre_activity_recommendation_for_patient = centreActivityRecommendationViewDF.loc[centreActivityRecommendationViewDF['PatientID'] == row['PatientID']]
        activities_excluded_for_patient = activitiesExcludedViewDF.loc[activitiesExcludedViewDF['PatientID'] == row['PatientID']]
        routine_for_patient = routineViewDF.loc[(routineViewDF['PatientID'] == row['PatientID']) & routineViewDF["IncludeInSchedule"]]
        medication_for_patient = medicationViewDF.loc[medicationViewDF['PatientID'] == row['PatientID']]
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
        
        ori_medication_for_patient = medication_for_patient['PrescriptionName'].tolist()
        dup_medication_for_patient = medication_for_patient['PrescriptionName'].tolist()
        
        print(f"Preferred Activities: {dup_centre_activity_likes}")
        print(f"Non-Preferred Activities: {ori_centre_activity_dislikes}")
        print(f"Activities Excluded: {ori_activities_excluded_for_patient}")
        print(f"Routines: {dup_routine_for_patient}")
        print(f"Doctor Recommended Activities: {dup_centre_activity_recommended}")
        print(f"Doctor Non-Recommended Activities: {ori_activity_non_recommended}")
        print(f"Medication: {dup_medication_for_patient}")
        print()
        
        
        for day in range(2,7):
            print(f"Activities in the week: {row.iloc[day]}")
            
            activities_in_a_day = row.iloc[day].split("--")
            
            for activity in activities_in_a_day:
                # if the preferred activity/ recommended activities/ routine activities are in the activities_in_a_day, we remove that activity from the list
                dup_centre_activity_likes = [item for item in dup_centre_activity_likes if item not in activity] 
                dup_centre_activity_recommended = [item for item in dup_centre_activity_recommended if item not in activity] 
                dup_routine_for_patient = [item for item in dup_routine_for_patient if item not in activity] 
                
                # if the non-preferred activities/ non-recommended activities/ activities excluded are in the activities_in_a_day, we keep that activity in the list
                dup_centre_activity_dislikes = [item for item in ori_centre_activity_dislikes if item in activity]
                dup_activity_non_recommended = [item for item in ori_activity_non_recommended if item in activity]
                dup_activities_excluded_for_patient = [item for item in ori_activities_excluded_for_patient if item in activity]
                
        ## ========================= FOR TESTING CASES =========================
        
        # Test 1
        # ori_activity_non_recommended = ["Mahjong", "Cutting"]
        # dup_centre_activity_likes = ["Mahjong","Cutting","Dancing","Piano", "Killing"]
        # ori_activities_excluded_for_patient = ["Dancing", "Piano"]
        
        # Test 2
        # dup_centre_activity_dislikes = ["Mahjong"]
        # ori_centre_activity_recommended = ["Mahjong", "Cutting"]
        
        # Test 3
        # dup_centre_activity_recommended = ["Clip Coupons", "Cutting"]
        # ori_activities_excluded_for_patient = ["Clip Coupons", "Piano"]
        
        # Test 5
        # dup_activity_non_recommended = ["Clip Coupons"]
        
        # =======================================================================
        
        ## INDIVIDUAL CHECKS 
        print("\nCHECKING IN PROGRESS")
        
        print(f"Test 1: Patient preferred activities are scheduled ", end = '')
        if len(dup_centre_activity_likes) == 0:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        else:
            common_exclusion_and_preferred = list(set(ori_activities_excluded_for_patient) & set(dup_centre_activity_likes))
            common_non_recommended_and_preferred = list(set(ori_activity_non_recommended) & set(dup_centre_activity_likes))
            not_in_exclusion_or_non_recommended = list(set(dup_centre_activity_likes) - (set(ori_activities_excluded_for_patient) | set(ori_activity_non_recommended)))
            
            if len(not_in_exclusion_or_non_recommended) != 0:
                print(Fore.RED + f"(Failed)" + Fore.RESET)
                if len(common_exclusion_and_preferred) != 0:
                    print(Fore.YELLOW + f"\t{common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                if len(common_non_recommended_and_preferred) != 0:
                    print(Fore.YELLOW + f"\t{common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities" + Fore.RESET)
                print(Fore.RED + f"\tThe following preferred activities are not scheduled: {not_in_exclusion_or_non_recommended}" + Fore.RESET)
            else:
                print(Fore.YELLOW + f"(Warning)" + Fore.RESET)
                if len(common_exclusion_and_preferred) != 0:
                    print(Fore.YELLOW + f"\t{common_exclusion_and_preferred} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
                if len(common_non_recommended_and_preferred) != 0:
                    print(Fore.YELLOW + f"\t{common_non_recommended_and_preferred} are not scheduled because there are part of Doctor Non-Recommended Activities" + Fore.RESET)
                
            # if any(item in ori_activities_excluded_for_patient for item in dup_centre_activity_likes):
            #     common_elements = list(set(ori_activities_excluded_for_patient) & set(dup_centre_activity_likes))
            #     if len(common_elements) == len(dup_centre_activity_likes): # all NOT SCHEDULED preferred activities are part of activities excluded
            #         print(Fore.YELLOW + f"(Warning)" + Fore.RESET)
            #         print(Fore.YELLOW + f"\t{dup_centre_activity_likes} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
            #     else: # there are some preferred activities that are NOT IN activities excluded BUT ARE NOT scheduled
            #         print(Fore.RED + f"(Failed)" + Fore.RESET)
            #         print(Fore.RED + f"\t{common_elements} are not scheduled because there are part of Activities Excluded" + Fore.RESET)
            #         print(Fore.RED + f"\tHowever, {[item for item in dup_centre_activity_likes if item not in common_elements]} are not Activities Excluded but are still not scheduled" + Fore.RESET)
            # elif any(item in ori_activity_non_recommended for item in dup_centre_activity_likes):
            #     common_elements = list(set(ori_activity_non_recommended) & set(dup_centre_activity_likes))
            #     if len(common_elements) == len(dup_centre_activity_likes): # all NOT SCHEDULED preferred activities are part of doctor non-recommended activities
            #         print(Fore.YELLOW + f"(Warning)" + Fore.RESET)
            #         print(Fore.YELLOW + f"\t{dup_centre_activity_likes} are not scheduled because there are Doctor Non-Recommendation Activities" + Fore.RESET)
            #     else: # there are some preferred activities that are NOT IN doctor non-recommended activities BUT ARE NOT scheduled
            #         print(Fore.RED + f"(Failed)" + Fore.RESET)
            #         print(Fore.RED + f"\t{common_elements} are not scheduled because there are part of Doctor Non-Recommended Activities" + Fore.RESET)
            #         print(Fore.RED + f"\tHowever, {[item for item in dup_centre_activity_likes if item not in common_elements]} are not Doctor Non-Recommended Activities but are still not scheduled" + Fore.RESET)
            # else:
            #     print(Fore.RED + f"(Failed)" + Fore.RESET)
            #     print(Fore.RED + f"\tThe following preferred activities are not scheduled: {dup_centre_activity_likes}" + Fore.RESET)
                
                
        print(f"Test 2: Patient non-preferred activities are not scheduled ", end = '')
        if len(dup_centre_activity_dislikes) == 0:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        else:
            common_recommended_and_non_preferred = list(set(ori_centre_activity_recommended) & set(dup_centre_activity_dislikes))
            not_in_recommended = list(set(dup_centre_activity_dislikes) - set(ori_centre_activity_recommended))
            
            if len(not_in_recommended) != 0:
                print(Fore.RED + f"(Failed)" + Fore.RESET)
                if len(common_recommended_and_non_preferred) != 0:
                    print(Fore.YELLOW + f"\t{common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
                print(Fore.RED + f"\tThe following non-preferred activities are scheduled: {not_in_recommended}" + Fore.RESET)
            else:
                print(Fore.YELLOW + f"(Warning)" + Fore.RESET)
                if len(common_recommended_and_non_preferred) != 0:
                    print(Fore.YELLOW + f"\t{common_recommended_and_non_preferred} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
                
            # if any(item in ori_centre_activity_recommended for item in dup_centre_activity_dislikes):
            #     common_elements = list(set(ori_centre_activity_recommended) & set(dup_centre_activity_dislikes))
            #     if len(common_elements) == len(dup_centre_activity_dislikes): # all non-preferred activities are part of doctor recommended activities
            #         print(Fore.YELLOW + f"(Warning)" + Fore.RESET)
            #         print(Fore.YELLOW + f"\t{common_elements} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
            #     else: # there are some non-preferred activities that are NOT IN doctor recommended activities BUT ARE SCHEDULED
            #         print(Fore.RED + f"(Failed)" + Fore.RESET)
            #         print(Fore.RED + f"\t{common_elements} are scheduled because there are part of Doctor Recommended Activities" + Fore.RESET)
            #         print(Fore.RED + f"\tHowever, {[item for item in dup_centre_activity_dislikes if item not in common_elements]} are not Doctor Recommended Activities but are still scheduled" + Fore.RESET)
            # else:   
            #     print(Fore.RED + f"(Failed)" + Fore.RESET)
            #     print(Fore.RED + f"\tThe following non-preferred activities are scheduled: {dup_centre_activity_dislikes}" + Fore.RESET)
                
                
        print(f"Test 3: Doctor recommended activities are scheduled ", end = '')
        if len(dup_centre_activity_recommended) == 0:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        else:
            common_excluded_and_recommended = list(set(ori_activities_excluded_for_patient) & set(dup_centre_activity_recommended))
            not_in_excluded = list(set(dup_centre_activity_recommended) - set(ori_activities_excluded_for_patient))
            
            if len(not_in_excluded) != 0:
                print(Fore.RED + f"(Failed)" + Fore.RESET)
                if len(common_excluded_and_recommended) != 0:
                    print(Fore.YELLOW + f"\t{common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded"  + Fore.RESET)
                print(Fore.RED + f"\tThe following doctor recommended activities are not scheduled: {not_in_excluded}" + Fore.RESET)
            else:
                print(Fore.YELLOW + f"(Warning)" + Fore.RESET)
                if len(common_excluded_and_recommended) != 0:
                    print(Fore.YELLOW + f"\t{common_excluded_and_recommended} are not scheduled because there are part of Activities Excluded"  + Fore.RESET)
                
            # if any(item in ori_activities_excluded_for_patient for item in dup_centre_activity_recommended):
            #     print(Fore.YELLOW + f"(Warning)" + Fore.RESET)
            #     print(Fore.YELLOW + f"\t{dup_centre_activity_recommended} are not scheduled because there are part of Activities Excluded"  + Fore.RESET)
            # else:
            #     print(Fore.RED + f"(Failed)" + Fore.RESET)
            #     print(Fore.RED + f"\tThe following doctor recommended activities are not scheduled: {dup_centre_activity_recommended}" + Fore.RESET)
                
                
        print(f"Test 5: Doctor non-recommended activities are not scheduled ", end = '')
        if len(dup_activity_non_recommended) == 0:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        else:
            print(Fore.RED + f"(Failed)" + Fore.RESET)
            print(Fore.RED + f"\tThe following doctor non-recommended activities are scheduled: {dup_activity_non_recommended}" + Fore.RESET)
            
            
        print(f"Test 8: Patient routines are scheduled ", end = '')
        if len(dup_routine_for_patient) == 0:
            print(Fore.GREEN + f"(Passed)" + Fore.RESET)
        else:
            if any(item in ori_activities_excluded_for_patient for item in dup_routine_for_patient):
                print(Fore.YELLOW + f"(Warning)" + Fore.RESET)
                print(Fore.YELLOW + f"\t{dup_centre_activity_recommended} are not scheduled because there are part of Activities Excluded"  + Fore.RESET)
            else:
                print(Fore.RED + f"(Failed)" + Fore.RESET)
                print(Fore.RED + f"\tThe following doctor recommended activities are not scheduled: {dup_centre_activity_recommended}" + Fore.RESET)
        
        print()
        
    return Response(
        "Schedule Test Successfully",
        status=200,
    )


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