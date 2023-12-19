# ideally all configs should be in an artifactory but PEAR doesnt have one as of yet


# ~~~~~~~~~~~~~~~~~~~~~~~ DATABASE CONFIGS ~~~~~~~~~~~~~~~~~~~~~~~
from dataclasses import dataclass


DB_CONN_STR = "mssql+pymssql://localhost:1433/fypcom_pearCore"


# ~~~~~~~~~~~~~~~~~~~~~~~ DATABASE TABLES/VIEWS ~~~~~~~~~~~~~~~~~~~~~~~
from utils import DBTABLES
db_tables = DBTABLES(
    DB_SCHEMA = "",
    ACTIVITY_TABLE = "Activity",
    ACTIVITY_AVAILABILITY_TABLE = "ActivityAvailability",
    ACTIVITY_EXCLUSION_TABLE = "ActivityExclusion",
    CENTRE_ACTIVITY_TABLE = "CentreActivity",
    CENTRE_ACTIVITY_PREFERENCE_TABLE = "CentreActivity",
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE = "CentreActivityRecommendation",
    PATIENT_TABLE = "Patient",
    ROUTINE_TABLE = "Routine",
    SCHEDULE_TABLE = "Schedule",
)
