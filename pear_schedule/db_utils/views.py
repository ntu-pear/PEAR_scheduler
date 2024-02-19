from contextlib import nullcontext
from operator import or_
from typing import Mapping, Any
import pandas as pd

from sqlalchemy import Connection, Select, and_, func, select
from pear_schedule.db import DB
from pear_schedule.db_utils.utils import compile_query
from pear_schedule.utils import ConfigDependant, DBTABLES

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BaseView(ConfigDependant):
    db_tables: DBTABLES
    @classmethod
    def init_app(cls, config: Mapping[str, Any]):
        cls.db_tables = config["DB_TABLES"]
        cls.config = config

    @classmethod
    def get_data(cls, conn: Connection = None, **query_kwargs) -> pd.DataFrame:
        query: Select = cls.build_query(**query_kwargs)

        logger.info(f"Retrieving data for {cls.__name__}")
        logger.debug(compile_query(query))

        if conn:
            with conn.begin() if conn._transaction is None else nullcontext():
                result: pd.DataFrame = pd.read_sql(query, con=conn)
        else:
            with DB.get_engine().begin() as conn:
                result: pd.DataFrame = pd.read_sql(query, con=conn)
        return result

    @classmethod
    def build_query(cls, **query_kwargs) -> Select:
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
        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        # centre_activity_recommendation = schema.tables[cls.db_tables.CENTRE_ACTIVITY_RECOMMENDATION_TABLE]

        centre_activity_cte = select(
            centre_activity_preference.c["PatientID"],
            centre_activity.c["ActivityID"].label("PreferredActivityID")
        ).join(
            centre_activity, centre_activity_preference.c["CentreActivityID"] == centre_activity.c["CentreActivityID"]
        ).where(
            centre_activity_preference.c["IsLike"] > 0
        ).cte()

        query: Select = select(
            patient.c["PatientID"], 
            centre_activity_cte.c["PreferredActivityID"]
        ).join(
            centre_activity_cte, patient.c["PatientID"] == centre_activity_cte.c["PatientID"], isouter=True
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
            centre_activity_preference.c["IsLike"],
            
        ).join(
            centre_activity_preference, centre_activity.c["CentreActivityID"] == centre_activity_preference.c["CentreActivityID"] 
        ).where(centre_activity.c["IsGroup"] == True
        ).where(centre_activity_preference.c["IsDeleted"] == False
        )


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
            centre_activity_recommendation.c["DoctorRecommendation"],
            
        ).join(
            centre_activity_recommendation, centre_activity.c["CentreActivityID"] == centre_activity_recommendation.c["CentreActivityID"] 
        ).where(centre_activity.c["IsGroup"] == True
        ).where(centre_activity_recommendation.c["IsDeleted"] == False
        )


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
            activity_exclusion, centre_activity.c["ActivityID"] == activity_exclusion.c["ActivityID"] 
        ).where(centre_activity.c["IsGroup"] == True
        ).where(activity_exclusion.c["IsDeleted"] == False
        ).where(activity_exclusion.c["StartDateTime"] <= curDateTime
        ).where(or_(activity_exclusion.c["EndDateTime"] >= curDateTime , activity_exclusion.c["EndDateTime"] == None))


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
    

class RecommendedActivitiesView(BaseView):
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building recommended activities query")
        schema = DB.schema

        recommendations = schema.tables[cls.db_tables.CENTRE_ACTIVITY_RECOMMENDATION_TABLE]
        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]

        query: Select = select(
            centre_activity.c["ActivityID"],
            centre_activity.c["IsFixed"],
            activity.c["ActivityTitle"],
            centre_activity.c["FixedTimeSlots"],
            recommendations.c["PatientID"]
        ).join(
            activity, activity.c["ActivityID"] == centre_activity.c["ActivityID"]
        ).join(
            recommendations, recommendations.c["CentreActivityID"] == centre_activity.c["CentreActivityID"]
        ).where(
            recommendations.c["IsDeleted"] == False,
            recommendations.c["DoctorRecommendation"] > 0,
        )

        return query

class MedicationView(BaseView): # Just medication table view
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building prescription view query")
        schema = DB.schema
        curDateTime = datetime.now()
        
        medication = schema.tables[cls.db_tables.MEDICATION_TABLE]
        
        query: Select = select(
            medication,
        ).where(
            medication.c["EndDateTime"] >= curDateTime 
        )
        return query

