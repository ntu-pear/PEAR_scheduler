from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date

class MedicationScheduleUpdate(BaseModel):
    MedicationID: int
    ScheduleID: int
    AdministerDate: date
    AdministerTime: str
    Status: str
    AdministeredBy: str