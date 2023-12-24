from flask import Blueprint, jsonify, current_app
from pear_schedule.db_views.views import PatientsOnlyView, CompulsoryActivitiesOnlyView

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


    for p, slots in patientSchedules.items():
        print(f"{p} Schedule: {slots}")

    data = {"data": "Success"} 
    return jsonify(data) 




@blueprint.route("/test", methods=["GET"])
def test2():
    compulsoryActivityDF = CompulsoryActivitiesOnlyView.get_data()
    # isFixed = groupActivityDF.query(f"ActivityTitle == 'Board Games'").iloc[0]['IsFixed']
    print(compulsoryActivityDF)

    
    data = {"data": "Hello test2"} 
    return jsonify(data) 