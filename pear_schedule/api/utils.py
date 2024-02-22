from typing import List
from fastapi.encoders import jsonable_encoder
from dateutil.parser import parse
import datetime

from pydantic import BaseModel, field_validator, model_validator

class AdHocRequest(BaseModel):
    OldActivityID: int
    NewActivityID: int
    PatientID: int
    StartDate: str
    EndDate: str

    @field_validator('StartDate', 'EndDate')
    @classmethod
    def isDate(cls, string, fuzzy=False):
        """
        Return whether the string can be interpreted as a date.

        :param string: str, string to check for date
        :param fuzzy: bool, ignore unknown tokens in string if True
        """
        try: 
            parse(string, fuzzy=fuzzy)
            return string

        except ValueError:
            raise ValueError(f"{string} cannot be parsed to date")
        

    @model_validator(mode="after")
    def check_date_range(self):
        if parse(self.EndDate) < parse(self.StartDate):
            raise ValueError(f"EndDate cannot be before StartDate")
        return self
    

def isWithinDateRange(curDateString, startScheduleDate, endScheduleDate):
    return startScheduleDate.date() <= parse(curDateString).date() <= endScheduleDate.date()
        
    
    
def getDaysFromDates(startDateString, endDateString, week_order: List[str]):
    startDayIdx = parse(startDateString).weekday()
    endDayIdx = parse(endDateString).weekday()

    return week_order[startDayIdx: endDayIdx+1]


def date_range(start_date, end_date, DAYS):
    current_date = start_date
    counter = 1
    while current_date <= end_date:
        yield current_date
        counter += 1
        if counter > DAYS:
            break
        current_date += datetime.timedelta(days=1)


def replaceActivitiesInSchedule(filteredAdHocDF, oldActivityName, newActivityName, chosenDays):
    for i, record in filteredAdHocDF.iterrows():
        for col in chosenDays:
            originalSchedule = record[col]
            if originalSchedule != "":
                if oldActivityName not in originalSchedule:
                    return False  
                newSchedule = originalSchedule.replace(oldActivityName, newActivityName)
                filteredAdHocDF.at[i,col] = newSchedule

    return True



def allPatientScheduleGeneratedSystemTest(weeklyScheduleViewDF, patientsDF):
    testName = "All patient weekly schedule is generated"
    testRemarks = []
    testResult = "Pass"

    patientSet = set()

    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSet.add(scheduleRecord["PatientID"])
    
    result = True
    for _, patientRecord in patientsDF.iterrows():
        if patientRecord["PatientID"] not in patientSet:
            result = False
            testRemarks.append(f"{patientRecord['PatientID']} does not have a weekly schedule")
    
    if not result:
        testResult = "Fail"

    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}


def allCompulsoryActivitiesAtCorrectSlotSystemTest(weeklyScheduleViewDF, compulsoryActivitiesDF, request):
    testName = "All compulsory activities are scheduled at correct time slots for all patients"
    testRemarks = []
    testResult = "Pass"
    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]

        for _, compActivityRecord, in compulsoryActivitiesDF.iterrows():
            fixedTimeSlots = compActivityRecord["FixedTimeSlots"].split(",")
            fixedTimeSlots = [(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots]
            compActivityName = compActivityRecord["ActivityTitle"]

            allCompulsoryScheduled = True
            for day, timeslot in fixedTimeSlots:
                if compActivityName not in patientSchedule[day][timeslot]:
                    allCompulsoryScheduled = False
                    testRemarks.append(f"{compActivityName} not scheduled at correct time slot for patient ID {scheduleRecord['PatientID']}. Scheduled timeslot is {request.app.state.config['DAY_OF_WEEK_ORDER'][day]} {request.app.state.config['DAY_TIMESLOTS'][timeslot]}")

    if not allCompulsoryScheduled:
        testResult = "Fail"

    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}


