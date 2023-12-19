from dataclasses import dataclass
import logging
from typing import Any, Mapping

from flask import Flask

from pear_schedule.db import DB
from pear_schedule.api.routes import blueprint as sched_bp

logger = logging.getLogger(__name__)

def init_app(config: Mapping[str, Any]):
    logger.info("Initialising app")

    app = Flask(__name__)  # TODO: might want to change to FASTAPI/starlette for ASGI and free swagger
    app.config.from_object(config)

    app.register_blueprint(sched_bp, url_prefix="/schedule")

    DB.init_app(app.config["DB_CONN_STR"])

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
    SCHEDULE_TABLE: str
