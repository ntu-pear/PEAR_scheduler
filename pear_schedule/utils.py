from dataclasses import dataclass
from typing import Any, Mapping
import logging

logger = logging.getLogger(__name__)


CONFIG_DEPENDANTS: Mapping[str, "ConfigDependant"] = {}


@dataclass(kw_only=True, frozen=True)
class DBTABLES:
    DB_SCHEMA: str = ""
    ACTIVITY_TABLE: str

    ACTIVITY_EXCLUSION_TABLE: str
    CENTRE_ACTIVITY_TABLE: str
    CENTRE_ACTIVITY_PREFERENCE_TABLE: str
    CENTRE_ACTIVITY_RECOMMENDATION_TABLE: str
    PATIENT_TABLE: str
    # ROUTINE_TABLE: str
    # ROUTINE_ACTIVITY_TABLE: str
    SCHEDULE_TABLE: str
    MEDICATION_TABLE: str

# ACTIVITY_AVAILABILITY_TABLE: str

@dataclass(kw_only=True, frozen=True)
class MICROSERVICE_TABLES:
    """New dataclass specifically for the microservices ref tables"""
    REF_PATIENT: str = "REF_PATIENT"
    REF_ACTIVITY: str = "REF_ACTIVITY"
    REF_CENTRE_ACTIVITY: str = "REF_CENTRE_ACTIVITY"
    REF_ACTIVITY_EXCLUSION: str = "REF_ACTIVITY_EXCLUSION"
    REF_ACTIVITY_PREFERENCE: str = "REF_ACTIVITY_PREFERENCE"
    REF_ACTIVITY_RECOMMENDATION: str = "REF_ACTIVITY_RECOMMENDATION"
    REF_ACTIVITY_ROUTINE: str = "REF_ACTIVITY_ROUTINE"
    REF_PATIENT_MEDICATION: str = "REF_PATIENT_MEDICATION"
    SCHEDULE: str = "SCHEDULE"


class ConfigDependant:
    config: Mapping[str, Any]
    def __init_subclass__(cls) -> None:
        CONFIG_DEPENDANTS[cls.__name__] = cls

    @classmethod
    def init_app(cls, config: Mapping[str, Any]):
        logger.info(f"Initialising {cls.__name__}")
        cls.config = config


def loadConfigs(config: Mapping[str, Any]):
    for classname, cls in CONFIG_DEPENDANTS.items():
        logger.info(f"reloading config for {classname}")
        cls.init_app(config)


# Utility functions for microservices integration
def get_ref_table_mapping():
    """Returns mapping from old table names to new ref table names"""
    return {
        "Patient": "REF_PATIENT",
        "Activity": "REF_ACTIVITY",
        "CentreActivity": "REF_CENTRE_ACTIVITY", 
        "ActivityExclusion": "REF_ACTIVITY_EXCLUSION",
        "CentreActivityPreference": "REF_ACTIVITY_PREFERENCE",
        "CentreActivityRecommendation": "REF_ACTIVITY_RECOMMENDATION",
        "Routine": "REF_ACTIVITY_ROUTINE",
        "RoutineActivity": "REF_ACTIVITY_ROUTINE",
        "Medication": "REF_PATIENT_MEDICATION",
        "Schedule": "SCHEDULE"
    }


def is_ref_table(table_name: str) -> bool:
    """Check if a table name is a ref table"""
    return table_name.startswith("REF_") or table_name == "SCHEDULE"


def get_model_for_table(table_name: str):
    """Get the SQLAlchemy model class for a given table name"""
    from pear_schedule.models.ref_patient_model import RefPatient
    from pear_schedule.models.ref_activity_model import RefActivity
    from pear_schedule.models.ref_centre_activity_model import RefCentreActivity
    from pear_schedule.models.ref_activity_exclusion_model import RefActivityExclusion
    from pear_schedule.models.ref_activity_preference_model import RefActivityPreference
    from pear_schedule.models.ref_activity_recommendation_model import RefActivityRecommendation
    from pear_schedule.models.ref_activity_routine_model import RefActivityRoutine
    from pear_schedule.models.ref_patient_medication_model import RefPatientMedication
    from pear_schedule.models.schedule_model import Schedule
    
    model_mapping = {
        "REF_PATIENT": RefPatient,
        "REF_ACTIVITY": RefActivity,
        "REF_CENTRE_ACTIVITY": RefCentreActivity,
        "REF_ACTIVITY_EXCLUSION": RefActivityExclusion,
        "REF_ACTIVITY_PREFERENCE": RefActivityPreference,
        "REF_ACTIVITY_RECOMMENDATION": RefActivityRecommendation,
        "REF_ACTIVITY_ROUTINE": RefActivityRoutine,
        "REF_PATIENT_MEDICATION": RefPatientMedication,
        "SCHEDULE": Schedule
    }
    
    return model_mapping.get(table_name)
