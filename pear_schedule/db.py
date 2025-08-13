from dataclasses import fields
import logging
from typing import Dict
from sqlalchemy import Table, create_engine, Engine, MetaData
from sqlalchemy.orm import sessionmaker

from pear_schedule.database import Base, get_db
from pear_schedule.utils import DBTABLES
from pear_schedule.models import (
    ref_patient_model,
    ref_activity_model, 
    ref_activity_exclusion_model,
    ref_activity_preference_model,
    ref_activity_recommendation_model,
    ref_activity_routine_model,
    ref_patient_prescription_model,
    schedule_model
)

logger = logging.getLogger(__name__)

class DB:
    engine: Engine
    schema: MetaData  # For backward compatibility with existing views
    SessionLocal: sessionmaker
    
    @classmethod
    def init_app(cls, conn_str: str, config: Dict):
        logger.info("Connecting to DB")
        cls.engine = create_engine(conn_str, echo=True)
        logger.info("Connected to DB")
        
        # Create sessionmaker for ORM operations
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        
        # Initialize schema metadata for backward compatibility
        cls.schema = MetaData()
        
        logger.info("Creating database tables if they don't exist")
        try:
            # Create all tables defined in models
            Base.metadata.create_all(bind=cls.engine)
            logger.info("ORM tables created successfully")
        except Exception as e:
            logger.warning(f"Could not create ORM tables: {e}")
        
        # For backward compatibility, load existing tables via reflection
        logger.info("Loading table schema for backward compatibility")
        try:
            dbTables: DBTABLES = config["DB_TABLES"]
            for field in fields(dbTables):
                if (field.name[-5:] != "TABLE"): continue
                table_name = getattr(dbTables, field.name)
                try:
                    Table(table_name, cls.schema, autoload_with=cls.engine)
                    logger.info(f"Loaded table: {table_name}")
                except Exception as e:
                    logger.warning(f"Could not load table {table_name}: {e}")
        except Exception as e:
            logger.error(f"Error during table reflection: {e}")
        
        logger.info("Database schema initialized")

    @classmethod
    def get_engine(cls):
        return cls.engine
    
    @classmethod
    def get_session(cls):
        """Get a new database session"""
        return cls.SessionLocal()
    
    @classmethod
    def get_db_session(cls):
        """Get database session with automatic cleanup (for dependency injection)"""
        return get_db()