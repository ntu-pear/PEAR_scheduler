
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
    ACTIVITY_TABLE = "ref_Activity",
    ACTIVITY_AVAILABILITY_TABLE = "ref_ActivityAvailability",
    ACTIVITY_EXCLUSION_TABLE = "ref_ActivityExclusion",
    CENTRE_ACTIVITY_TABLE = "ref_Centre_Activity",
    CENTRE_ACTIVITY_PREFERENCE_TABLE = "ref_CentreActivityPreference",
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE = "ref_CentreActivityRecommendation",
    PATIENT_TABLE = "ref_Patient",
    ROUTINE_TABLE = "ref_Routine",
    ROUTINE_ACTIVITY_TABLE= "ref_RoutineActivity", 
    MEDICATION_TABLE = "ref_Medication",
    SCHEDULE_TABLE = "Schedule",
)


# Scheduling Configs
DAYS = 5
HOURS = 8
GROUP_TIMESLOTS = 10
GROUP_TIMESLOT_MAPPING = [(0,1), (0,6), (1,1), (1,6), (2,1), (2,6), (3,1), (3,6), (4,1), (4,6)] #(day, timeslot in day)
TARGET_WEEKLY_GROUP_ACTIVITIES = 6
DAY_OF_WEEK_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_TIMESLOTS = ["9am-10am", "10am-11am", "11am-12pm", "12pm-1pm", "1pm-2pm","2pm-3pm","3pm-4pm", "4pm-5pm"]