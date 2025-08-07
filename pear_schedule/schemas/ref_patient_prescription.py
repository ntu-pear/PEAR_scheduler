from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefPatientPrescriptionBase(BaseModel):
    PatientId: int
    PrescriptionListValue: Optional[str] = None
    Dosage: str
    FrequencyPerDay: int
    Instruction: str
    StartDate: datetime
    EndDate: Optional[datetime] = None
    IsAfterMeal: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "0"})
    PrescriptionRemarks: str
    Status: str
    IsDeleted: Optional[str] = Field(default="1", json_schema_extra={"example": "0"})


class RefPatientPrescriptionCreate(RefPatientPrescriptionBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefPatientPrescriptionUpdate(BaseModel):
    PatientId: Optional[int] = None
    PrescriptionListValue: Optional[str] = None
    Dosage: Optional[str] = None
    FrequencyPerDay: Optional[int] = None
    Instruction: Optional[str] = None
    StartDate: Optional[datetime] = None
    EndDate: Optional[datetime] = None
    IsAfterMeal: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "0"})
    PrescriptionRemarks: Optional[str] = None
    Status: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefPatientPrescription(RefPatientPrescriptionBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
