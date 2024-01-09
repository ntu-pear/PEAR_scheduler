from dataclasses import dataclass
import logging


logger = logging.getLogger(__name__)

@dataclass(kw_only=True, frozen=True)
class DBTABLES:
    DB_SCHEMA: str = ""
    ACTIVITY_TABLE: str
    ACTIVITY_AVAILABILITY_TABLE: str
    ACTIVITY_EXCLUSION_TABLE: str
    CENTRE_ACTIVITY_TABLE: str
    CENTRE_ACTIVITY_PREFERENCE_TABLE: str
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE: str
    PATIENT_TABLE: str
    ROUTINE_TABLE: str
    ROUTINE_ACTIVITY_TABLE: str
    SCHEDULE_TABLE: str
