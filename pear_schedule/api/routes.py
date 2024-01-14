from flask import Blueprint, jsonify, current_app, request, Response
from pear_schedule.db_views.views import PatientsOnlyView, ValidRoutineActivitiesView, ActivityNameView, AdHocScheduleView, ExistingScheduleView, WeeklyScheduleView, CentreActivityPreferenceView, CentreActivityRecommendationView, ActivitiesExcludedView, RoutineView, MedicationView

from pear_schedule.db import DB
from sqlalchemy.orm import Session
from sqlalchemy import Table
import datetime

from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
from pear_schedule.scheduler.individualScheduling import IndividualActivityScheduler
from pear_schedule.scheduler.medicationScheduling import medicationScheduler
from pear_schedule.scheduler.routineScheduling import RoutineActivityScheduler

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

    # Schedule individual activities
    IndividualActivityScheduler.fillSchedule(patientSchedules)
    
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

            # check if have existing schedule, if have then just ignore
            existingScheduleDF = ExistingScheduleView.get_data(start_of_week, p)
            if len(existingScheduleDF) > 0:
                continue
            
            # Use the add method to add data to the session
            schedule_instance = schedule_table.insert().values(schedule_data)
            session.execute(schedule_instance)
            
            # Commit the changes to the database
            session.commit()
            
    except Exception as e:
        print(f"Error occurred when inserting {schedule_data}: {e}")
        
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
        print(f"================== Checking patient {row['PatientID']} schedule now ==================")
        
        centre_activity_preference_for_patient = centreActivityPreferenceViewDF.loc[centreActivityPreferenceViewDF['PatientID'] == row['PatientID']]
        centre_activity_recommendation_for_patient = centreActivityRecommendationViewDF.loc[centreActivityRecommendationViewDF['PatientID'] == row['PatientID']]
        activities_excluded_for_patient = activitiesExcludedViewDF.loc[activitiesExcludedViewDF['PatientID'] == row['PatientID']]
        routine_for_patient = routineViewDF.loc[(routineViewDF['PatientID'] == row['PatientID']) & routineViewDF["IncludeInSchedule"]]
        medication_for_patient = medicationViewDF.loc[medicationViewDF['PatientID'] == row['PatientID']]
        
        centre_activity_likes = centre_activity_preference_for_patient.loc[centre_activity_preference_for_patient['IsLike'] == True]
        centre_activity_dislikes = centre_activity_preference_for_patient.loc[centre_activity_preference_for_patient['IsLike'] == False]
        centre_activity_recommended = centre_activity_recommendation_for_patient.loc[centre_activity_recommendation_for_patient['DoctorRecommendation'] == True]
        centre_activity_non_recommended = centre_activity_recommendation_for_patient.loc[centre_activity_recommendation_for_patient['DoctorRecommendation'] == False]
        
        print(f"Preferred Activities: {centre_activity_likes['ActivityTitle'].tolist()}")
        print(f"Non-Preferred Activities: {centre_activity_dislikes['ActivityTitle'].tolist()}")
        print(f"Activities Excluded: {activities_excluded_for_patient['ActivityTitle'].tolist()}")
        print(f"Routines: {routine_for_patient['ActivityTitle'].tolist()}")
        print(f"Doctor Recommended Activities: {centre_activity_recommended['ActivityTitle'].tolist()}")
        print(f"Doctor Non-Recommended Activities: {centre_activity_non_recommended['ActivityTitle'].tolist()}")
        print(f"Medication: {medication_for_patient['PrescriptionName'].tolist()}")
        print()
        
        remaining_centre_activity_likes = centre_activity_likes['ActivityTitle'].tolist()
        remaining_centre_activity_recommended = centre_activity_recommended['ActivityTitle'].tolist()
        
        for day in range(2,7):
            print(f"Activities in the week: {row.iloc[day]}")
            
            activities_in_a_day = row.iloc[day].split("--")
            
            remaining_centre_activity_likes = [item for item in remaining_centre_activity_likes if not any(item in activity for activity in activities_in_a_day)] # if the preferred activity is in the activities_in_a_day, we remove that activity from the initial list
            remaining_centre_activity_recommended = [item for item in remaining_centre_activity_recommended if not any(item in activity for activity in activities_in_a_day)] # if the activities recommended is in the activities_in_a_day, we remove that activity from the initial list
        
        ## INDIVIDUAL CHECKS 
        print("\nCHECKING IN PROGRESS")
        
        print(f"Test 1: Patient preferred activities are scheduled ", end = '')
        if len(remaining_centre_activity_likes) == 0:
            print(f"(Passed)")
        else:
            if any(item in activities_excluded_for_patient['ActivityTitle'].tolist() for item in remaining_centre_activity_likes):
                print(f"(Warning)")
                print(f"\tThe following preferred activities are not scheduled: {remaining_centre_activity_likes}, because there are part of Activities Excluded")
            elif any(item in centre_activity_non_recommended['ActivityTitle'].tolist() for item in remaining_centre_activity_likes):
                print(f"(Warning)")
                print(f"\tThe following preferred activities are not scheduled: {remaining_centre_activity_likes}, because there are Doctor Non-Recommendation Activities")
            else:
                print(f"(Failed)")
                print(f"\tThe following preferred activities are not scheduled: {remaining_centre_activity_likes}")
            
        print(f"Test 3: Doctor recommended activities are scheduled ", end = '')
        if len(remaining_centre_activity_recommended) == 0:
            print(f"(Passed)")
        else:
            if any(item in activities_excluded_for_patient['ActivityTitle'].tolist() for item in remaining_centre_activity_recommended):
                print(f"(Warning)")
                print(f"\tThe following doctor recommended activities are not scheduled: {remaining_centre_activity_recommended}, because there are part of Activities Excluded")
            else:
                print(f"(Failed)")
                print(f"\tThe following doctor recommended activities are not scheduled: {remaining_centre_activity_recommended}")
        
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
            status = 500
        )
    
    if not isinstance(data["originalActivityID"], int) or not isinstance(data["newActivityID"], int):
        
        return Response(
            "Invalid Request Body",
            status = 500
        )
    
    if not isinstance(data["patientIDList"], list) or not isinstance(data["dayList"], list):
        
        return Response(
            "Invalid Request Body",
            status = 500
        )
    

    for val in data["patientIDList"]:
        if not isinstance(val, int):
            return Response(
                "Invalid Request Body",
                status = 500
            )
    
    days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"}
    for val in data["dayList"]:
        if val not in days:
            return Response(
                "Invalid Request Body",
                status = 500
            )

    return None