from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date
from typing import Optional

class RefCentreActivityBase(BaseModel):
    CentreActivityID: int
    ActivityID: int # foreign key reference to RefActivity
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})
    IsCompulsory: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})
    IsFixed: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})
    IsGroup: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})
    StartDate: date
    EndDate: Optional[date] = None
    MinDuration: int = Field(gt=0)
    MaxDuration: int = Field(gt=0)
    MinPeopleReq: int = Field(ge=1)
    FixedTimeSlots: Optional[str] = None


class RefCentreActivityCreate(RefCentreActivityBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "activity_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefCentreActivityUpdate(BaseModel):
    ActivityID: Optional[int] = None
    IsDeleted: Optional[str] = Field(default=None, json_schema_extra={"example": "0"})
    IsCompulsory: Optional[str] = Field(default=None, json_schema_extra={"example": "0"})
    IsFixed: Optional[str] = Field(default=None, json_schema_extra={"example": "0"})
    IsGroup: Optional[str] = Field(default=None, json_schema_extra={"example": "0"})
    StartDate: Optional[date] = None
    EndDate: Optional[date] = None
    MinDuration: Optional[int] = Field(default=None, gt=0, description="Minimum duration in minutes")
    MaxDuration: Optional[int] = Field(default=None, gt=0, description="Maximum duration in minutes")
    MinPeopleReq: Optional[int] = Field(default=None, ge=1, description="Minimum people required")
    FixedTimeSlots: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefCentreActivity(RefCentreActivityBase):
    CentreActivityID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "activity_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})
    
    model_config = ConfigDict(from_attributes=True)