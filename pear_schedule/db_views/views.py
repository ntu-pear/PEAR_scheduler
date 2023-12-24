from typing import Mapping, Any
import pandas as pd

from sqlalchemy import Select, select
from pear_schedule.db import DB
from pear_schedule.db_views.utils import compile_query
from pear_schedule.utils import ConfigDependant
from utils import DBTABLES
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class BaseView(ConfigDependant):
    db_tables: DBTABLES
    @classmethod
    def init_app(cls, config: Mapping[str, Any]):
        cls.db_tables = config["DB_TABLES"]
        cls.config = config

    @classmethod
    def get_data(cls) -> pd.DataFrame:
        with DB.get_engine().begin() as conn:
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
        schema = DB.schema

        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        # activity_availability = schema.tables[cls.db_tables.ACTIVITY_AVAILABILITY_TABLE]
        # routine = schema.tables[cls.db_tables.ROUTINE_TABLE]

        query: Select = select(
            activity,
            centre_activity.c["FixedTimeSlots"].label("FixedTimeSlots"),
            centre_activity.c["MinDuration"].label("MinDuration"),
            centre_activity.c["MaxDuration"].label("MaxDuration")
        ).join(
            centre_activity, activity.c["ActivityID"] == centre_activity.c["ActivityID"]
        )\
        # .join(
        #     routine, activity.c["ActivityID"] == routine.c["ActivityID"]
        # )

        return query


class PatientsView(BaseView):
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building patients query")
        schema = DB.schema

        patient = schema.tables[cls.db_tables.PATIENT_TABLE]
        centre_activity_preference = schema.tables[cls.db_tables.CENTRE_ACTIVITY_PREFERENCE_TABLE]
        activity_exclusion = schema.tables[cls.db_tables.ACTIVITY_EXCLUSION_TABLE]
        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        # centre_activity_recommendation = schema.tables[cls.db_tables.CENTRE_ACTIVITY_RECOMMENDATION_TABLE]

        centre_activity_cte = select(
            centre_activity_preference.c["PatientID"],
            centre_activity.c["ActivityID"].label("PreferredActivityID")
        ).join(
            centre_activity, centre_activity_preference.c["CentreActivityID"] == centre_activity.c["CentreActivityID"]
        ).cte()

        query: Select = select(
            patient.c["PatientID"], 
            centre_activity_cte.c["PreferredActivityID"],
            activity_exclusion.c["ActivityID"].label("ExcludedActivityID"),
        ).join(
            centre_activity_cte, patient.c["PatientID"] == centre_activity_cte.c["PatientID"], isouter=True
        ).join(
            activity_exclusion, patient.c["PatientID"] == activity_exclusion.c["PatientID"], isouter=True
        )\
        # .join(
        #     centre_activity_recommendation, 
        #     patient.c["PatientID"] == centre_activity_recommendation.c["PatientID"]
        # )

        return query
    

class PatientsOnlyView(BaseView): # Just patients only
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building only patients query")
        schema = DB.schema

        patient = schema.tables[cls.db_tables.PATIENT_TABLE]

        query: Select = select(
            patient.c.PatientID
        )

        return query


class GroupActivitiesOnlyView(BaseView): # Just group activities only
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building only group activities query")
        schema = DB.schema

        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]

        query: Select = select(
            centre_activity.c["ActivityID"],
            activity.c["ActivityTitle"],
            centre_activity.c["IsFixed"],
            centre_activity.c["FixedTimeSlots"],
            centre_activity.c["MinPeopleReq"],
        ).join(
            activity, activity.c["ActivityID"] == centre_activity.c["ActivityID"]
        ).where(centre_activity.c["IsGroup"] == True
        ).where(centre_activity.c["IsCompulsory"] == False)

        return query
    

class GroupActivitiesPreferenceView(BaseView): # Just group activities preference only
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building only group activities preference query")
        schema = DB.schema

        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        centre_activity_preference = schema.tables[cls.db_tables.CENTRE_ACTIVITY_PREFERENCE_TABLE]


        query: Select = select(
            centre_activity.c["CentreActivityID"],
            centre_activity_preference.c["PatientID"],
            
        ).join(
            centre_activity_preference, centre_activity.c["CentreActivityID"] == centre_activity_preference.c["CentreActivityID"] 
        ).where(centre_activity.c["IsGroup"] == True
        ).where(centre_activity_preference.c["IsLike"] == 1)


        return query
    

class GroupActivitiesRecommendationView(BaseView): # Just group activities preference only
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building only group activities recommendation query")
        schema = DB.schema

        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        centre_activity_recommendation= schema.tables[cls.db_tables.CENTRE_ACTIVITY_RECOMMENDATION_TABLE]


        query: Select = select(
            centre_activity.c["CentreActivityID"],
            centre_activity_recommendation.c["PatientID"],
            
        ).join(
            centre_activity_recommendation, centre_activity.c["CentreActivityID"] == centre_activity_recommendation.c["CentreActivityID"] 
        ).where(centre_activity.c["IsGroup"] == True
        ).where(centre_activity_recommendation.c["DoctorRecommendation"] == True)


        return query
    

class GroupActivitiesExclusionView(BaseView): # Just group activities preference only
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building only group activities exclusion query")
        schema = DB.schema

        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        activity_exclusion = schema.tables[cls.db_tables.ACTIVITY_EXCLUSION_TABLE]


        curDateTime = datetime.now()
        query: Select = select(
            centre_activity.c["CentreActivityID"],
            activity_exclusion.c["PatientID"],
            
        ).join(
            activity_exclusion, centre_activity.c["CentreActivityID"] == activity_exclusion.c["ActivityID"] 
        ).where(centre_activity.c["IsGroup"] == True
        ).where(activity_exclusion.c["StartDateTime"] <= curDateTime
        ).where(activity_exclusion.c["EndDateTime"] >= curDateTime)


        return query
    

class CompulsoryActivitiesOnlyView(BaseView): # Just compulsory activities only
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building only compulsory activities query")
        schema = DB.schema

        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]

        query: Select = select(
            centre_activity.c["ActivityID"],
            activity.c["ActivityTitle"],
            centre_activity.c["IsFixed"],
            centre_activity.c["FixedTimeSlots"],
        ).join(
            activity, activity.c["ActivityID"] == centre_activity.c["ActivityID"]
        ).where(centre_activity.c["IsCompulsory"] == True)

        return query
    