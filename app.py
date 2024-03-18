import argparse
import importlib
import logging
import os
import sys
from typing import Any, Mapping

import uvicorn
from fastapi import FastAPI

from pear_schedule.db import DB
from pear_schedule.db_utils.writer import ScheduleWriter

from pear_schedule.scheduler.scheduleUpdater import ScheduleRefresher
from pear_schedule.scheduler.utils import build_schedules
from pear_schedule.utils import loadConfigs

logging.basicConfig(format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d:%H:%M:%S',
    level=logging.DEBUG)

logger = logging.getLogger(__name__)


def create_app():
    from pear_schedule.api.routes import router as sched_router
    app = FastAPI()
    app.include_router(sched_router, prefix="/schedule")

    config = import_config(os.environ["PEAR_SCHEDULER_CONFIG"])
    app.state.config = {item: getattr(config, item) for item in dir(config)}

    DB.init_app(app.state.config["DB_CONN_STR"], app.state.config)
    loadConfigs(app.state.config)

    return app

def init_app(config: Mapping[str, Any], args):
    logger.info("Initialising app")
    # from pear_schedule.api.routes import router as sched_router
    # app = FastAPI()
    # app.include_router(sched_router, prefix="/schedule")
    # app.state.config = {item: getattr(config, item) for item in dir(config)}

    # DB.init_app(app.state.config["DB_CONN_STR"], app.state.config)
    # loadConfigs(app.state.config)

    os.environ["PEAR_SCHEDULER_CONFIG"] = args.config

    uvicorn.run("app:create_app", host="0.0.0.0", port=args.port, workers=args.workers, factory=True)


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
    server_parser.add_argument("-w", "--workers", required=False, type=int, default=1)
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


def import_config(filepath: str):
    config_module = "config"
    spec = importlib.util.spec_from_file_location(config_module, filepath)
    config = importlib.util.module_from_spec(spec)

    sys.modules[config_module] = config
    spec.loader.exec_module(config)

    return config


def main():
    args = parse_args()
    config = import_config(args.config)

    args.func(config, args)
    # init_app(config)


if __name__ == "__main__":
    main()
