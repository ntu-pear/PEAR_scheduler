import logging
from sqlalchemy import create_engine, Engine, MetaData

logger = logging.getLogger(__name__)

class DB:
    engine: Engine
    schema: MetaData

    @classmethod
    def init_app(cls, conn_str: str):
        logger.info("Connecting to DB")
        cls.engine = create_engine(conn_str)
        logger.info("Connected to DB")
        cls.schema = MetaData()

        logger.info("Downloading DB schema")
        cls.schema.reflect(bind=cls.engine)
        logger.info("DB schema loaded")


        

    @classmethod
    def get_engine(cls):
        return cls.engine
