from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date

class MedicationScheduleUpdate(BaseModel):
    PatientID: int
    PrescriptionName: str
    AdministerDate: date
    AdministerTime: str
    Status: str = Field(pattern=r"^(0|1)$")
    AdministeredBy: Optional[str] = None  # ignored: the caller's token decides who gave the dose

class MedicationScheduleUndo(BaseModel):
    PatientID: int
    PrescriptionName: str
    AdministerDate: date
    AdministerTime: str
