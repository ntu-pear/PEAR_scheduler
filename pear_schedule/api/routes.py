from flask import Blueprint, jsonify, current_app
from pear_schedule.db_views.views import PatientsOnlyView, GroupActivitiesPreferenceView

from pear_schedule.db import DB
from sqlalchemy.orm import Session
from sqlalchemy import Table
import datetime

from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
from pear_schedule.scheduler.individualScheduling import IndividualActivityScheduler


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

    # Schedule group activities
    groupSchedule = GroupActivityScheduler.fillSchedule(patientSchedules)
    for patientID, scheduleArr in groupSchedule.items():
        for i, activity in enumerate(scheduleArr):
            day,hour = config["GROUP_TIMESLOT_MAPPING"][i]
            patientSchedules[patientID][day][hour] = activity

    # Schedule individual activities
    IndividualActivityScheduler.fillSchedule(patientSchedules)
    
    ## ------------------------------------------------------------------------------------------------
    ## Inserting into Schedule Table
    session = Session(bind=DB.engine)
    
    # Reflect the database tables
    schedule_table = Table('Schedule', DB.schema, autoload=True, autoload_with= DB.engine)
    
    today = datetime.datetime.now()
    start_of_week = today - datetime.timedelta(days=today.weekday())  # Monday
    end_of_week = start_of_week + datetime.timedelta(days=4)  # Friday
    
    #TEST
    patientSchedules[1] = [['Breathing+Vital Check', '', 'Movie Screening', 'Lunch', 'Cutting Pictures', 'Sewing', 'Brisk Walking', ''], ['Breathing+Vital Check', 'Musical Instrument Lesson', '', 'Lunch', 'Cutting Pictures', '', 'Movie Screening', 'Cup Stacking Game'], ['Breathing+Vital Check', 'Mahjong', 'Sewing', 'Lunch', 'Movie Screening', 'Cutting Pictures', 'Clip Coupons', 'Sort poker chips'], ['Breathing+Vital Check', 'Movie Screening', 'Cutting Pictures', 'Lunch', 'Sewing', 'String beads', 'Clip Coupons', ''], ['Breathing+Vital Check', 'Sewing', 'Cutting Pictures', 'Lunch', 'Movie Screening', 'Sort poker chips', 'Origami', '']]
    
    try:
        for p, slots in patientSchedules.items():
            print(f"{p} Schedule: {slots}")
            
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
            converted_schedule = {}

            for i, day in enumerate(days):
                activities = "-".join(['Free and Easy' if activity == '' else activity for activity in slots[i]])
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
    groupPreferenceDF = GroupActivitiesPreferenceView.get_data()
    preferredDF = groupPreferenceDF.query(f"CentreActivityID == 4 and IsLike == 1")
    
    for id in preferredDF["PatientID"]:
        print(id)
        


    
    data = {"data": "Hello test2"} 
    return jsonify(data) 