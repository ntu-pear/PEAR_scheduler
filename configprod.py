
from sqlalchemy import URL

from pear_schedule.utils import DBTABLES
from pear_schedule.database import DB_CONN_STR_RAW
from dotenv import load_dotenv
import os
load_dotenv()

# Use the properly encoded connection string from database module
DB_CONN_STR = DB_CONN_STR_RAW


# connection_string = (
#     r"Driver=ODBC Driver 18 for SQL Server;"
#     r"Server=127.0.0.1;"
#     r"Database=fypcom_localdb;"
#     r"TrustServerCertificate=yes;"
#     r"UID=sa;"
#     r"PWD=MyPass@word;"
# )
# DB_CONN_STR = URL.create(
#     "mssql+pyodbc", 
#     query={"odbc_connect": connection_string}
# )

# ~~~~~~~~~~~~~~~~~~~~~~~ DATABASE TABLES/VIEWS ~~~~~~~~~~~~~~~~~~~~~~~
DB_TABLES = DBTABLES(
    DB_SCHEMA = "",
    ACTIVITY_TABLE = "REF_ACTIVITY",
    ACTIVITY_EXCLUSION_TABLE = "REF_ACTIVITY_EXCLUSION",
    CENTRE_ACTIVITY_TABLE = "REF_CENTRE_ACTIVITY",
    CENTRE_ACTIVITY_PREFERENCE_TABLE = "REF_ACTIVITY_PREFERENCE",
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE = "REF_ACTIVITY_RECOMMENDATION",
    PATIENT_TABLE = "REF_PATIENT",
    # ROUTINE_TABLE = "REF_ROUTINE",
    # ROUTINE_ACTIVITY_TABLE = "REF_ROUTINEACTIVITY",
    MEDICATION_TABLE = "REF_PATIENT_MEDICATION",
    ALLOCATION_TABLE = "REF_PATIENT_ALLOCATION",
    SCHEDULE_TABLE = "SCHEDULE",
    MEDICATION_SCHEDULE_TABLE = "MEDICATION_SCHEDULE",
    CARE_CENTRE_TABLE = "REF_CARE_CENTRE",
)


    # ACTIVITY_AVAILABILITY_TABLE = "ref_ActivityAvailability",
# ! Phased out variables for scheduling. Still have remaining dependencies
DAYS = 6
HOURS = 16

# FOR GROUP SCHEDULING
GROUP_TIMESLOTS = 15
# GROUP_TIMESLOT_MAPPING = [(0,1), (0,6), (0,7), (1,1), (1,6), (1,7), (2,1), (2,6), (2,7), (3,1), (3,6), (3,7), (4,1), (4,6), (4,7)] #(day, timeslot in day)
GROUP_TIMESLOT_MAPPING = ["Monday 10:00", "Monday 15:00", "Monday 16:00", "Tuesday 10:00", "Tuesday 15:00", "Tuesday 16:00", "Wednesday 10:00", "Wednesday 15:00", "Wednesday 16:00", "Thursday 10:00", "Thursday 15:00", "Thursday 16:00", "Friday 10:00", "Friday 15:00", "Friday 16:00"] #(day, timeslot in day)
# GROUP_TIMESLOT_MAPPING = [(0,2), (0,12), (0,14), (1,2), (1,12), (1,14), (2,2), (2,12), (2,14), (3,2), (3,12), (3,14), (4,2), (4,12), (4,14)] #(day, timeslot in day)
TARGET_WEEKLY_GROUP_ACTIVITIES = 6

# Scheduling Configs
DAY_OF_WEEK_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# ! Remaining dependency with /systemTest, DAY_TIMESLOTS should be phased out
DAY_TIMESLOTS = ["09:00-09:30", "09:30-10:00", "10:00-10:30", "10:30-11:00", "11:00-11:30", "11:30-12:00", "12:00-12:30", "12:30-13:00", "13:00-13:30", "13:30-14:00", "14:00-14:30", "14:30-15:00", "15:00-15:30", "15:30-16:00", "16:00-16:30", "16:30-17:00"]
MIN_ACTIVITY_DURATION: int = 30 # in minutes
MAX_ACTIVITY_DURATION: int = 60 # in minutes
STD_DATE_FORMAT = "%Y-%m-%d"
CARE_CENTRE_ID = 1