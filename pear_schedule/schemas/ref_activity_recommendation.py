from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefActivityRecommendationBase(BaseModel):
    PatientID: int
    CentreActivityID: int
    DoctorID: Optional[str] = None
    DoctorRecommendation: str = Field(default="1", pattern=r"^(0|1|-1)$", json_schema_extra={"example": "1"})
    DoctorRemarks: Optional[str] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefActivityRecommendationCreate(RefActivityRecommendationBase):
    CentreActivityRecommendationID: int # Include CentreActivityRecommendationID for message queue synchronization
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityRecommendationUpdate(BaseModel):
    PatientID: Optional[int] = None
    CentreActivityID: Optional[int] = None
    DoctorID: Optional[str] = None
    DoctorRecommendation: Optional[str] = Field(None, pattern=r"^(0|1|-1)$", json_schema_extra={"example": "1"})
    DoctorRemarks: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityRecommendation(RefActivityRecommendationBase):
    CentreActivityRecommendationID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
