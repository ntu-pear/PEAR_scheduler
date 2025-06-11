from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
import re

class RefActivityRecommendationBase(BaseModel):
    PatientId: int
    ActivityId: int
    DoctorId: str
    DoctorRecommendation: str = "0"
    DoctorRemarks: str
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class RefActivityRecommendationCreate(RefActivityRecommendationBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})

class RefActivityRecommendationUpdate(RefActivityRecommendationBase):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "1"})


class RefActivityRecommendation(RefActivityRecommendationBase):
    Id: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})
    model_config = {"from_attributes": True}