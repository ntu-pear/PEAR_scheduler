from dataclasses import dataclass
from typing import Any, Mapping
import logging

logger = logging.getLogger(__name__)


CONFIG_DEPENDANTS: Mapping[str, "ConfigDependant"] = {}


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
    MEDICATION_TABLE: str


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
