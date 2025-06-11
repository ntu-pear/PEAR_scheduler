from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
import re

class RefActivityBase(BaseModel):
    Id: int
    Title: str
    Desc: str
    StartDate: datetime 
    EndDate: Optional[datetime] = None
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})

class RefActivityCreate(RefActivityBase):
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})

class RefActivityUpdate(RefActivityBase):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "1"})


class RefActivity(RefActivityBase):
    IncludeInScheduled: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime 
    CreatedById: str = Field(json_schema_extra={"example": "1"})
    ModifiedById: str = Field(json_schema_extra={"example": "1"})
    model_config = {"from_attributes": True}