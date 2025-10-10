from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefActivityRoutineBase(BaseModel):
    PatientId: int
    ActivityId: int
    IncludeInSchedule: str = Field(default="1", pattern="^[01]$", json_schema_extra={"example": "1"})
    RoutineIssues: Optional[str] = None
    RoutineTimeSlots: Optional[str] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefActivityRoutineCreate(RefActivityRoutineBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityRoutineUpdate(BaseModel):
    PatientId: Optional[int] = None
    ActivityId: Optional[int] = None
    IsDeleted: Optional[bool] # DriftSync will update isdeleted if there are discrepency with delete records
    IncludeInSchedule: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "1"})
    RoutineIssues: Optional[str] = None
    RoutineTimeSlots: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityRoutineDelete(BaseModel):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefActivityRoutine(RefActivityRoutineBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
