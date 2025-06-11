from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
import re

class ScheduleBase(BaseModel):
    PatientId: int
    StartDate: datetime 
    EndDate: datetime
    Monday: str
    Tuesday: str
    Wednesday: str
    Thursday: str
    Friday: str
    Saturday: str
    Sunday: str
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class ScheduleCreate(ScheduleBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})

class ScheduleUpdate(ScheduleBase):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "1"})


class Schedule(ScheduleBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})
    model_config = {"from_attributes": True}