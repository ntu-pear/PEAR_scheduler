from utils import DBTABLES
from sqlalchemy import URL

# ideally all configs should be in an artifactory but PEAR doesnt have one as of yet


# ~~~~~~~~~~~~~~~~~~~~~~~ DATABASE CONFIGS ~~~~~~~~~~~~~~~~~~~~~~~
DB_CONN_STR = "mssql+pyodbc://localhost:1433/fypcom_pearCore?driver=ODBC+Driver+17+for+SQL+Server"

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
    ACTIVITY_TABLE = "Activity",
    ACTIVITY_AVAILABILITY_TABLE = "ActivityAvailability",
    ACTIVITY_EXCLUSION_TABLE = "ActivityExclusion",
    CENTRE_ACTIVITY_TABLE = "CentreActivity",
    CENTRE_ACTIVITY_PREFERENCE_TABLE = "CentreActivityPreference",
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE = "CentreActivityRecommendation",
    PATIENT_TABLE = "Patient",
    ROUTINE_TABLE = "Routine",
    SCHEDULE_TABLE = "Schedule",
)


# Scheduling Configs
DAYS = 5
HOURS = 8
GROUP_TIMESLOTS = 10
GROUP_TIMESLOT_MAPPING = [(0,1),(1,6), (2,1), (3,6), (4,1), (2,6), (3,1), (0,6), (1,1), (4,6)] #(day, timeslot in day)
