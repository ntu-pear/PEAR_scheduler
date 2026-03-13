import argparse
import importlib
import logging
import os
import sys
import threading
import signal
import asyncio
import json
import pandas as pd
import datetime
from typing import Any, Mapping

import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv
from pear_schedule.db import DB
from pear_schedule.db_utils.writer import ScheduleWriter
from pear_schedule.db_utils.views import CareCentreView

from pear_schedule.scheduler.scheduleUpdater import ScheduleRefresher
from pear_schedule.scheduler.utils import build_schedules
from pear_schedule.utils import loadConfigs
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
# Import messaging components
from messaging.consumer_manager import create_scheduler_consumer_manager


# Configure logging to reduce Pika spam
def setup_logging():
    """Setup logging with reduced Pika verbosity"""
    logging.basicConfig(
        format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S',
        level=logging.INFO
    )
    
    # Reduce Pika/RabbitMQ logging verbosity
    pika_loggers = [
        'pika',
        'pika.adapters',
        'pika.adapters.blocking_connection',
        'pika.adapters.utils.selector_ioloop_adapter',
        'pika.adapters.utils.io_services_utils', 
        'pika.adapters.utils.connection_workflow',
        'pika.adapters.select_connection',
        'pika.connection',
        'pika.channel',
        'pika.callback'
    ]
    
    for logger_name in pika_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    # These are particularly spammy - set to ERROR only
    spam_loggers = [
        'pika.adapters.utils.selector_ioloop_adapter',
        'pika.adapters.utils.io_services_utils',
        'pika.adapters.blocking_connection',
        'pika.connection'
    ]
    
    for logger_name in spam_loggers:
        logging.getLogger(logger_name).setLevel(logging.ERROR)
    
    # Also reduce SQLAlchemy verbosity if needed
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Global consumer manager instance
consumer_manager = None
shutdown_event = threading.Event()

def create_app():
    from pear_schedule.api import (
        schedule_router,
        integrity_router,
        medication_schedule_router
    )
    app = FastAPI(
        title="PEAR FYP Scheduler Service",
        description="Scheduler Service API Documentation"
    )
    app.include_router(schedule_router.router, prefix="/schedule")
    app.include_router(integrity_router.router, prefix="/integrity")
    app.include_router(medication_schedule_router.router, prefix="/MedicationSchedule")
    #Add Origins so CORS allows these URLS to pass through so Front-end to be able to call APIs
    origins = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        f"http://{os.getenv('WEB_FE_ORIGIN')}",
        f"http://{os.getenv('WEB_FE_ORIGIN_STAGING')}"
        # Add other origins if needed
    ]


    # middleware to connect to the frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,  # Add your Next.js app's URL
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    config = import_config(os.environ["PEAR_SCHEDULER_CONFIG"])
    app.state.config = {item: getattr(config, item) for item in dir(config)}

    DB.init_app(app.state.config["DB_CONN_STR"], app.state.config)
    logger.info("Initialising Care Centre View")
    CareCentreView.init_app(app.state.config)
    careCentreView: pd.DataFrame = CareCentreView.get_data()
    workingHours_str = ""
    try:
        workingHours_str = careCentreView.iloc[0]["WorkingHours"]
    except IndexError:
        raise Exception("No care centre found in database.")
    if not workingHours_str:
        raise Exception("Working hours not found for care centre.")
    workingHours: dict = json.loads(workingHours_str)
    # data format: day in lowercase -> open, close (24hr format, e.g. 0900, 1700)
    schedulable_days = []
    num_slots_per_day = {}
    for day in app.state.config["DAY_OF_WEEK_ORDER"]:
        opening_info: dict = workingHours.get(day.lower())
        if opening_info.get("open"):
            schedulable_days.append(day)
            open_hour = datetime.datetime.strptime(workingHours.get(day.lower()).get("open"), "%H:%M")
            closing_hour = datetime.datetime.strptime(workingHours.get(day.lower()).get("close"), "%H:%M")
            num_slots_per_day[day] = (closing_hour - open_hour) // datetime.timedelta(minutes=app.state.config["MIN_ACTIVITY_DURATION"])
    
    # push this as global config variable for writer.py to use. reload configs for all subclasses of ConfigDependant
    app.state.config["OPEN_DAYS"] = schedulable_days
    app.state.config["WORKING_HOURS"] = workingHours
    app.state.config["SLOTS_PER_DAY"] = num_slots_per_day
    loadConfigs(app.state.config) # then load config for the rest of the classes

    # Add startup and shutdown events for consumer management
    @app.on_event("startup")
    async def startup_event():
        """Start consumers when FastAPI server starts"""
        start_consumers()

    @app.on_event("shutdown") 
    async def shutdown_event_handler():
        """Stop consumers when FastAPI server shuts down"""
        logger.info("FastAPI shutdown event triggered")
        shutdown_event.set()  # Signal shutdown
        await asyncio.get_event_loop().run_in_executor(None, stop_consumers)

    return app

