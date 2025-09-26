from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date
from typing import Optional

class RefCentreActivityBase(BaseModel):
    ActivityID: int
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})
    IsCompulsory: str = Field(default="0", pattern="^[01]$", json_schema_extra={"example": "0"})
    IsFixed: str = Field(default="0", pattern="^[01]$", json_schema_extra={"example": "0"})
    IsGroup: str = Field(default="0", pattern="^[01]$", json_schema_extra={"example": "0"})
    StartDate: date
    EndDate: Optional[date] = None
    MinDuration: int = Field(default=30, json_schema_extra={"example": 30})
    MaxDuration: int = Field(default=60, json_schema_extra={"example": 60})
    MinPeopleReq: int = Field(default=1, json_schema_extra={"example": 1})
    FixedTimeSlots: Optional[str] = None


class RefCentreActivityCreate(RefCentreActivityBase):
    CentreActivityID: int  # Include CentreActivityID for message queue synchronization
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(default="activity_service", json_schema_extra={"example": "activity_service"})
    ModifiedById: str = Field(default="activity_service", json_schema_extra={"example": "activity_service"})


class RefCentreActivityUpdate(BaseModel):
    ActivityID: Optional[int] = None
    IsDeleted: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "0"})
    IsCompulsory: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "0"})
    IsFixed: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "0"})
    IsGroup: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "0"})
    StartDate: Optional[date] = None
    EndDate: Optional[date] = None
    MinDuration: Optional[int] = None
    MaxDuration: Optional[int] = None
    MinPeopleReq: Optional[int] = None
    FixedTimeSlots: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefCentreActivity(RefCentreActivityBase):
    CentreActivityID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(default="activity_service", json_schema_extra={"example": "activity_service"})
    ModifiedById: str = Field(default="activity_service", json_schema_extra={"example": "activity_service"})
    
    model_config = ConfigDict(from_attributes=True)
