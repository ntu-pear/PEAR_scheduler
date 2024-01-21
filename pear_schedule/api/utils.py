from typing import List
from flask import Response, current_app, jsonify
from dateutil.parser import parse

def checkAdhocRequestBody(data):
    if "OldActivityID" not in data or "NewActivityID" not in data or "PatientID" not in data or "StartDate" not in data or "EndDate" not in data:
        
        responseData = {"Status": "400", "Message": "Invalid Request Body", "Data": ""} 
        return jsonify(responseData)
    
    if not isinstance(data["OldActivityID"], int) or not isinstance(data["NewActivityID"], int):
        
        responseData = {"Status": "400", "Message": "Invalid Request Body", "Data": ""} 
        return jsonify(responseData)
    
    if not isinstance(data["PatientID"], int):
        
        responseData = {"Status": "400", "Message": "Invalid Request Body", "Data": ""} 
        return jsonify(responseData)
    

    if not isDate(data["StartDate"]):
        responseData = {"Status": "400", "Message": "Invalid Request Body", "Data": ""} 
        return jsonify(responseData)
    

    if not isDate(data["EndDate"]):
        responseData = {"Status": "400", "Message": "Invalid Request Body", "Data": ""} 
        return jsonify(responseData)

    if parse(data["EndDate"]) < parse(data["StartDate"]):
        responseData = {"Status": "400", "Message": "Invalid Request Body", "Data": ""} 
        return jsonify(responseData)
    
    return None


def isDate(string, fuzzy=False):
    """
    Return whether the string can be interpreted as a date.

    :param string: str, string to check for date
    :param fuzzy: bool, ignore unknown tokens in string if True
    """
    try: 
        parse(string, fuzzy=fuzzy)
        return True

    except ValueError:
        return False
    

def isWithinDateRange(curDateString, startScheduleDate, endScheduleDate):
    return startScheduleDate.date() <= parse(curDateString).date() <= endScheduleDate.date()
        
    
    
def getDaysFromDates(startDateString, endDateString, week_order: List[str] = None):
    startDayIdx = parse(startDateString).weekday()
    endDayIdx = parse(endDateString).weekday()

    DAY_OF_WEEK_ORDER = week_order or current_app.config["DAY_OF_WEEK_ORDER"]

    return DAY_OF_WEEK_ORDER[startDayIdx: endDayIdx+1]
