from flask import Blueprint, jsonify, current_app
from pear_schedule.db_models.models import Schedule
from pear_schedule.db_views.views import PatientsOnlyView, CompulsoryActivitiesOnlyView

# IMPORT TEMPORARILY, WILL REFACTOR
from sqlalchemy.orm import Session
from pear_schedule.db import DB
from pear_schedule.db_views.utils import compile_query
from pear_schedule.utils import ConfigDependant
import datetime
##

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
    ## TODO: TRYING TO TEST TO INSERT TO TABLE... WILL REFACTOR
    session = Session(bind=DB.engine)
    latest_schedule_id = session.query(Schedule.ScheduleID).order_by(Schedule.ScheduleID.desc()).first()
    new_schedule_id = latest_schedule_id[0] + 1
    
    print("Latest Schedule Id: ", latest_schedule_id[0])
    
    today = datetime.datetime.now()
    start_of_week = today - datetime.timedelta(days=today.weekday())  # Monday
    end_of_week = start_of_week + datetime.timedelta(days=4)  # Friday
    
    for p, slots in patientSchedules.items():
        print(f"{p} Schedule: {slots}")
        
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        converted_schedule = {}

        for i, day in enumerate(days):
            activities = "-".join(slots[i])
            converted_schedule[day] = activities
            
        new_schedule = Schedule(
            ScheduleID=new_schedule_id,
            PatientID=p,
            StartDate=start_of_week,
            EndDate=end_of_week,
            Monday= converted_schedule["Monday"],
            Tuesday= converted_schedule["Tuesday"],
            Wednesday= converted_schedule["Wednesday"],
            Thursday= converted_schedule["Thursday"],
            Friday= converted_schedule["Friday"],
            IsDeleted = 0,
            CreatedDateTime = today,
            UpdatedDateTime = today
        )
        
        new_schedule_id = new_schedule_id + 1

        # Add the Schedule object to the session and commit
        session.add(new_schedule)
        session.commit()
        
    # Close the session
        session.close()
    ## ------------------------------------------------------------------------------------------------
        
    data = {"data": "Success"} 
    return jsonify(data) 




@blueprint.route("/test", methods=["GET"])
def test2():
    compulsoryActivityDF = CompulsoryActivitiesOnlyView.get_data()
    # isFixed = groupActivityDF.query(f"ActivityTitle == 'Board Games'").iloc[0]['IsFixed']
    print(compulsoryActivityDF)

    
    data = {"data": "Hello test2"} 
    return jsonify(data) 