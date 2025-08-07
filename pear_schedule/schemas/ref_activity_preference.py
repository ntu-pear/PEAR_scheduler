from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefActivityPreferenceBase(BaseModel):
    PatientId: int
    ActivityId: int
    IsLike: str = Field(default="0", pattern="^[01]$", json_schema_extra={"example": "0"})
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefActivityPreferenceCreate(RefActivityPreferenceBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityPreferenceUpdate(BaseModel):
    PatientId: Optional[int] = None
    ActivityId: Optional[int] = None
    IsLike: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "0"})
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityPreference(RefActivityPreferenceBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