class ValidRoutineActivitiesView(BaseView): # 
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building valid routine activities query")
        schema = DB.schema

        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        routine_activity = schema.tables[cls.db_tables.ROUTINE_ACTIVITY_TABLE]
        routine = schema.tables[cls.db_tables.ROUTINE_TABLE]

        query: Select = select(
            activity.c["ActivityTitle"],
            routine_activity.c["FixedTimeSlots"],
            routine.c["PatientID"]
        ).join(
            activity, activity.c["ActivityID"] == routine.c["ActivityID"]
        ).join(
            routine_activity, routine.c["RoutineID"] == routine_activity.c["RoutineID"]
        ).where(routine.c["IncludeInSchedule"] == True)

        return query
    

class ActivityNameView(BaseView): # get activity name from activityID
    @classmethod
    def build_query(cls, **query_kwarg) -> Select:
        logger.info("Building valid routine activities query")
        schema = DB.schema

        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]

        query: Select = select(
            activity.c["ActivityTitle"],
        ).where(activity.c["ActivityID"] == query_kwarg["arg1"])

        return query
    
    

class AdHocScheduleView(BaseView): # get schedule for specific patients
    @classmethod
    def build_query(cls, **query_kwarg) -> Select:
        logger.info("Building ad hoc schedule query")
        schema = DB.schema

        schedule = schema.tables[cls.db_tables.SCHEDULE_TABLE]

        curDateTime = datetime.now()

        query: Select = select(
            schedule.c["ScheduleID"],
            schedule.c["PatientID"],
            schedule.c["Monday"],
            schedule.c["Tuesday"],
            schedule.c["Wednesday"],
            schedule.c["Thursday"],
            schedule.c["Friday"],
            schedule.c["Saturday"],
            schedule.c["Sunday"],
            schedule.c["StartDate"],
            schedule.c["EndDate"],

        ).where(schedule.c["PatientID"] == query_kwarg["arg1"]
        ).where(schedule.c["StartDate"] <= curDateTime
        ).where(schedule.c["EndDate"] >= curDateTime
        ).where(schedule.c["IsDeleted"] == False)

        

        return query
    
    
class ExistingScheduleView(BaseView): # check if have existing schedule
    @classmethod
    def build_query(cls, **query_kwarg) -> Select:
        #start_of_week, patientID

        logger.info("Building existing schedule query")
        schema = DB.schema
        schedule = schema.tables[cls.db_tables.SCHEDULE_TABLE]
        query: Select = select(
            schedule.c["ScheduleID"],
        ).where(schedule.c["EndDate"] >= query_kwarg["arg1"]
        ).where(schedule.c["PatientID"] == query_kwarg["arg2"]
        ).where(schedule.c["IsDeleted"] == False)
        
        return query
    
    
class WeeklyScheduleView(BaseView): # Get the weekly schedule for all patients
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building the weekly schedule query")
        schema = DB.schema
        
        schedule = schema.tables[cls.db_tables.SCHEDULE_TABLE]
        
        curDateTime = datetime.now()
        
        query: Select = select(
            schedule.c["ScheduleID"],
            schedule.c["PatientID"],
            schedule.c["Monday"],
            schedule.c["Tuesday"],
            schedule.c["Wednesday"],
            schedule.c["Thursday"],
            schedule.c["Friday"],
            schedule.c["Saturday"],
            schedule.c["Sunday"],
            schedule.c["StartDate"],
            schedule.c["EndDate"],
        ).where(schedule.c["StartDate"] <= curDateTime
        ).where(schedule.c["EndDate"] >= curDateTime)
        
        return query
class MedicationTesterView(BaseView): # Just medication table view
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building prescription view query")
        schema = DB.schema
        curDateTime = datetime.now()
        start_of_week = curDateTime - timedelta(days=curDateTime.weekday(), hours=0, minutes=0, seconds=0)  # Monday -> 00:00:00
        medication = schema.tables[cls.db_tables.MEDICATION_TABLE]
        
        query: Select = select(
            medication,
        ).where(
            medication.c["EndDateTime"] >= start_of_week 
        )
        return query
    
