
from sqlalchemy import URL

from pear_schedule.utils import DBTABLES
from dotenv import load_dotenv
import os
load_dotenv()
user = os.getenv("DB_USERNAME_DEV")
password = os.getenv("DB_PASSWORD_DEV")
server = os.getenv("DB_SERVER_DEV")
port = os.getenv("DB_DATABASE_PORT")
db = os.getenv("DB_DATABASE_DEV")
driver = os.getenv("DB_DRIVER_DEV")
# ideally all configs should be in an artifactory but PEAR doesnt have one as of yet


# ~~~~~~~~~~~~~~~~~~~~~~~ DATABASE CONFIGS ~~~~~~~~~~~~~~~~~~~~~~~
# DB_CONN_STR = "mssql+pyodbc://(LocalDb)\\MSSQLLocalDB/fypcom_localdb?driver=ODBC+Driver+17+for+SQL+Server"
# DB_CONN_STR = "mssql+pyodbc://localhost:1433/fypcom_pearCore?driver=ODBC+Driver+17+for+SQL+Server"
# DB_CONN_STR = "mssql+pyodbc://fypcom_fypcom:Fyppear%401@host.minikube.internal:1433/fypcom_dev?driver=ODBC+Driver+17+for+SQL+Server"
# DB_CONN_STR = "mssql+pyodbc://fypcom_fypcom:6Tnl78v^@124.6.61.66:1433/fypcom_pearCore?driver=ODBC+Driver+17+for+SQL+Server"
# DB_CONN_STR = "mssql+pyodbc://"
DB_CONN_STR = f"mssql+pyodbc://{user}:{password}@{server}:{port}/{db}?driver={driver.replace(' ', '+')}"
from urllib.parse import unquote


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
    ACTIVITY_EXCLUSION_TABLE = "ref_Activity_Exclusion",
    CENTRE_ACTIVITY_TABLE = "Centre_Activity",
    CENTRE_ACTIVITY_PREFERENCE_TABLE = "ref_Activity_Preference",
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE = "ref_Activity_Recommendation",
    PATIENT_TABLE = "ref_Patient",
    # ROUTINE_TABLE = "ref_Routine",
    # ROUTINE_ACTIVITY_TABLE= "ref_RoutineActivity", 
    MEDICATION_TABLE = "ref_Patient_Prescription",
    SCHEDULE_TABLE = "Schedule",
)

    # ACTIVITY_AVAILABILITY_TABLE = "ref_ActivityAvailability",
# Scheduling Configs
DAYS = 5
HOURS = 8
GROUP_TIMESLOTS = 10
GROUP_TIMESLOT_MAPPING = [(0,1), (0,6), (1,1), (1,6), (2,1), (2,6), (3,1), (3,6), (4,1), (4,6)] #(day, timeslot in day)
TARGET_WEEKLY_GROUP_ACTIVITIES = 6
DAY_OF_WEEK_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_TIMESLOTS = ["9am-10am", "10am-11am", "11am-12pm", "12pm-1pm", "1pm-2pm","2pm-3pm","3pm-4pm", "4pm-5pm"]