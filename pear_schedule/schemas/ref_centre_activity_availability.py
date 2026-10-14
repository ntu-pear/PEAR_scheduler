from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date, time
from typing import Optional

class RefCentreActivityAvailabilityBase(BaseModel):
    CentreActivityID: int
    DaysOfWeek: int
    StartTime: time
    EndTime: time
    StartDate: Optional[date] = None
    EndDate: Optional[date] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefCentreActivityAvailabilityCreate(RefCentreActivityAvailabilityBase):
    CentreActivityAvailabilityID: int # Source ID from the activity service for message queue synchronization
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: Optional[str] = Field(default=None, json_schema_extra={"example": "scheduler_service"})


class RefCentreActivityAvailabilityUpdate(BaseModel):
    CentreActivityID: Optional[int] = None
    DaysOfWeek: Optional[int] = None
    StartTime: Optional[time] = None
    EndTime: Optional[time] = None
    StartDate: Optional[date] = None
    EndDate: Optional[date] = None
    IsDeleted: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefCentreActivityAvailabilityDelete(BaseModel):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefCentreActivityAvailability(RefCentreActivityAvailabilityBase):
    CentreActivityAvailabilityID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: Optional[str] = Field(default=None, json_schema_extra={"example": "scheduler_service"})

    model_config = ConfigDict(from_attributes=True)
