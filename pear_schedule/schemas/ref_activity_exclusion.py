from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
import re

class RefActivityExclusionBase(BaseModel):
    PatientId: int
    ActivityId: int
    StartDate: datetime 
    EndDate: Optional[datetime] = None
    ExclusionRemarks: Optional[str] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class RefActivityExclusionCreate(RefActivityExclusionBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})

class RefActivityExclusionUpdate(RefActivityExclusionBase):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "1"})


class RefActivityExclusion(RefActivityExclusionBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})
    model_config = {"from_attributes": True}