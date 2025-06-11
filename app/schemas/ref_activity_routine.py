from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
import re

class RefActivityRoutineBase(BaseModel):
    PatientId: int
    ActivityId: int
    IncludeInSchedule: str = "1"
    RoutineIssues: str
    RoutineTimeSlots: str
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class RefActivityRoutineCreate(RefActivityRoutineBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})

class RefActivityRoutineUpdate(RefActivityRoutineBase):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "1"})


class RefActivityRoutine(RefActivityRoutineBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})
    model_config = {"from_attributes": True}