class CentreActivityPreferenceView(BaseView): # Get the centre activities preferences for all patients 
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building centre activities preference query")
        schema = DB.schema
        
        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        centre_activity_preference = schema.tables[cls.db_tables.CENTRE_ACTIVITY_PREFERENCE_TABLE]
        
        query: Select = select(
            centre_activity_preference.c["CentreActivityPreferenceID"], 
            centre_activity.c["CentreActivityID"],
            centre_activity.c["ActivityID"],
            centre_activity_preference.c["PatientID"],
            centre_activity_preference.c["IsLike"],
            centre_activity.c["IsCompulsory"],
            centre_activity.c["IsFixed"],
            centre_activity.c["IsGroup"],
            activity.c["ActivityTitle"]
        ).join(
            centre_activity_preference, centre_activity.c["CentreActivityID"] == centre_activity_preference.c["CentreActivityID"] 
        ).join(
            activity, activity.c["ActivityID"] == centre_activity.c["ActivityID"]
        )
        
        return query

class CentreActivityRecommendationView(BaseView): # Get the centre activities recommendation for all patients 
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building centre activities recommendation query")
        schema = DB.schema
        
        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        centre_activity_recommendation = schema.tables[cls.db_tables.CENTRE_ACTIVITY_RECOMMENDATION_TABLE]
        
        query: Select = select(
            centre_activity_recommendation.c["CentreActivityRecommendationID"], 
            centre_activity.c["CentreActivityID"],
            centre_activity.c["ActivityID"],
            centre_activity_recommendation.c["PatientID"],
            centre_activity_recommendation.c["DoctorID"],
            centre_activity_recommendation.c["DoctorRecommendation"],
            centre_activity.c["IsCompulsory"],
            centre_activity.c["IsFixed"],
            centre_activity.c["IsGroup"],
            activity.c["ActivityTitle"]
        ).join(
            centre_activity_recommendation, centre_activity.c["CentreActivityID"] == centre_activity_recommendation.c["CentreActivityID"] 
        ).join(
            activity, activity.c["ActivityID"] == centre_activity.c["ActivityID"]
        )
        
        return query
    
class ActivitiesExcludedView(BaseView): # Get the activities excluded for all patients 
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building activities excluded recommendation query")
        schema = DB.schema
        curDateTime = datetime.now()
        start_of_week = curDateTime - timedelta(days=curDateTime.weekday(), hours=0, minutes=0, seconds=0)  # Monday -> 00:00:00
        
        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        activities_excluded = schema.tables[cls.db_tables.ACTIVITY_EXCLUSION_TABLE]
        
        query: Select = select(
            activities_excluded.c["ActivityExclusionID"], 
            activities_excluded.c["ActivityID"],
            activities_excluded.c["PatientID"],
            activities_excluded.c["ExclusionRemarks"],
            activities_excluded.c["EndDateTime"],
            activity.c["ActivityTitle"]
        ).join(
            activity, activity.c["ActivityID"] == activities_excluded.c["ActivityID"]
        ).where(
            or_(
                activities_excluded.c["EndDateTime"] >= start_of_week, 
                activities_excluded.c["EndDateTime"] == None
            )
        )
        
        return query
    
class RoutineView(BaseView): # Get the routines for all patients 
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building routine query")
        schema = DB.schema
        
        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        routine = schema.tables[cls.db_tables.ROUTINE_TABLE]
        
        query: Select = select(
            routine.c["RoutineID"], 
            routine.c["ActivityID"],
            routine.c["PatientID"],
            routine.c["IncludeInSchedule"],
            activity.c["ActivityTitle"]
        ).join(
            activity, activity.c["ActivityID"] == routine.c["ActivityID"]
        )
        
        return query
    
class ActivityAndCentreActivityView(BaseView): # Get all the activities and centre activities 
    @classmethod
    def build_query(cls) -> Select:
        logger.info("Building activities query")
        schema = DB.schema
        
        activity = schema.tables[cls.db_tables.ACTIVITY_TABLE]
        centre_activity = schema.tables[cls.db_tables.CENTRE_ACTIVITY_TABLE]
        
        query: Select = select(
            activity,
            centre_activity
        ).join(
            centre_activity, activity.c["ActivityID"] == centre_activity.c["ActivityID"]
        )
        
        return query
