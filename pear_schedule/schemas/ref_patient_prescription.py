from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
import re

class RefPatientPrescriptionBase(BaseModel):
    Id: int
    PatientId: int
    PrescriptionListId: int
    PrescriptionListValue: str
    Dosage: str
    FrequencyPerDay: int
    Instruction: str
    StartDate: datetime
    EndDate: Optional[datetime] = None
    IsAfterMeal: Optional[str] = None
    PrescriptionRemarks: str
    Status: Optional[str] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class RefPatientPrescriptionCreate(RefPatientPrescriptionBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})

class RefPatientPrescriptionUpdate(RefPatientPrescriptionBase):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "1"})


class RefPatientPrescription(RefPatientPrescriptionBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})
    model_config = {"from_attributes": True}