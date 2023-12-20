from flask import Blueprint, jsonify
from pear_schedule.db_views.views import ActivitiesView, PatientsOnlyView


blueprint = Blueprint("scheduling", __name__)

DAYS = 5
HOURS = 8

@blueprint.route("/generate", methods=["GET"])
def generate_schedule():

    # Set up patient schedule structure
    patientSchedule = {} # patient id: [[],[],[],[],[]]

    patientDF = PatientsOnlyView.execute_query().values.tolist()
    patientIDs = [x[0] for x in patientDF]

    for id in patientIDs:
        patientSchedule[id] = [["" for _ in range(HOURS)] for _ in range(DAYS)]

    
    # Schedule compulsory activities

    # Schedule group activities

    # Schedule individual activities


    data = {"data": "Hello World"} 
    return jsonify(data) 
    # raise NotImplementedError()