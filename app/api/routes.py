import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.encoders import jsonable_encoder
from typing import List, Optional
from pear_schedule.db_utils.views import ValidRoutineActivitiesView, ActivityNameView, AdHocScheduleView, GroupActivitiesOnlyView, WeeklyScheduleView, CompulsoryActivitiesOnlyView,PatientsOnlyView,AllActivitiesView
import pandas as pd

from pear_schedule.db import DB
from sqlalchemy.orm import Session
import datetime
from pear_schedule.db_utils.writer import ScheduleWriter

from pear_schedule.api.utils import AdHocRequest, activitiesExcludedPatientTest, checkWeeklyScheduleCorrectness, generateStatistics, isWithinDateRange, getDaysFromDates, medicationPatientTest, nonPreferredActivitiesPatientTest, nonRecommendedActivitiesPatientTest, preferredActivitiesPatientTest, prepareJsonResponse, printWellnessPlan, recommendedActivitiesPatientTest, replaceActivitiesInSchedule, allPatientScheduleGeneratedSystemTest, allCompulsoryActivitiesAtCorrectSlotSystemTest,nonExpiredCentreActivitiesSystemTest,fixedActivitiesScheduledCorrectlySystemTest, groupActivitiesMinSizeSystemTest, groupActivitiesCorrectTimeslotSystemTest, routinesPatientTest, systemLevelStatistics,clashInFixedTimeSlotWarning, getTablesDF, getPatientWellnessPlan
from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler
from pear_schedule.scheduler.scheduleUpdater import ScheduleRefresher
from pear_schedule.scheduler.utils import build_schedules
from pear_schedule.utils import DBTABLES


logger = logging.getLogger(__name__)

from colorama import init, Fore

init(autoreset=True)


router = APIRouter()


@router.api_route("/generate/", methods=["GET"])
def generate_schedule(request: Request):
    config = request.app.state.config
    
    # Set up patient schedule structure
    patientSchedules = {} # patient id: [[],[],[],[],[]]

    try:
        build_schedules(config, patientSchedules)

        if ScheduleWriter.write(patientSchedules, overwriteExisting=False):
            responseData = {"Status": "200", "Message": "Generated Schedule Successfully", "Data": ""} 
            return JSONResponse(jsonable_encoder(responseData))
        else:
            responseData = {"Status": "500", "Message": "Error in writing schedule to DB. Check scheduler logs", "Data": ""} 
            return JSONResponse(jsonable_encoder(responseData))
            
    except Exception as e:
        logger.exception(e)
        responseData = {"Status": "400", "Message": str(e), "Data": ""}
        return JSONResponse(jsonable_encoder(responseData))


@router.api_route("/regenerate/", methods=["GET"])
def generate_schedule(request: Request):
    config = request.app.state.config
    
    # Set up patient schedule structure
    patientSchedules = {} # patient id: [[],[],[],[],[]]

    try:
        build_schedules(config, patientSchedules)
        with DB.get_engine().begin() as conn:
            latestSchedules = PreferredActivityScheduler.getMostUpdatedSchedules(patientSchedules.keys(), conn)
        
        scheduleMeta = {}
        for _, row in latestSchedules.iterrows():
            scheduleMeta[row["PatientID"]] = {
                "ScheduleID": row["ScheduleID"],
            }

        if ScheduleWriter.write(patientSchedules, schedule_meta=scheduleMeta, overwriteExisting=True):
            responseData = {"Status": "200", "Message": "Generated Schedule Successfully", "Data": ""} 
            return JSONResponse(jsonable_encoder(responseData))
        else:
            responseData = {"Status": "500", "Message": "Error in writing schedule to DB. Check scheduler logs", "Data": ""} 
            return JSONResponse(jsonable_encoder(responseData))
            
    except Exception as e:
        logger.exception(e)
        responseData = {"Status": "400", "Message": str(e), "Data": ""}
        return JSONResponse(jsonable_encoder(responseData))


