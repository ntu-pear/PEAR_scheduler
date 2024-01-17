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
from pear_schedule.api.utils import checkAdhocRequestBody, isWithinDateRange, getDaysFromDates

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
    #     "PatientID": 1,
    #     "OldActivityID": 0,
    #     "NewActivityID": 1,
    #     "StartDate": "2021-05-26", (if empty means replace for all patients)
    #     "EndDate": "2021-05-26",
    #     
    # }

    data = request.get_json()
    print(data)

    # check request body
    errorRes = checkAdhocRequestBody(data)
    if errorRes != None:
        return errorRes
    
    # find original activity name
    originalDF = ActivityNameView.get_data(arg1=data["OldActivityID"])
    if len(originalDF) == 0: # invalid activity
        responseData = {"Status": "400", "Message": "Invalid old activity ID", "Data": ""} 
        return jsonify(responseData)
        

    oldActivityName = originalDF["ActivityTitle"].iloc[0]

    # find new activity name
    newDF = ActivityNameView.get_data(arg1=data["NewActivityID"])
    if len(newDF) == 0: # invalid activity
        responseData = {"Status": "400", "Message": "Invalid new activity ID", "Data": ""} 
        return jsonify(responseData)

    newActivityName = newDF["ActivityTitle"].iloc[0]

    adHocDF = AdHocScheduleView.get_data(arg1=data["PatientID"])
    scheduleStartDate = adHocDF["StartDate"].iloc[0]
    scheduleEndDate = adHocDF["EndDate"].iloc[0]

    if not isWithinDateRange(data["StartDate"], scheduleStartDate, scheduleEndDate) or not isWithinDateRange(data["EndDate"], scheduleStartDate, scheduleEndDate):
        responseData = {"Status": "400", "Message": "Invalid start date or end date", "Data": ""} 
        return jsonify(responseData)


    chosenDays = getDaysFromDates(data["StartDate"], data["EndDate"])

    filteredAdHocDF = adHocDF[[c for c in adHocDF.columns if c in chosenDays + ["ScheduleID"]]]
    
    # replace activities
    for i, record in filteredAdHocDF.iterrows():
        for col in chosenDays:
            originalSchedule = record[col]
            if originalSchedule != "":
                newSchedule = originalSchedule.replace(oldActivityName, newActivityName)
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
        responseData = {"Status": "500", "Message": "Schedule Update Error. Check Logs", "Data": ""} 
        return jsonify(responseData)
            
    responseData = {"Status": "200", "Message": "Schedule Updated Successfully", "Data": ""} 
    return jsonify(responseData)




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



# @blueprint.route('/download_csv', methods=['GET'])
# def download_csv():
#     # Dummy data for the CSV file
#     data = [
#         {'Name': 'John Doe', 'Age': 30, 'City': 'New York'},
#         {'Name': 'Jane Doe', 'Age': 25, 'City': 'San Francisco'},
#         {'Name': 'Bob Smith', 'Age': 35, 'City': 'Chicago'}
#     ]

#     # Create a CSV file in-memory
#     csv_output = generate_csv(data)

#     # Set up response headers for CSV download
#     response = make_response(csv_output)
#     response.headers["Content-Disposition"] = "attachment; filename=example.csv"
#     response.headers["Content-type"] = "text/csv"

#     return response


# def generate_csv(data):
#     # Create a CSV string using the csv module
#     csv_output = io.StringIO()
#     csv_writer = csv.DictWriter(csv_output, fieldnames=data[0].keys())

#     # Write the header and data to the CSV
#     csv_writer.writeheader()
#     csv_writer.writerows(data)

#     return csv_output.getvalue()