def start_consumers():
    """Start RabbitMQ consumers"""
    global consumer_manager
    
    # Check if messaging is enabled (can be controlled via environment variable)
    enable_messaging = os.getenv('ENABLE_MESSAGING', 'true').lower() == 'true'
    
    if not enable_messaging:
        logger.info("Messaging disabled via ENABLE_MESSAGING environment variable")
        return
    
    try:
        logger.info("Starting RabbitMQ consumers...")
        consumer_manager = create_scheduler_consumer_manager()
        
        # Pass shutdown event to consumer manager
        consumer_manager.set_shutdown_event(shutdown_event)
        
        # Start all registered consumers
        consumer_manager.start_all_consumers()
        
        logger.info("All consumers started successfully")
        
        # Log consumer status
        status = consumer_manager.get_consumer_status()
        for name, state in status.items():
            logger.info(f"Consumer {name}: {state}")
            
    except Exception as e:
        logger.error(f"Failed to start consumers: {str(e)}")
        # Don't fail the entire application if messaging fails
        logger.warning("Application will continue without messaging")

def stop_consumers():
    """Stop RabbitMQ consumers"""
    global consumer_manager
    
    if consumer_manager:
        try:
            logger.info("Stopping RabbitMQ consumers...")
            consumer_manager.stop_all_consumers()
            logger.info("All consumers stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping consumers: {str(e)}")
    else:
        logger.info("No consumers to stop")

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        shutdown_event.set()
        stop_consumers()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def init_app(config: Mapping[str, Any], args):
    logger.info("Initialising app")
    
    os.environ["PEAR_SCHEDULER_CONFIG"] = args.config
    
    # For uvicorn, we rely on FastAPI's shutdown event rather than signal handlers
    # because uvicorn handles signals itself
    
    # Start the FastAPI server (consumers will start automatically via startup event)
    uvicorn.run(
        "app:create_app", 
        host="0.0.0.0", 
        port=args.port, 
        workers=args.workers, 
        factory=True,
        # Add signal handlers for uvicorn
        loop="asyncio",
        reload=True
    )

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

def start_consumers_only(config: Mapping[str, Any], args):
    """Start only the RabbitMQ consumers (no FastAPI server)"""
    logger.info("Starting consumers only mode...")
    
    # Initialize database connection
    config_dict = {item: getattr(config, item) for item in dir(config)}
    DB.init_app(config_dict["DB_CONN_STR"], config_dict)
    loadConfigs(config_dict)
    
    # Setup signal handlers (this mode needs them since no uvicorn)
    setup_signal_handlers()
    
    # Start consumers
    start_consumers()
    
    # Keep the main thread alive
    try:
        logger.info("Consumers running... Press Ctrl+C to stop")
        while not shutdown_event.is_set():
            shutdown_event.wait(1)  # Wait with timeout so we can check health
            
            # Optional: Monitor consumer health
            if consumer_manager:
                status = consumer_manager.get_consumer_status()
                failed_consumers = [name for name, state in status.items() if state.startswith("Error")]
                if failed_consumers:
                    logger.error(f"Failed consumers detected: {failed_consumers}")
                    # Optionally restart failed consumers
                    for name in failed_consumers:
                        logger.info(f"Restarting consumer: {name}")
                        consumer_manager.stop_consumer(name)
                        consumer_manager.start_consumer(name)
                        
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    finally:
        shutdown_event.set()
        stop_consumers()

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
    generate_parser = subparsers.add_parser("generate_schedules", help="schedule updating help")
    generate_parser.add_argument("-c", "--config", required=True)
    generate_parser.set_defaults(func=generate_schedules)
    
    # NEW: add args for running only consumers (useful for separate consumer processes)
    consumer_parser = subparsers.add_parser("start_consumers", help="start only RabbitMQ consumers")
    consumer_parser.add_argument("-c", "--config", required=True)
    consumer_parser.set_defaults(func=start_consumers_only)

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

if __name__ == "__main__":
    main()
