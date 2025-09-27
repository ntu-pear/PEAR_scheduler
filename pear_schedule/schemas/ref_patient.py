from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefPatientBase(BaseModel):
    Name: str
    PreferredName: Optional[str] = None
    UpdateBit: str = Field(default="1", pattern="^[01]$", json_schema_extra={"example": "1"})
    StartDate: datetime
    EndDate: Optional[datetime] = None
    IsActive: str = Field(default="1", pattern="^[01]$", json_schema_extra={"example": "1"})


class RefPatientCreate(RefPatientBase):
    """Schema for creating a new ref patient - includes Id for message queue operations"""
    PatientID: int  # Include Id for message queue synchronization
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefPatientUpdate(BaseModel):
    """Schema for updating an existing ref patient"""
    Name: Optional[str] = None
    PreferredName: Optional[str] = None
    UpdateBit: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "1"})
    StartDate: Optional[datetime] = None
    EndDate: Optional[datetime] = None
    IsActive: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "1"})
    IsDeleted: Optional[str] = Field(None, json_schema_extra={"example": "0"})
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefPatientDelete(BaseModel):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefPatient(RefPatientBase):
    """Schema for ref patient response"""
    PatientID: int
    IsDeleted: str = Field(default="0")
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
