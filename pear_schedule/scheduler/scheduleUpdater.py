import pandas as pd
from sqlalchemy import Select, select
from pear_schedule.db import DB
from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler
from pear_schedule.utils import DBTABLES, ConfigDependant


class ScheduleRefresher(ConfigDependant):
    @classmethod
    def refresh_schedules(cls):
        db_tables: DBTABLES = cls.config["DB_TABLES"]
        patient_table = DB.schema.tables[db_tables.PATIENT_TABLE]

        stmt: Select = select(patient_table).where(
            patient_table.c["UpdateBit"] == 1,
            patient_table.c["IsDeleted"] == False,
        )

        with DB.get_engine().begin() as conn:
            updated_patients: pd.DataFrame = pd.read_sql(stmt, conn)

        PreferredActivityScheduler.update_schedules(updated_patients["PatientID"])