from typing import Any, Mapping
import logging

logger = logging.getLogger(__name__)


CONFIG_DEPENDANTS: Mapping[str, "ConfigDependant"] = {}


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
