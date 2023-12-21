from flask import Blueprint, jsonify
from pear_schedule.db_views.views import ActivitiesView, PatientsOnlyView, GroupActivitiesOnlyView,GroupActivitiesPreferenceView,GroupActivitiesRecommendationView,GroupActivitiesExclusionView

from config import DAYS, HOURS, GROUP_TIMESLOT_MAPPING
from pear_schedule.helper.groupScheduling import groupScheduling


blueprint = Blueprint("scheduling", __name__)


@blueprint.route("/generate", methods=["GET"])
def generate_schedule():

    # Set up patient schedule structure
    patientSchedule = {} # patient id: [[],[],[],[],[]]

    patientDF = PatientsOnlyView.execute_query()

    for id in patientDF["PatientID"]:
        patientSchedule[id] = [["" for _ in range(HOURS)] for _ in range(DAYS)]


    
    # Schedule compulsory activities

    # Schedule group activities
    groupSchedule = groupScheduling()
    for patientID, scheduleArr in groupSchedule.items():
        for i, activity in enumerate(scheduleArr):
            day,hour = GROUP_TIMESLOT_MAPPING[i]
            patientSchedule[patientID][day][hour] = activity

    # Schedule individual activities


    # for p, slots in groupSchedule.items():
    #     print(f"{p} Schedule: {slots}")

    data = {"data": "Success"} 
    return jsonify(data) 




@blueprint.route("/test2", methods=["GET"])
def test2():
    groupActivityDF = GroupActivitiesOnlyView.execute_query()
    isFixed = groupActivityDF.query(f"ActivityTitle == 'Board Games'").iloc[0]['IsFixed']
    print(isFixed)

    

    
    data = {"data": "Hello test2"} 
    return jsonify(data) 