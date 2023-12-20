import logging
from typing import Any, Mapping

from flask import Flask

from pear_schedule.db import DB
from pear_schedule.db_views.views import ActivitiesView, PatientsOnlyView, PatientsView

import config

logging.basicConfig(format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d:%H:%M:%S',
    level=logging.DEBUG)

logger = logging.getLogger(__name__)

def init_app(config: Mapping[str, Any]):
    from pear_schedule.api.routes import blueprint as sched_bp
    logger.info("Initialising app")

    app = Flask(__name__)  # TODO: might want to change to FASTAPI/starlette for ASGI and free swagger
    app.config.from_object(config)

    app.register_blueprint(sched_bp, url_prefix="/schedule")

    DB.init_app(app.config["DB_CONN_STR"])

    PatientsOnlyView.init_app(DB, app.config, app.config["DB_TABLES"])
    ActivitiesView.init_app(DB, app.config, app.config["DB_TABLES"])
    PatientsView.init_app(DB, app.config, app.config["DB_TABLES"])

    
    app.run(host="localhost", debug=True, port=8000)

def main():
    # TODO: change to use click instead
    init_app(config)


if __name__ == "__main__":
    main()
