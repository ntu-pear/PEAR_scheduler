from flask import Blueprint, jsonify
from pear_schedule.db_views.views import PatientsOnlyView, GroupActivitiesOnlyView,CompulsoryActivitiesOnlyView

from config import DAYS, HOURS, GROUP_TIMESLOT_MAPPING
from pear_schedule.helper.groupScheduling import groupScheduling
from pear_schedule.helper.compulsoryScheduling import compulsoryScheduling


blueprint = Blueprint("scheduling", __name__)


@blueprint.route("/generate", methods=["GET"])
def generate_schedule():

    # Set up patient schedule structure
    patientSchedule = {} # patient id: [[],[],[],[],[]]

    patientDF = PatientsOnlyView.get_data()

    for id in patientDF["PatientID"]:
        patientSchedule[id] = [["" for _ in range(HOURS)] for _ in range(DAYS)]


    # Schedule compulsory activities
    compulsoryScheduling(patientSchedule)

    # Schedule group activities
    groupSchedule = groupScheduling()
    for patientID, scheduleArr in groupSchedule.items():
        for i, activity in enumerate(scheduleArr):
            day,hour = GROUP_TIMESLOT_MAPPING[i]
            patientSchedule[patientID][day][hour] = activity

    # Schedule individual activities


    for p, slots in patientSchedule.items():
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