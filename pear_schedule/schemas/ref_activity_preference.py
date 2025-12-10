from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RefActivityPreferenceBase(BaseModel):
    PatientID: int
    CentreActivityID: int
    IsLike: str = Field(default="0", pattern=r"^(0|1|-1)$", json_schema_extra={"example": "0"})
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class RefActivityPreferenceCreate(RefActivityPreferenceBase):
    CentreActivityPreferenceID: int # Include CentreActivityPreferenceID for message queue synchronization
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})

class RefActivityPreferenceUpdate(BaseModel):
    PatientID: Optional[int] = None
    CentreActivityID: Optional[int] = None
    IsDeleted: Optional[bool] # DriftSync will update isdeleted if there are discrepency with delete records
    IsLike: Optional[str] = Field(None, pattern=r"^(0|1|-1)$", json_schema_extra={"example": "0"})
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})

class RefActivityPreferenceDelete(BaseModel):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})

class RefActivityPreference(RefActivityPreferenceBase):
    CentreActivityPreferenceID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
