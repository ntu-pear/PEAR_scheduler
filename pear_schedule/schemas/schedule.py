from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class ScheduleBase(BaseModel):
    PatientId: int
    StartDate: datetime 
    EndDate: datetime
    Monday: Optional[str] = ""
    Tuesday: Optional[str] = ""
    Wednesday: Optional[str] = ""
    Thursday: Optional[str] = ""
    Friday: Optional[str] = ""
    Saturday: Optional[str] = ""
    Sunday: Optional[str] = ""
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class ScheduleCreate(ScheduleBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class ScheduleUpdate(BaseModel):
    PatientId: Optional[int] = None
    StartDate: Optional[datetime] = None
    EndDate: Optional[datetime] = None
    Monday: Optional[str] = None
    Tuesday: Optional[str] = None
    Wednesday: Optional[str] = None
    Thursday: Optional[str] = None
    Friday: Optional[str] = None
    Saturday: Optional[str] = None
    Sunday: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class Schedule(ScheduleBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