@router.api_route("/patientTest/", methods=["GET"])
async def test_schedule(request: Request, patientIDs: Optional[List[int]] = Query(None)): 
    try:
        # 1) Prepare necessary tables and lists 
        tablesDF = getTablesDF() 
        json_response = {} # json data to be returned to caller
        activity_count_dict = {activity: 0 for activity in tablesDF['activitiesAndCentreActivityViewDF']['ActivityTitle'].unique()} # dictionary to keep track of each activity count
        activity_count_dict['Free and Easy'] = 0 # adding free and easy as an activity 
        
        mondayIndex = tablesDF['weeklyScheduleViewDF'].columns.get_loc("Monday")
        config = {
            "DAY_OF_WEEK_ORDER": request.app.state.config['DAY_OF_WEEK_ORDER'],
            "DAYS": request.app.state.config['DAYS']
        }
        
        # 2) Checks if 'patientID' provided by the user is valid or not
        if patientIDs is not None:
            valid_patientIDs = tablesDF['weeklyScheduleViewDF']['PatientID'].unique().tolist()
            invalid_patientIDs = [patientID for patientID in patientIDs if patientID not in valid_patientIDs]
            
            if invalid_patientIDs:
                responseData = {"Status": "400", "Message": f"Patient IDs {invalid_patientIDs} do not exist in the schedule", "Data": ""}
                return JSONResponse(jsonable_encoder(responseData))
            
            tablesDF['weeklyScheduleViewDF'] = tablesDF['weeklyScheduleViewDF'][tablesDF['weeklyScheduleViewDF']['PatientID'].isin(patientIDs)]
        
        # 3) Iterate over every patient
        for index, patientInfo in tablesDF['weeklyScheduleViewDF'].iterrows():
            patientID = patientInfo['PatientID']
            json_response[patientID] = {}
            
            print(Fore.CYAN + f"=========================================== Checking patient {patientID} schedule now ===========================================" + Fore.RESET)
            
            # resets the activity_count on each patient iteration             
            for activity in activity_count_dict:
                activity_count_dict[activity] = 0
            
            # 4) Get the patient_wellness_plan. This dictionary stores ground truth information and will be used to validate against the weekly schedule 
            '''
            patient_wellness_plan = {
                'patientID' : patientID,
                'DAYS' : request.app.state.config['DAYS'],
                'DAY_OF_WEEK_ORDER' : request.app.state.config['DAY_OF_WEEK_ORDER'],
                'weekly_schedule': weekly_schedule,
                'schedule_start_datetime' : schedule_start_datetime,
                'schedule_end_datetime': schedule_end_datetime,
                'routines_timeslot' : routines_timeslot,
                'should_be_scheduled_activities': {
                    'preferred': preferred_activities,
                    'recommended': recommended_activities,
                    'routines': routines,
                    'error_check': {  # Duplicate lists for further processing
                        'preferred': preferred_activities,
                        'recommended': recommended_activities,
                        'routines': routines,
                    }
                },
                'should_not_be_scheduled_activities':{
                    'non_preferred': non_preferred_activities,
                    'non_recommended': non_recommended_activities,
                    'excluded': activities_excluded,
                    'error_check': {  # Initializing empty lists for further processing
                        'non_preferred': [],
                        'non_recommended': [],
                        'excluded': [],
                    }
                },
                'medication_info': {
                    'medication_schedule' : medication_schedule,
                    'error_check': { # Initializing empty dictionary for further processing
                        "medication_schedule" : medication_incorrect_schedule
                    }
                }
            }
            '''
            patient_wellness_plan = getPatientWellnessPlan(tablesDF, patientID, config)
            
            # 5) Updates the json_response with patient_wellness_plan
            prepareJsonResponse(json_response, patient_wellness_plan)
            
            printWellnessPlan(patient_wellness_plan)
            
            # 6) Validates the weekly schedule against the patient_wellness_plan 
            checkWeeklyScheduleCorrectness(mondayIndex, patientInfo, patient_wellness_plan, json_response, activity_count_dict)
            
            # 7) Checking Patient Test Cases 
            print(Fore.CYAN + "\nCHECKING TEST CASES" + Fore.RESET)
            
            # Test 1: Activities excluded are not scheduled
            activitiesExcludedPatientTest(patient_wellness_plan, json_response)
            
            # Test 2: Patient preferred activities are scheduled
            preferredActivitiesPatientTest(patient_wellness_plan, json_response)
            
            # Test 3: Patient non-preferred activities are not scheduled        
            nonPreferredActivitiesPatientTest(patient_wellness_plan, json_response)
            
            # Test 4: Doctor recommended activities are scheduled
            recommendedActivitiesPatientTest(patient_wellness_plan, json_response)        
            
            # Test 5: Doctor non-recommended activities are not scheduled
            nonRecommendedActivitiesPatientTest(patient_wellness_plan, json_response)        
            
            # Test 6: Patient routines are scheduled   
            routinesPatientTest(patient_wellness_plan, json_response)
            
            # Test 7: All medications are administered correctly
            medicationPatientTest(patient_wellness_plan, json_response)
            
            # 8) Generate Patient Test Report
            generateStatistics(tablesDF, patient_wellness_plan, json_response, activity_count_dict)
            
        responseData = {"Status": "200", "Message": "Tester Ran Successfully", "Data": json_response} 
        return JSONResponse(jsonable_encoder(responseData))
    
    except Exception as e:
        logger.exception(f"Error occurred when conducting patientTest: {e}")
        responseData = {"Status": "500", "Message": "Patient Test Error", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))


