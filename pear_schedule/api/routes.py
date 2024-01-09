from flask import Blueprint, jsonify, current_app
from pear_schedule.db_views.views import PatientsOnlyView, ValidRoutineActivitiesView

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
    start_of_week = today - datetime.timedelta(days=today.weekday())  # Monday
    end_of_week = start_of_week + datetime.timedelta(days=4)  # Friday
    
    try:
        for p, slots in patientSchedules.items():
            print(f"{p} Schedule: {slots}")
            
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
    
    data = {"data": "Success"} 
    return jsonify(data) 




@blueprint.route("/test", methods=["GET"])
def test2():
    routineActivitiesDF = ValidRoutineActivitiesView.get_data()
    # x = GroupActivitiesRecommendationView.get_data()
    # preferredDF = groupPreferenceDF.query(f"CentreActivityID == 4 and IsLike == 1")
    
    # for id in preferredDF["PatientID"]:
    #     print(id)
    
    print(routineActivitiesDF)

        

    
    data = {"data": "Hello test2"} 
    return jsonify(data) 