def nonExpiredCentreActivitiesSystemTest(activitiesDF, weeklyScheduleViewDF):
    testName = "Only centre activities 'not expired' are scheduled"
    testRemarks = []
    testResult = "Pass"

    validityMap = {}
    for _, activityRecord, in activitiesDF.iterrows():
        if activityRecord["ActivityTitle"] not in validityMap:
            validityMap[activityRecord["ActivityTitle"]] = [activityRecord["StartDate"], activityRecord["EndDate"]]

    result = True
    startScheduleDate = weeklyScheduleViewDF["StartDate"].iloc[0]
    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        addDays = 0
        for daySchedule in patientSchedule:
            dateOfActivity = startScheduleDate + datetime.timedelta(days=addDays)
            if len(daySchedule) <= 1:
                continue

            for activity in daySchedule:
                activityTitle = activity.split(" |")[0]

                if not (validityMap[activityTitle][0] <= dateOfActivity <= validityMap[activityTitle][1]):
                    result = False
                    testRemarks.append(f"{activityTitle} for patient ID {scheduleRecord['PatientID']} on {dateOfActivity.strftime('%Y-%m-%d')} has expired and is not valid")
            addDays += 1
    
    if not result:
        testResult = "Fail"
            
    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}



def fixedActivitiesScheduledCorrectlySystemTest(activitiesDF, validRoutinesDF, weeklyScheduleViewDF, request):
    testName = "Fixed time centre activities are scheduled in the correct timeslot (fixed and routine activities)"
    testRemarks = []
    testResult = "Pass"

    fixedActivitiesDF = activitiesDF.query("IsFixed == True")
    fixedActivityMap = {} #activityTitle: set(fixedTimeSlots)
    for _, activityRecord in fixedActivitiesDF.iterrows():
        fixedTimeSlots = activityRecord["FixedTimeSlots"].split(",")
        fixedTimeSlots = set([(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots])
        fixedActivityMap[activityRecord["ActivityTitle"]] = fixedTimeSlots

    routineActivityMap = {} #routine activityTitle: set(fixedTimeSlots)
    for _, routineRecord in validRoutinesDF.iterrows():
        fixedTimeSlots = routineRecord["FixedTimeSlots"].split(",")
        fixedTimeSlots = set([(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots])
        routineActivityMap[routineRecord["ActivityTitle"]] = fixedTimeSlots
    

    result = True
    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        for day, daySchedule in enumerate(patientSchedule):
            if len(daySchedule) <= 1:
                continue
            for timeslot, activity in enumerate(daySchedule):
                activityTitle = activity.split(" |")[0]
                if activityTitle in fixedActivityMap and (day, timeslot) not in fixedActivityMap[activityTitle] and activityTitle in routineActivityMap and (day, timeslot) not in routineActivityMap[activityTitle]:
                    result = False
                    testRemarks.append(f"{activityTitle} for patient ID {scheduleRecord['PatientID']} is not scheduled in one of its fixed time slots. Scheduled Time Slot is {request.app.state.config['DAY_OF_WEEK_ORDER'][day]} {request.app.state.config['DAY_TIMESLOTS'][timeslot]}")

    if not result:
        testResult = "Fail"
            
    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}


def groupActivitiesMinSizeSystemTest(groupActivitiesDF,weeklyScheduleViewDF):
    testName = "Group activities meet the minimum number of people"
    testRemarks = []
    testResult = "Pass"
    minSizeMap = {} #activityTitle: min size req

    result = True
    for _, grpActivityRecord in groupActivitiesDF.iterrows():
        minSizeMap[grpActivityRecord["ActivityTitle"]] = [grpActivityRecord["MinPeopleReq"],grpActivityRecord["MinPeopleReq"]]

    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        for _, daySchedule in enumerate(patientSchedule):
            if len(daySchedule) <= 1:
                continue
    
            for _, activity in enumerate(daySchedule):
                activityTitle = activity.split(" |")[0]
                if activityTitle in minSizeMap:
                    minSizeMap[activityTitle][0] -= 1
                    if minSizeMap[activityTitle][0] == 0:
                        minSizeMap.pop(activityTitle)


    for activityTitle, sizeList in minSizeMap.items():
        result = False
        testRemarks.append(f"{activityTitle} did not hit minumum size of {sizeList[1]}")

    if not result:
        testResult = "Fail"
            
    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}

