from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefActivityExclusionBase(BaseModel):
    PatientId: int
    ActivityId: int
    StartDate: datetime 
    EndDate: datetime
    ExclusionRemarks: Optional[str] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefActivityExclusionCreate(RefActivityExclusionBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityExclusionUpdate(BaseModel):
    PatientId: Optional[int] = None
    ActivityId: Optional[int] = None
    StartDate: Optional[datetime] = None
    EndDate: Optional[datetime] = None
    ExclusionRemarks: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityExclusion(RefActivityExclusionBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
