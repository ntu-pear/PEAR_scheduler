import datetime
import logging
import traceback
import pandas as pd
import json
from typing import Mapping, List, Dict

from sqlalchemy import Connection, column, delete, select, func, literal_column, column
from pear_schedule.db import DB
from pear_schedule.db_utils.utils import day_timeslot_labels
from pear_schedule.db_utils.views import ExistingScheduleView, DeletedMedicationView, WeeklyScheduleView
from pear_schedule.scheduler.medicationScheduling import medicationScheduleData
from pear_schedule.utils import ConfigDependant, DBTABLES
from pear_schedule.models.schedule_model import Schedule
from pear_schedule.models.medication_schedule_model import MedicationSchedule
from pear_schedule.models.ref_patient_medication_model import RefPatientMedication
from pear_schedule.api.utils import MedicationAlreadyAdministeredException, MedicationScheduleNotFoundException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified


logger = logging.getLogger(__name__)

# TODO: REPLACE THIS FOR AUDIT / LOGGING
SYSTEM_USER_ID = "SYSTEM"

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _past_day_columns(start_of_week: datetime.datetime, today: datetime.datetime) -> set:
    """Day columns already in the past, shouldn't be overwritten."""
    return {
        day for i, day in enumerate(WEEKDAYS)
        if (start_of_week.date() + datetime.timedelta(days=i)) < today.date()
    }


def _past_medication_dates(start_of_week: datetime.datetime, today: datetime.datetime, date_format: str) -> set:
    """Medication dates already in the past, shouldn't be overwritten."""
    return {
        (start_of_week.date() + datetime.timedelta(days=i)).strftime(date_format)
        for i in range(7)
        if (start_of_week.date() + datetime.timedelta(days=i)) < today.date()
    }