def groupActivitiesCorrectTimeslotSystemTest(groupActivitiesDF, weeklyScheduleViewDF, request):
    testName = "Group activities are scheduled in the correct timeslot"
    testRemarks = []
    testResult = "Pass"
    groupActivitySet = set()

    result = True
    for _, grpActivityRecord in groupActivitiesDF.iterrows():
        groupActivitySet.add(grpActivityRecord["ActivityTitle"])

    timeSlotSet = set(request.app.state.config["GROUP_TIMESLOT_MAPPING"])

    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        for day, daySchedule in enumerate(patientSchedule):
            if len(daySchedule) <= 1:
                continue
            for timeslot, activity in enumerate(daySchedule):
                activityTitle = activity.split(" |")[0] 
                if activityTitle in groupActivitySet:
                    if (day, timeslot) not in timeSlotSet:
                        result = False
                        testRemarks.append(f"{activityTitle} for patient ID {scheduleRecord['PatientID']} is not scheduled in one of the fixed group time slots. Scheduled Time Slot is {request.app.state.config['DAY_OF_WEEK_ORDER'][day]} {request.app.state.config['DAY_TIMESLOTS'][timeslot]}")

    if not result:
        testResult = "Fail"
            
    return {"testName": testName, "testResult": testResult, "testRemarks": testRemarks}


def systemLevelStatistics(activitiesDF, weeklyScheduleViewDF):
    activityCountMap = {}
    for _, activityRecord, in activitiesDF.iterrows():
        activityCountMap[activityRecord["ActivityTitle"]] = 0

    for _, scheduleRecord in weeklyScheduleViewDF.iterrows():
        patientSchedule = [scheduleRecord["Monday"].split("--"),scheduleRecord["Tuesday"].split("--"),scheduleRecord["Wednesday"].split("--"),scheduleRecord["Thursday"].split("--"),scheduleRecord["Friday"].split("--"),scheduleRecord["Saturday"].split("--")]
        for _, daySchedule in enumerate(patientSchedule):
            if len(daySchedule) <= 1:
                continue
            for _, activity in enumerate(daySchedule):
                activityTitle = activity.split(" |")[0] 
                activityCountMap[activityTitle] += 1



    maxActivities = []
    maxActivityCount = max(activityCountMap.values())
    minActivities = []
    minActivityCount = min(activityCountMap.values())

    statsResult = []
    for activity, count in activityCountMap.items():
        statsResult.append(f"{activity}: {count}")
        if count == maxActivityCount:
            maxActivities.append(activity)
        if count == minActivityCount:
            minActivities.append(activity)


    return statsResult, minActivities, maxActivities


def clashInFixedTimeSlotWarning(activitiesDF, validRoutinesDF, request):
    warningName = "Clash in Fixed Time Slots"
    warningRemarks = []

    timeSlotMap = {} # map fixed time slots to activity
    fixedActivitiesDF = activitiesDF.query("IsFixed == True")

    for _, activityRecord in fixedActivitiesDF.iterrows():
        fixedTimeSlots = activityRecord["FixedTimeSlots"].split(",")
        fixedTimeSlots = [(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots]
        activityTitle = activityRecord["ActivityTitle"] + "(normal)"
        for ts in fixedTimeSlots:
            if ts not in timeSlotMap:
                timeSlotMap[ts] = [activityTitle]
            else:
                timeSlotMap[ts].append(activityTitle)

    for _, routineRecord in validRoutinesDF.iterrows():
        fixedTimeSlots = routineRecord["FixedTimeSlots"].split(",")
        fixedTimeSlots = [(int(value.split("-")[0]), int(value.split("-")[1])) for value in fixedTimeSlots]
        activityTitle = routineRecord["ActivityTitle"] + "(routine)"
        for ts in fixedTimeSlots:
            if ts not in timeSlotMap:
                timeSlotMap[ts] = [activityTitle]
            else:
                timeSlotMap[ts].append(activityTitle)

    for timeslot, activityList in timeSlotMap.items():
        warningStatement = ""
        if len(activityList) > 1:
            warningStatement += f"These activities have clashing fixed timeslots on {request.app.state.config['DAY_OF_WEEK_ORDER'][timeslot[0]]} {request.app.state.config['DAY_TIMESLOTS'][timeslot[1]]}: "
            for activity in activityList:
                warningStatement += f"{activity}, "

        if warningStatement:
            warningRemarks.append(warningStatement[:-1])

    return {"warningName": warningName, "warningRemarks": warningRemarks}