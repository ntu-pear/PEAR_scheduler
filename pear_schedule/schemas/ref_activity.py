from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional

class RefActivityBase(BaseModel):
    ActivityTitle: Optional[str] = None
    ActivityDesc: Optional[str] = None
    StartDate: datetime 
    EndDate: datetime
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefActivityCreate(RefActivityBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "activity_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefActivityUpdate(BaseModel):
    ActivityTitle: Optional[str] = None
    ActivityDesc: Optional[str] = None
    StartDate: Optional[datetime] = None
    EndDate: Optional[datetime] = None
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefActivity(RefActivityBase):
    ActivityID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "activity_service"})
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})
    
    model_config = ConfigDict(from_attributes=True)
