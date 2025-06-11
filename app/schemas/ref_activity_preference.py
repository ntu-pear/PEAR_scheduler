from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
import re

class RefActivityPreferenceBase(BaseModel):
    PatientId: int
    ActivityId: int
    IsLike: str = "0"
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class RefActivityPreferenceCreate(RefActivityPreferenceBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})

class RefActivityPreferenceUpdate(RefActivityPreferenceBase):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "1"})


class RefActivityPreference(RefActivityPreferenceBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})
    model_config = {"from_attributes": True}