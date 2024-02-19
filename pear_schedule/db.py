from dataclasses import fields
import logging
from typing import Dict
from sqlalchemy import Table, create_engine, Engine, MetaData

from pear_schedule.utils import DBTABLES

logger = logging.getLogger(__name__)

class DB:
    engine: Engine
    schema: MetaData

    @classmethod
    def init_app(cls, conn_str: str, config: Dict):
        logger.info("Connecting to DB")
        cls.engine = create_engine(conn_str)
        logger.info("Connected to DB")
        cls.schema = MetaData()

        logger.info("Downloading DB schema")
        cls.schema.reflect(bind=cls.engine)
        # dbTables: DBTABLES = config["DB_TABLES"]
        # for field in fields(dbTables):
        #     if (field.name[-5:] != "TABLE"): continue
        #     Table(getattr(dbTables, field.name), cls.schema, autoload_with=cls.engine)


        logger.info("DB schema loaded")


        

    @classmethod
    def get_engine(cls):
        return cls.engine
    
