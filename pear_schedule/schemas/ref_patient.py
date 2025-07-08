from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
import re

class RefPatientBase(BaseModel):
    Id: int
    Name: str
    PreferredName: Optional[str] = None
    UpdateBit: str = Field(..., pattern="^[01]$", json_schema_extra={"example": "1"})
    StartDate: datetime
    EndDate: Optional[datetime] = None
    IsActive: str = Field(..., pattern="^[01]$", json_schema_extra={"example": "1"})
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class RefPatientCreate(RefPatientBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})

class RefPatientUpdate(RefPatientBase):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "1"})


class RefPatient(RefPatientBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})
    model_config = {"from_attributes": True}