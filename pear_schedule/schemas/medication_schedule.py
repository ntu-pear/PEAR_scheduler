from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date

class MedicationScheduleUpdate(BaseModel):
    PatientID: int
    PrescriptionName: str
    AdministerDate: date
    AdministerTime: str
    Status: str = Field(pattern=r"^(0|1)$")
    AdministeredBy: str