@router.api_route("/adhoc/", methods=["PUT"])
def adhoc_change_schedule(request: Request, data: AdHocRequest):
    # find original activity name
    originalDF = ActivityNameView.get_data(arg1=data.OldActivityID)
    if len(originalDF) == 0: # invalid activity
        responseData = {"Status": "400", "Message": "Invalid old activity ID", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))
        

    oldActivityName = originalDF["ActivityTitle"].iloc[0]

    # find new activity name
    newDF = ActivityNameView.get_data(arg1=data.NewActivityID)
    if len(newDF) == 0: # invalid activity
        responseData = {"Status": "400", "Message": "Invalid new activity ID", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))

    newActivityName = newDF["ActivityTitle"].iloc[0]

    # Get schedule
    adHocDF = AdHocScheduleView.get_data(arg1=data.PatientID)
    if len(adHocDF.index) == 0:
        responseData = {"Status": "404", "Message": "Patient Schedule not found/generated", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))
    
    scheduleStartDate = adHocDF["StartDate"].iloc[0]
    scheduleEndDate = adHocDF["EndDate"].iloc[0]

    if not isWithinDateRange(data.StartDate, scheduleStartDate, scheduleEndDate) or not isWithinDateRange(data.EndDate, scheduleStartDate, scheduleEndDate):
        responseData = {"Status": "400", "Message": "Invalid start date or end date", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))


    chosenDays = getDaysFromDates(data.StartDate, data.EndDate, request.app.state.config["DAY_OF_WEEK_ORDER"])

    filteredAdHocDF = adHocDF[[c for c in adHocDF.columns if c in chosenDays + ["ScheduleID"]]]
    
    # replace activities
    isSuccess = replaceActivitiesInSchedule(filteredAdHocDF, oldActivityName, newActivityName, chosenDays)
    if not isSuccess:
        responseData = {"Status": "400", "Message": f"{oldActivityName} (old activity) cannnot be found in some/all days of patient schedule for {data.StartDate.split('T')[0]} to {data.EndDate.split('T')[0]}", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))
                
    
    # Update db
    db_tables: DBTABLES = request.app.state.config["DB_TABLES"]
    schedule_table = DB.schema.tables[db_tables.SCHEDULE_TABLE]
    responseData = ScheduleWriter.updateDB(schedule_table, filteredAdHocDF, chosenDays)
    
    return JSONResponse(jsonable_encoder(responseData))



@router.api_route("/refresh/", methods=["GET"])
def refresh_schedules():
    ScheduleRefresher.refresh_schedules()

    return PlainTextResponse("Successfully updated schedules", status_code=200)


@router.api_route("/systemTest/", methods=["GET"])
async def system_report(request: Request): 
    
    systemTestArray = []
    statisticsArray = []
    warningArray = []

    weeklyScheduleViewDF = WeeklyScheduleView.get_data()
    compulsoryActivitiesDF = CompulsoryActivitiesOnlyView.get_data()
    patientsDF = PatientsOnlyView.get_data()
    activitiesDF = AllActivitiesView.get_data()
    groupActivitiesDF = GroupActivitiesOnlyView.get_data()
    validRoutinesDF = ValidRoutineActivitiesView.get_data()

    if len(weeklyScheduleViewDF) == 0:
        responseData = {"Status": "404", "Message": "No schedule for the week found", "Data": ""} 
        return JSONResponse(jsonable_encoder(responseData))
    

    # 1. All patient weekly schedule is generated"
    systemTestArray.append(allPatientScheduleGeneratedSystemTest(weeklyScheduleViewDF, patientsDF))

    # 2. All compulsory activities are scheduled at correct time slots  
    systemTestArray.append(allCompulsoryActivitiesAtCorrectSlotSystemTest(weeklyScheduleViewDF, compulsoryActivitiesDF, request))

    # 3. Only centre activities "not expired" are scheduled
    systemTestArray.append(nonExpiredCentreActivitiesSystemTest(activitiesDF, weeklyScheduleViewDF))

    # 4. Fixed time centre activities are scheduled in the correct timeslot (fixed and routine activities)
    systemTestArray.append(fixedActivitiesScheduledCorrectlySystemTest(activitiesDF, validRoutinesDF, weeklyScheduleViewDF, request))

    # 5. Group activities meet the minimum number of people   
    systemTestArray.append(groupActivitiesMinSizeSystemTest(groupActivitiesDF, weeklyScheduleViewDF))

    # 6. Group activities are scheduled in the correct timeslot
    systemTestArray.append(groupActivitiesCorrectTimeslotSystemTest(groupActivitiesDF, weeklyScheduleViewDF, request))

    # statistics
    statsResult, minActivities, maxActivities = systemLevelStatistics(activitiesDF, weeklyScheduleViewDF)

    statisticsArray.append({"statsName": "Number of patients scheduled per activity", "statsResult": statsResult})
    statisticsArray.append({"statsName": "Most scheduled activities", "statsResult": [activity for activity in maxActivities]})
    statisticsArray.append({"statsName": "Least scheduled activities", "statsResult": [activity for activity in minActivities]})
    
    # warnings
    warningArray.append(clashInFixedTimeSlotWarning(activitiesDF, validRoutinesDF, request))

    responseData = {"Status": "200", "Message": "System Report Generated", "Data": {"SystemTest": systemTestArray, "Statistics": statisticsArray, "Warnings": warningArray}} 
    return JSONResponse(jsonable_encoder(responseData))

