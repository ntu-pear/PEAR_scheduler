from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefPatientMedicationBase(BaseModel):
    PatientID: int
    PrescriptionName: Optional[str] = None
    Dosage: str
    AdministerTime: str
    Instruction: str
    StartDate: datetime
    EndDate: Optional[datetime] = None
    PrescriptionRemarks: str
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefPatientMedicationCreate(RefPatientMedicationBase):
    MedicationID: int  # Include MedicationID for message queue synchronization
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefPatientMedicationUpdate(BaseModel):
    PatientID: Optional[int] = None
    PrescriptionName: Optional[str] = None
    Dosage: Optional[str] = None
    AdministerTime: str
    Instruction: Optional[str] = None
    StartDate: Optional[datetime] = None
    EndDate: Optional[datetime] = None
    PrescriptionRemarks: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefPatientMedication(RefPatientMedicationBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
