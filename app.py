import logging
from typing import Any, Mapping

from flask import Flask

from pear_schedule.db import DB
# from pear_schedule.db_views.views import ActivitiesView, PatientsOnlyView, PatientsView, GroupActivitiesOnlyView,GroupActivitiesPreferenceView,GroupActivitiesRecommendationView,GroupActivitiesExclusionView, CompulsoryActivitiesOnlyView

import config
from pear_schedule.utils import loadConfigs

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
    loadConfigs(app.config)

    # PatientsOnlyView.init_app(app.config)
    # ActivitiesView.init_app(app.config)
    # PatientsView.init_app(app.config)
    # GroupActivitiesOnlyView.init_app(app.config)
    # GroupActivitiesPreferenceView.init_app(app.config)
    # GroupActivitiesRecommendationView.init_app(app.config)
    # GroupActivitiesExclusionView.init_app(app.config)
    # CompulsoryActivitiesOnlyView.init_app(app.config)

    app.run(host="0.0.0.0", debug=True, port=8000)

def main():
    # TODO: change to use click instead
    init_app(config)


if __name__ == "__main__":
    main()