def _merge_medication_schedule(existing_json: str, new_data: Dict, past_dates: set) -> str:
    """Keeps past dates from existing_json, uses new_data for the rest."""
    try:
        existing = json.loads(existing_json) if existing_json else {}
    except (TypeError, ValueError):
        existing = {}

    merged = dict(new_data)
    for date_str in past_dates:
        if date_str in existing:
            merged[date_str] = existing[date_str]
        else:
            merged.pop(date_str, None)
    return json.dumps(merged)

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
        past_days = _past_day_columns(start_of_week, today)
        past_medication_dates = _past_medication_dates(start_of_week, today, cls.config["STD_DATE_FORMAT"])

        medication_schedule: Mapping[int, Dict[datetime.date, List[Dict]]] = medicationScheduleRef.reformatMedicationScheduleData(cls)

        logger.info(f"writing schedules to db for week start {start_of_week}")
        try:
            for p, slots in patientSchedules.items():
                
                days = cls.config["OPEN_DAYS"]
                converted_schedule = {}

                for i, day in enumerate(days):
                    activities = {}
                    day_labels = day_timeslot_labels(
                        day, len(slots[i]), cls.config["WORKING_HOURS"], cls.config["MIN_ACTIVITY_DURATION"]
                    )
                    for j, activity in enumerate(slots[i]):
                        key = day_labels[j]
                        activities[key] = 'Free and Easy' if not activity else activity
                    converted_schedule[day] = json.dumps(activities)

                existingScheduleDF = ExistingScheduleView.get_data(conn=conn, start_dateTime=start_of_week, patient_id=p)
                existing_medication_schedule = (
                    existingScheduleDF.iloc[0]["MedicationSchedule"] if len(existingScheduleDF) > 0 else None
                )
                medication_schedule_json = _merge_medication_schedule(
                    existing_medication_schedule, medication_schedule.get(int(p), {}), past_medication_dates
                )

                schedule_data = {
                    ## "ScheduleID": _ (not necessary as it is a primary key which will automatically be created)
                    "PatientID": p,
                    "StartDate": start_of_week,
                    "EndDate": end_of_week,
                    "Monday": converted_schedule.get("Monday", ""),
                    "Tuesday": converted_schedule.get("Tuesday", ""),
                    "Wednesday": converted_schedule.get("Wednesday", ""),
                    "Thursday": converted_schedule.get("Thursday", ""),
                    "Friday": converted_schedule.get("Friday", ""),
                    "Saturday": converted_schedule.get("Saturday", ""),
                    "Sunday": converted_schedule.get("Sunday", ""),
                    "MedicationSchedule": medication_schedule_json,
                    # "MedicationLog": "",
                    "IsDeleted": 0, ## Mandatory Field
                    "UpdatedDateTime": today, ## Mandatory Field
                    "CreatedById": SYSTEM_USER_ID,
                    "ModifiedById": SYSTEM_USER_ID
                }

                if not overwriteExisting:
                    # check if have existing schedule, if have then just ignore
                    schedule_data["CreatedDateTime"] = today ## Mandatory Field
                    if len(existingScheduleDF) > 0:
                        null_schedule = False
                        for day in cls.config["OPEN_DAYS"]:
                           if not existingScheduleDF.iloc[0][day]:
                              null_schedule = True
                              break
                        if not null_schedule:
                           continue
                        update_data = {k: v for k, v in schedule_data.items() if k not in past_days}
                        schedule_instance = schedule_table.update().values(update_data).where(
                            schedule_table.c["ScheduleID"] == int(existingScheduleDF.iloc[0]["ScheduleID"])
                        )
                    else:
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
                        update_data = {k: v for k, v in schedule_data.items() if k not in past_days}
                        schedule_instance = schedule_table.update().values(update_data).where(
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
    """
    This function is responsible for writing medication schedules for the day based on the MedicationSchedule generated
    by medicationScheduler on /generate and /regenerate. Removes any outstanding medication schedule records due to expiry, deletion of course, etc, 
    before inserting/updating records.
    """
    @classmethod
    def write(cls, schedules=None) -> bool:
        with DB.get_engine().begin() as conn:
            with Session(bind=conn) as session:
                try:
                  cls.__checkAndFlush(conn, session) # remove any outstanding records first
                  session.commit()
                except Exception as e:
                  logger.exception(e)
                  logger.error(f"An error has occurred when flushing medication schedules, rolling back transaction: {traceback.format_exc()}")
                  session.rollback()
                  return False # do not proceed if unable to delete
            try:
              if schedules:
                return cls.__writeRecordsUsingSchedules(conn, schedules)
              return cls.__writeRecords(conn) # transaction will be automatically committed (begin once)
            except Exception as e:
              logger.exception(e)
              logger.error(f"An error has occurred when writing medication schedules, rolling back transaction: {traceback.format_exc()}")
              conn.rollback()
              return False
    
    @classmethod
    def update(cls, medication_data) -> datetime:
      with DB.get_engine().begin() as conn:
        with Session(bind=conn) as session:
          # returns None if no results
          try: 
            # get MedicationID
            medication_record = session.execute(select(RefPatientMedication).where(
               RefPatientMedication.PatientID == medication_data.PatientID,
               RefPatientMedication.PrescriptionName == medication_data.PrescriptionName
            )).scalar_one()

            # get ScheduleID
            schedule_record = session.execute(select(Schedule).where(
               Schedule.PatientID == medication_data.PatientID,
               Schedule.EndDate >= medication_data.AdministerDate
            )).scalar_one()
            
            composite_key = {
               "MedicationID": medication_record.MedicationID,
               "ScheduleID": schedule_record.ScheduleID,
               "AdministerDate": medication_data.AdministerDate,
               "AdministerTime": medication_data.AdministerTime
            }
            existingSchedule = session.get(MedicationSchedule, composite_key)
            if not existingSchedule: raise MedicationScheduleNotFoundException()
            if existingSchedule.Status == '1': raise MedicationAlreadyAdministeredException()
            existingSchedule.Status = medication_data.Status
            existingSchedule.AdministeredBy = medication_data.AdministeredBy

            timestamp = datetime.datetime.now()
            existingSchedule.ActualAdministerTime = timestamp
            session.commit()
            return timestamp
          except Exception as e:
            logger.exception(e)
            logger.error(f"Error updating medication schedule: {traceback.format_exc()}")
            session.rollback()
            raise e

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
                    "AdministerDate": today_str,
                    "AssignedTo": med["AssignedTo"],
                }

                composite_key_filters = [
                  medication_schedule_table.c.MedicationID == medication_schedule_data["MedicationID"],
                  medication_schedule_table.c.ScheduleID == medication_schedule_data["ScheduleID"],
                  medication_schedule_table.c.AdministerDate == medication_schedule_data["AdministerDate"],
                  medication_schedule_table.c.AdministerTime == medication_schedule_data["AdministerTime"],
                ]
                
                statement = select(medication_schedule_table).where(*composite_key_filters)
                if not conn.execute(statement).first(): # .first() returns none if no results
                  conn.execute(medication_schedule_table.insert().values(medication_schedule_data))
                else:
                  conn.execute(
                     medication_schedule_table.update().where(*composite_key_filters).values({"AssignedTo": medication_schedule_data["AssignedTo"]})
                  )
        return True
    
    @classmethod
    def __writeRecordsUsingSchedules(cls, conn: Connection, schedules: Mapping[int, List[int]]) -> bool:
        today = datetime.datetime.now()
        start_of_week = today - datetime.timedelta(days=today.weekday())  # Monday -> 00:00:00
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_week = start_of_week + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=0)  # Sunday -> 23:59:59
        
        schedule_table = DB.schema.tables[cls.config["DB_TABLES"].SCHEDULE_TABLE]
        for patient_id, meds in schedules.items():
          if len(meds) == 0: continue
          for med in meds:
            # if schedule id is none, create a new schedule for the patient, primarily so as to allow flushing of records to medlog
            sid = med["ScheduleID"]
            x = ExistingScheduleView.get_data(conn=conn, start_dateTime=start_of_week, patient_id=patient_id)
            if not sid and x.empty:
                data = {
                   "PatientID": patient_id,
                   "StartDate": start_of_week,
                   "EndDate": end_of_week,
                   "IsDeleted": 0,
                   "UpdatedDateTime": today,
                   "CreatedById": SYSTEM_USER_ID,
                   "ModifiedById": SYSTEM_USER_ID,
                   "CreatedDateTime": today
                }
                result = conn.execute(schedule_table.insert().values(data))
                sid = result.inserted_primary_key[0] # returns a row obj representing a NamedTuple
            else:
                sid = sid or x.iloc[0]["ScheduleID"]
            with Session(bind=conn) as s:
                try:
                  med["ScheduleID"] = int(sid)
                  s.merge(MedicationSchedule(**med))
                  s.commit()
                except Exception as e:
                  logger.error(f"Error with merge: {e}\n\n{traceback.format_exc()}")
                  s.rollback()
                  return False
                
        return True

    """
    This function flushes outstanding medication schedule records to the medication log field in Schedule based on the schedule id.
    """
    @classmethod
    def __checkAndFlush(cls, conn: Connection, session: Session):
        existingMedicationSchedule: pd.DataFrame = pd.read_sql(select(MedicationSchedule), session.bind)
        # based on schema: MedicationID: int64, ScheduleID: int64, AdministerTime: object, AdministerDate: datetime64[ns], AssignedTo: object, Status: object
        # print(existingMedicationSchedule.dtypes)
        if existingMedicationSchedule.empty:
            return
        
        # if there are existing records. First filter out any records that have expired
        today = datetime.datetime.now().date()
        # if generate/regenerate was submitted midday, the schedules would not have expired yet
        expiredSchedules = existingMedicationSchedule[existingMedicationSchedule["AdministerDate"] == today.strftime(cls.config["STD_DATE_FORMAT"])]
        expiredSchedules["LoggedReason"] = "Expired"

        session.execute(delete(MedicationSchedule).where(MedicationSchedule.AdministerDate < today).execution_options(synchronize_session=False))
        session.flush() # pending deletion

        # then check whether medication for patient has been deleted, flush any outstanding records (for current day)
        # this only checks for medication that was already scheduled before being later deleted
        deletedMedications: pd.DataFrame = DeletedMedicationView.get_data(conn) # returns existing schema + MedicationCourseDeleted
        # simply adds on that the medication course has been deleted.
        deletedMedications.rename(columns={"MedicationCourseDeleted": "LoggedReason"}, inplace=True)
        deletedMedications["LoggedReason"] = deletedMedications["LoggedReason"].apply(lambda x: "Medication course deleted")
        session.execute(delete(MedicationSchedule).where(MedicationSchedule.MedicationID.in_(deletedMedications["MedicationID"].unique().tolist())))
        session.flush()

        # check for administerTime changes for the day, delete any records with changes
        # inserting medication schedules for only one day. Records with duplicate medID, different administer times
        subquery = select(column("value")) \
            .select_from(func.string_split(RefPatientMedication.AdministerTime, ",")) \
            .scalar_subquery()
        
        statement = (
          select(MedicationSchedule, RefPatientMedication.AdministerTime.label("CurrentAdministerTimes"))
          .join(RefPatientMedication, MedicationSchedule.MedicationID == RefPatientMedication.MedicationID)
          .where(MedicationSchedule.AdministerTime.not_in(subquery))
        )

        medication_records = session.execute(statement).all()
        alteredMedications: pd.DataFrame = pd.read_sql(statement, session.bind)
        for obj in medication_records: session.delete(obj.MedicationSchedule)
        session.flush()
        alteredMedications.rename(columns={"CurrentAdministerTimes": "LoggedReason"}, inplace=True)
        alteredMedications["LoggedReason"] = alteredMedications["LoggedReason"].apply(lambda x: f"AdministerTime no longer in {x}")
        
        medicationLog = pd.concat([expiredSchedules, deletedMedications, alteredMedications])
        if medicationLog.empty: return # if there is nothing that was deleted, then no need to update logs, return
        medicationLog["AdministerDate"] = pd.to_datetime(medicationLog["AdministerDate"]).dt.strftime(cls.config["STD_DATE_FORMAT"])
        date_str = medicationLog["AdministerDate"].mode()[0]
        medicationLog = medicationLog.drop("AdministerDate", axis=1).set_index("ScheduleID").groupby(level=0).apply(lambda x: x.to_dict(orient="records")).to_dict()

        for scheduleID, log in medicationLog.items():
          # retrieve existing medication log, append to it, then update back
          schedule = session.get(Schedule, scheduleID)
          # all records are created by the day, meaning about-to-be-flushed records all belong to the same day
          existingLog = json.loads(schedule.MedicationLog) if schedule.MedicationLog else {} # {date: []}
          existingLog.setdefault(date_str, []).extend(log)
          schedule.MedicationLog = json.dumps(existingLog)
          flag_modified(schedule, "MedicationLog") # sqlalchemy may not detect if internal contents of mutable have been modified
