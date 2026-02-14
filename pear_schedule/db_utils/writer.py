import datetime
import logging
import traceback
import pandas as pd
import json
from typing import Mapping, List, Dict

from sqlalchemy import Connection
from pear_schedule.db import DB
from pear_schedule.db_utils.views import ExistingScheduleView, ExistingMedicationScheduleView
from pear_schedule.scheduler.medicationScheduling import medicationScheduleData
from pear_schedule.utils import ConfigDependant, DBTABLES
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)

# TODO: REPLACE THIS FOR AUDIT / LOGGING
SYSTEM_USER_ID = "SYSTEM"

class ScheduleWriter(ConfigDependant):
    @classmethod
    def write(
        cls, 
        patientSchedules: Mapping[str, List[str]],
        medicationScheduleRef: medicationScheduleData, 
        conn: Connection = None,
        overwriteExisting: bool = False,
        schedule_meta: Mapping[str, int] = None  # to be able to override specific entries
    ) -> bool:
        if not conn:
            with DB.get_engine().begin() as conn:
                return cls.__writeToDB(patientSchedules, medicationScheduleRef, conn, overwriteExisting, schedule_meta)
        else:
            return cls.__writeToDB(patientSchedules, medicationScheduleRef, conn, overwriteExisting, schedule_meta)

    @classmethod
    def __writeToDB(
        cls, 
        patientSchedules: Mapping[str, List[str]], 
        medicationScheduleRef: medicationScheduleData,
        conn: Connection, 
        overwriteExisting: bool,
        schedule_meta: Mapping[str, int] = None  # to be able to override specific entries
    ):
        db_tables: DBTABLES = cls.config["DB_TABLES"]
        schedule_table = DB.schema.tables[db_tables.SCHEDULE_TABLE]

        today = datetime.datetime.now()
        start_of_week = today - datetime.timedelta(days=today.weekday())  # Monday -> 00:00:00
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_week = start_of_week + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=0)  # Sunday -> 23:59:59

        medication_schedule: Mapping[int, Dict[datetime.date, List[Dict]]] = medicationScheduleRef.reformatMedicationScheduleData(cls)

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
                    "MedicationSchedule": json.dumps(medication_schedule.get(int(p), {})),
                    # "MedicationLog": "",
                    "IsDeleted": 0, ## Mandatory Field 
                    "UpdatedDateTime": today, ## Mandatory Field 
                    "CreatedById": SYSTEM_USER_ID,
                    "ModifiedById": SYSTEM_USER_ID
                }

                if not overwriteExisting:
                    # check if have existing schedule, if have then just ignore
                    existingScheduleDF = ExistingScheduleView.get_data(conn=conn, start_dateTime=start_of_week, patient_id=p)
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

        # TODO: REPLACE THIS FOR AUDIT / LOGGING
        SYSTEM_USER_ID = "SYSTEM"

        with Session(bind=DB.engine) as session:
            try:

                for i, record in filteredAdHocDF.iterrows():
                    schedule_data = {
                        "UpdatedDateTime": today,
                        "CreatedById": SYSTEM_USER_ID,
                        "ModifiedById": SYSTEM_USER_ID
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
    
class MedicationScheduleWrite(ConfigDependant):
    @classmethod
    def write(cls) -> bool:
        with DB.get_engine().begin() as conn:
            cls.__checkAndFlush(conn) # remove any outstanding records first
            return True
            return cls.__writeRecords(conn) # transaction will be automatically committed (begin once)

    @classmethod
    def __writeRecords(cls, conn: Connection) -> bool:
        db_tables: DBTABLES = cls.config["DB_TABLES"]
        medication_schedule_table = DB.schema.tables[db_tables.MEDICATION_SCHEDULE_TABLE]

        # Need to get the ScheduleID, retrieve existing schedule
        today = datetime.datetime.now()
        start_of_week = datetime.datetime.combine(today.date() - datetime.timedelta(days=today.weekday()), datetime.datetime.min.time()) # Monday 00:00:00
        # get existing schedules for the week for all patients, pid should be unique in this df
        existingSchedules: pd.DataFrame = ExistingScheduleView.get_data(conn=conn, start_dateTime=start_of_week)

        # for each patient schedule, retrieve the MedicationSchedule field, parse json, then generate medication schedule records
        # iterrows used to iterate over rows as (index, Series) pairs, itertuples iterates over rows as named tuples (faster)
        today_str = today.date().strftime(cls.config["STD_DATE_FORMAT"])
        for row in existingSchedules.itertuples():
            # try parsing MedicationSchedule, at least {}. Then, try checking list of meds for the day
            medicationSchedule = json.loads(row.MedicationSchedule)
            medications = medicationSchedule.get(today_str, [])
            if not medications: continue
            for med in medications:
                # schema: MedicationID, ScheduleID, AdministerTime (separate), AdministerDate, AssignedTo, Status
                medication_schedule_data = {
                    "MedicationID": med["MedicationID"],
                    "ScheduleID": row.ScheduleID,
                    "AdministerTime": med["AdministerTime"],
                    "AdministerDate": today.date(),
                    "AssignedTo": med["AssignedTo"],
                    "Status": med["Status"]
                }

                conn.execute(medication_schedule_table.insert().values(medication_schedule_data)) #TODO: need to handle exception
    
    @classmethod
    def __checkAndFlush(cls, conn: Connection):
        DB_TABLES: DBTABLES = cls.config["DB_TABLES"]
        medication_schedule_table = DB.schema.tables[DB_TABLES.MEDICATION_SCHEDULE_TABLE]
        schedule_table = DB.schema.tables[DB_TABLES.SCHEDULE_TABLE]

        existingMedicationSchedule: pd.DataFrame = ExistingMedicationScheduleView.get_data(conn)
        # based on schema: MedicationID: int64, ScheduleID: int64, AdministerTime: object, AdministerDate: datetime64[ns], AssignedTo: object, Status: object
        # print(existingMedicationSchedule.dtypes)
        if len(existingMedicationSchedule) == 0:
            return
        
        # if there are existing records. First filter out any records that have expired
        today = (datetime.datetime.now().date() + datetime.timedelta(days=1)).strftime(cls.config["STD_DATE_FORMAT"])
        # if generate/regenerate was submitted midday, the schedules would not have expired yet
        expiredSchedules = existingMedicationSchedule[existingMedicationSchedule["AdministerDate"] < today]
        expiredSchedules["AdministerDate"] = expiredSchedules["AdministerDate"].dt.strftime(cls.config["STD_DATE_FORMAT"])
        medicationLog = expiredSchedules.set_index("ScheduleID").groupby(level=0).apply(lambda x: x.to_dict(orient="records")).to_dict()
        logger.info(medicationLog)

        for row in expiredSchedules.itertuples():
            query = medication_schedule_table.delete().where(
                medication_schedule_table.c.MedicationID == row.MedicationID,
                medication_schedule_table.c.ScheduleID == row.ScheduleID,
                medication_schedule_table.c.AdministerTime == row.AdministerTime,
                medication_schedule_table.c.AdministerDate == row.AdministerDate
            )
            conn.execute(query)
        
        # flush to MedicationLog
        for scheduleID, log in medicationLog.items():
            # TODO: retrieve existing medication log, append to it, then update back
            query = schedule_table.update() \
                                  .values(MedicationLog=json.dumps(log)) \
                                  .where(schedule_table.c.ScheduleID == scheduleID)
            conn.execute(query)

        # then check whether medication for patient has been deleted