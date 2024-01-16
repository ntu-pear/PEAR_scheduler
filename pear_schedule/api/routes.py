import logging
from flask import Blueprint, jsonify, current_app, request, Response
import pandas as pd
from pear_schedule.db_utils.views import PatientsOnlyView, ValidRoutineActivitiesView, ActivityNameView, AdHocScheduleView, ExistingScheduleView

from pear_schedule.db import DB
from sqlalchemy.orm import Session
from sqlalchemy import Select, Table, select
import datetime
from pear_schedule.db_utils.writer import ScheduleWriter

from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
from pear_schedule.scheduler.individualScheduling import IndividualActivityScheduler
from pear_schedule.scheduler.medicationScheduling import medicationScheduler
from pear_schedule.scheduler.routineScheduling import RoutineActivityScheduler
from utils import DBTABLES

logger = logging.getLogger(__name__)

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
            logger.info(f"FOR PATIENT {p}")
            
            for day, activities in enumerate(slots):
                if day == 0:
                    logger.info(f"\t Monday: ")
                elif day == 1:
                    logger.info(f"\t Tuesday: ")
                elif day == 2:
                    logger.info(f"\t Wednesday: ")
                elif day == 3:
                    logger.info(f"\t Thursday: ")
                elif day == 4:
                    logger.info(f"\t Friday: ")
                
                for index, hour in enumerate(activities):
                    logger.info(f"\t\t {index}: {hour}")
            
            logger.info("==============================================")
    
    if ScheduleWriter.write(patientSchedules, overwriteExisting=False):
        return Response(
            "Generated Schedule Successfully",
            status=200,
        )
    else:
        return Response(
            "Error in writing schedule to DB. Check scheduler logs",
            status = 500
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
        logger.exception(f"Error occurred when inserting \n{e}\nData attempted: \n{schedule_data}")
        return Response(
            "Schedule update error. Check Logs",
            status=500,
        )
            
    return Response(
        "Updated Schedule Successfully",
        status=200,
    )




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


@blueprint.route("/refresh", methods=["GET"])
def refresh_schedules():
    db_tables: DBTABLES = current_app.config["DB_TABLES"]
    patient_table = DB.schema.tables[db_tables.PATIENT_TABLE]

    stmt: Select = select(patient_table).where(
        patient_table.c["UpdateBit"] == 1,
        patient_table.c["IsDeleted"] == False,
    )

    with DB.get_engine().begin() as conn:
        updated_patients: pd.DataFrame = pd.read_sql(stmt, conn)

    IndividualActivityScheduler.update_schedules(updated_patients["PatientID"])


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