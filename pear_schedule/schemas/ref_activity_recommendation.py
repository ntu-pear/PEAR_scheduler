from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefActivityRecommendationBase(BaseModel):
    PatientId: int
    ActivityId: int
    DoctorId: Optional[str] = None
    DoctorRecommendation: str = Field(default="1", pattern="^[01]$", json_schema_extra={"example": "1"})
    DoctorRemarks: Optional[str] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefActivityRecommendationCreate(RefActivityRecommendationBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityRecommendationUpdate(BaseModel):
    PatientId: Optional[int] = None
    ActivityId: Optional[int] = None
    DoctorId: Optional[str] = None
    DoctorRecommendation: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "1"})
    DoctorRemarks: Optional[str] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})


class RefActivityRecommendation(RefActivityRecommendationBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "scheduler_service"})
    
    model_config = ConfigDict(from_attributes=True)
