import argparse
import importlib
import logging
import sys
from typing import Any, Mapping

from flask import Flask

from pear_schedule.db import DB
from pear_schedule.db_utils.writer import ScheduleWriter
# from pear_schedule.db_views.views import ActivitiesView, PatientsOnlyView, PatientsView, GroupActivitiesOnlyView,GroupActivitiesPreferenceView,GroupActivitiesRecommendationView,GroupActivitiesExclusionView, CompulsoryActivitiesOnlyView

from pear_schedule.scheduler.scheduleUpdater import ScheduleRefresher
from pear_schedule.scheduler.utils import build_schedules
from pear_schedule.utils import loadConfigs

logging.basicConfig(format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d:%H:%M:%S',
    level=logging.DEBUG)

logger = logging.getLogger(__name__)


def init_app(config: Mapping[str, Any], args):
    from pear_schedule.api.routes import blueprint as sched_bp
    logger.info("Initialising app")

    app = Flask(__name__)  # TODO: might want to change to FASTAPI/starlette for ASGI and free swagger
    app.config.from_object(config)

    app.register_blueprint(sched_bp, url_prefix="/schedule")

    DB.init_app(app.config["DB_CONN_STR"], app.config)
    loadConfigs(app.config)

    app.run(host="0.0.0.0", debug=True, port=args.port)


def refresh_schedules(config: Mapping[str, Any], args):
    config = {item: getattr(config, item) for item in dir(config)}

    DB.init_app(config["DB_CONN_STR"], config)
    loadConfigs(config)

    ScheduleRefresher.refresh_schedules()


def generate_schedules(config: Mapping[str, Any], args):
    config = {item: getattr(config, item) for item in dir(config)}

    DB.init_app(config["DB_CONN_STR"], config)
    loadConfigs(config)
    # Set up patient schedule structure
    patientSchedules = {} # patient id: [[],[],[],[],[]]

    build_schedules(config, patientSchedules)

    if ScheduleWriter.write(patientSchedules, overwriteExisting=False):
        logger.info("Generated schedules")
    else:
        logger.error("Error in writing schedule to DB. Check logs")
        exit(1)


def parse_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    # add args for starting up server (normal operation)
    server_parser = subparsers.add_parser("start_server", help="server start up help")
    server_parser.add_argument("-c", "--config", required=True)
    server_parser.add_argument("-p", "--port", required=True, type=int)
    server_parser.set_defaults(func=init_app)

    # add args for running schedule update from cli
    update_parser = subparsers.add_parser("refresh_schedules", help="schedule updating help")
    update_parser.add_argument("-c", "--config", required=True)
    update_parser.set_defaults(func=refresh_schedules)

    # add args for running schedule update from cli
    update_parser = subparsers.add_parser("generate_schedules", help="schedule updating help")
    update_parser.add_argument("-c", "--config", required=True)
    update_parser.set_defaults(func=generate_schedules)

    args = parser.parse_args()

    return args


def main():
    args = parse_args()

    config_module = "config"

    spec = importlib.util.spec_from_file_location(config_module, args.config)
    config = importlib.util.module_from_spec(spec)

    sys.modules[config_module] = config
    spec.loader.exec_module(config)

    args.func(config, args)
    # init_app(config)


if __name__ == "__main__":
    main()
