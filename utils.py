import logging
from typing import Any, Mapping

from flask import Flask

from db import DB
from scheduling.routes import blueprint as sched_bp

logger = logging.getLogger(__name__)

def init_app(config: Mapping[str, Any]):
    logger.info("Initialising app")

    app = Flask(__name__)  # TODO: might want to change to FASTAPI/starlette for ASGI and free swagger
    app.config.from_object(config)

    app.register_blueprint(sched_bp, url_prefix="/schedule")

    DB.init_app(app.config["DB_CONN_STR"])
