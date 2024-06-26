import datetime
import logging
import traceback
from typing import Mapping, List

from sqlalchemy import Connection
from pear_schedule.db import DB
from pear_schedule.db_utils.views import ExistingScheduleView
from pear_schedule.utils import ConfigDependant, DBTABLES
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


class ScheduleWriter(ConfigDependant):
    @classmethod
    def write(
        cls, 
        patientSchedules: Mapping[str, List[str]], 
        conn: Connection = None,
        overwriteExisting: bool = False,
        schedule_meta: Mapping[str, int] = None  # to be able to override specific entries
    ) -> bool:
        if not conn:
            with DB.get_engine().begin() as conn:
                return cls.__writeToDB(patientSchedules, conn, overwriteExisting, schedule_meta)
        else:
            return cls.__writeToDB(patientSchedules, conn, overwriteExisting, schedule_meta)

    @classmethod
    def __writeToDB(
        cls, 
        patientSchedules: Mapping[str, List[str]], 
        conn: Connection, 
        overwriteExisting: bool,
        schedule_meta: Mapping[str, int] = None  # to be able to override specific entries
    ):
        db_tables: DBTABLES = cls.config["DB_TABLES"]
        schedule_table = DB.schema.tables[db_tables.SCHEDULE_TABLE]

        today = datetime.datetime.now()
        start_of_week = today - datetime.timedelta(days=today.weekday(), hours=0, minutes=0, seconds=0, microseconds=0)  # Monday -> 00:00:00
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_week = start_of_week + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=0)  # Sunday -> 23:59:59

        logger.info(f"writing schedules to db for week start {start_of_week}")
        try:
            for p, slots in patientSchedules.items():
                
                days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
                converted_schedule = {}

                for i, day in enumerate(days):
                    activities = "--".join(['Free and Easy' if activity == '' else activity for activity in slots[i]])
                    converted_schedule[day] = activities
                
                schedule_data = {
                    ## "ScheduleID": _ (not necessary as it is a primary key which will automatically be created)
                    "PatientID": p,
                    "StartDate": start_of_week,
                    "EndDate": end_of_week,
                    "Monday": converted_schedule["Monday"],
                    "Tuesday": converted_schedule["Tuesday"],
                    "Wednesday": converted_schedule["Wednesday"],
                    "Thursday": converted_schedule["Thursday"],
                    "Friday": converted_schedule["Friday"],
                    "Saturday": "",
                    "Sunday": "",
                    "IsDeleted": 0, ## Mandatory Field 
                    "UpdatedDateTime": today, ## Mandatory Field 
                }

                if not overwriteExisting:
                    # check if have existing schedule, if have then just ignore
                    existingScheduleDF = ExistingScheduleView.get_data(conn=conn, arg1=start_of_week, arg2=p)
                    if len(existingScheduleDF) > 0:
                        continue
                    
                    schedule_data["CreatedDateTime"] = today ## Mandatory Field 
                    # Use the add method to add data to the session
                    schedule_instance = schedule_table.insert().values(schedule_data)
                else:
                    if schedule_meta is None:
                        raise Exception("schedule_meta must be provided when overwriteExisting is used for schedules")
                    elif p not in schedule_meta:
                        schedule_data["CreatedDateTime"] = today ## Mandatory Field 
                        schedule_instance = schedule_table.insert().values(schedule_data)
                    else:
                        if "ScheduleID" not in schedule_meta[p]:
                            raise Exception(
                                f"schedule_meta must be provided for patient {p} with corresponding ScheduleID.\n\
                                Instead got:\n{schedule_meta}"
                            )

                        schedule_data.update(schedule_meta[p])
                        schedule_data.pop("ScheduleID")
                        schedule_instance = schedule_table.update().values(schedule_data).where(
                            schedule_table.c["ScheduleID"] == schedule_meta[p]["ScheduleID"]
                        )
                conn.execute(schedule_instance)
        except Exception as e:
            logger.exception(e)
            logger.error(traceback.format_exc())
            logger.error(f"Error occurred when inserting \n{e}\nData attempted: \n{schedule_data}")
            # conn.get_transaction().rollback()
            # assume conn has transaction started

            return False

        return True


    @classmethod
    def updateDB(cls, schedule_table,filteredAdHocDF, chosenDays):
        
        today = datetime.datetime.now()

        with Session(bind=DB.engine) as session:
            try:

                for i, record in filteredAdHocDF.iterrows():
                    schedule_data = {
                        "UpdatedDateTime": today
                    }
                    for col in chosenDays:
                        schedule_data[col] = record[col]

                    schedule_instance = schedule_table.update().values(schedule_data).where(schedule_table.c["ScheduleID"] == record["ScheduleID"])
                    session.execute(schedule_instance)

                # Commit the changes to the database
                session.commit()
                responseData = {"Status": "200", "Message": "Schedule Updated Successfully", "Data": ""} 
            except Exception as e:
                session.rollback()
                logger.exception(f"Error occurred when inserting \n{e}\nData attempted: \n{schedule_data}")
                responseData = {"Status": "500", "Message": "Schedule Update Error. Check Logs", "Data": ""}   

        return responseData    
        