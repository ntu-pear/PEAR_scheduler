from sqlalchemy.orm import clear_mappers
from pear_schedule.database import engine, Base

clear_mappers()

from pear_schedule.models import (
    ref_activity_exclusion_model,
    ref_activity_model,
    ref_activity_recommendation_model,
    ref_activity_preference_model,
    ref_activity_routine_model,
    ref_patient_model,
    ref_patient_medication_model,
    schedule_model
)

# Create all tables in the database using the engine
Base.metadata.create_all(bind=engine)

print("Tables created successfully in the DB_DATABASE_DEV database.")