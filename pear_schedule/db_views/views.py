from typing import Mapping
import pandas as pd

from sqlalchemy import Select, select
from pear_schedule.db import DB
from pear_schedule.db_views.utils import compile_query
from utils import DBTABLES

import logging

logger = logging.getLogger(__name__)


class BaseView:  # might want to change to abc
    db: DB = None
    db_tables: DBTABLES
    @classmethod
    def init_app(cls, db: DB, config: Mapping[str, str]):
        cls.db = db
        cls.db_tables = config["db_tables"]
        cls.config = config
    
    
    @classmethod
    def get_activities(cls) -> pd.DataFrame:
        with cls.db.get_engine().begin() as conn:
            query: Select = cls.build_query()

            logger.info(f"Retrieving data for {cls.__name__}")
            logger.debug(compile_query(query))
            result: pd.DataFrame = pd.read_sql(query, con=conn)
        return result

    @classmethod
    def build_query(cls) -> Select:
        raise NotImplementedError(f"build_query() not implemented for {cls.__name__}")


class ActivitiesView(BaseView):
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building activities query")
        schema = cls.db.schema

        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        activity_availability = schema.tables[cls.db_tables.ACTIVITY_AVAILABILITY_TABLE]
        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        routine = schema.tables[cls.db_tables.ROUTINE_TABLE]

        query: Select = select(
            activity
        ).join(
            activity_availability, activity.c["ActivityID"] == activity_availability.c["ActivityID"]
        ).join(
            centre_activity, activity.c["ActivityID"] == centre_activity.c["ActivityID"]
        ).join(
            routine, activity.c["ActivityID"] == routine.c["ActivityID"]
        )

        return query


class PatientsView(BaseView):
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building patients query")
        schema = cls.db.schema

        patient = schema.tables[cls.db_tables.PATIENT_TABLE]
        centre_activity_preference = schema.tables[cls.db_tables.CENTRE_ACTIVITY_PREFERENCE_TABLE]
        centre_activity_recommendation = schema.tables[cls.db_tables.CENTRE_ACTIVITY_RECOMMENDATION_TABLE]
        activity_exclusion = schema.tables[cls.db_tables.ACTIVITY_EXCLUSION_TABLE]

        query: Select = select(
            patient
        ).join(
            centre_activity_preference, patient.c["PatientID"] == centre_activity_preference.c["PatientID"]
        ).join(
            centre_activity_recommendation, 
            patient.c["PatientID"] == centre_activity_recommendation.c["PatientID"]
        ).join(
            activity_exclusion, patient.c["PatientID"] == activity_exclusion.c["PatientID"]
        )

        return query
