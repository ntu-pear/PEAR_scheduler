from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefActivityExclusionBase(BaseModel):
    PatientID: int
    ActivityID: int
    StartDateTime: datetime 
    EndDateTime: datetime
    ExclusionRemarks: Optional[str] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefActivityExclusionCreate(RefActivityExclusionBase):
    ActivityExclusionID: int # Include ActivityExclusionID for message queue synchronization
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityExclusionUpdate(BaseModel):
    PatientID: Optional[int] = None
    ActivityID: Optional[int] = None
    StartDateTime: Optional[datetime] = None
    EndDateTime: Optional[datetime] = None
    ExclusionRemarks: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityExclusionDelete(BaseModel):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefActivityExclusion(RefActivityExclusionBase):
    ActivityExclusionID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
