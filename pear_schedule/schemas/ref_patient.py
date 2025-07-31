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


class RefPatientUpdate(BaseModel):
    # Only include fields that can be updated and exist in database
    Id: Optional[int] = None
    Name: Optional[str] = None
    PreferredName: Optional[str] = None
    UpdateBit: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "1"})
    StartDate: Optional[datetime] = None
    EndDate: Optional[datetime] = None
    IsActive: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "1"})
    IsDeleted: Optional[str] = Field(None, json_schema_extra={"example": "0"})
    # UpdatedDateTime: datetime
    # ModifiedById: str = Field(json_schema_extra={"example": "1"})


class RefPatient(RefPatientBase):
    model_config = {"from_attributes": True}