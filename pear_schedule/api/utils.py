from typing import List
from fastapi.encoders import jsonable_encoder
from dateutil.parser import parse
import datetime

from pydantic import BaseModel, field_validator, model_validator
    

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


class AdHocRequest(BaseModel):
    OldActivityID: int
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
        if parse(self["EndDate"]) < parse(self["StartDate"]):
            raise ValueError(f"EndDate cannot be before StartDate")
        return self
