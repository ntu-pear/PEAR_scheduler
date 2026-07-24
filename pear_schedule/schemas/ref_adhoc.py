from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date
from typing import Optional


class RefAdhocBase(BaseModel):
    PatientID: int
    OldCentreActivityID: int
    NewCentreActivityID: int
    StartDate: date
    EndDate: date
    Status: str
    IsDeleted: Optional[str] = Field(default="0", json_schema_extra={"example": "0"})


class RefAdhocCreate(RefAdhocBase):
    AdhocID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(default="activity_service", json_schema_extra={"example": "activity_service"})
    ModifiedById: str = Field(default="activity_service", json_schema_extra={"example": "activity_service"})


class RefAdhocUpdate(BaseModel):
    PatientID: Optional[int] = None
    OldCentreActivityID: Optional[int] = None
    NewCentreActivityID: Optional[int] = None
    StartDate: Optional[date] = None
    EndDate: Optional[date] = None
    Status: str = None
    IsDeleted: Optional[str] = Field(None, pattern="^[01]$", json_schema_extra={"example": "0"})
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefAdhocDelete(BaseModel):
    UpdatedDateTime: datetime
    ModifiedById: str = Field(json_schema_extra={"example": "activity_service"})


class RefAdhoc(RefAdhocBase):
    AdhocID: int
    CreatedDateTime: datetime
    UpdatedDateTime: datetime
    CreatedById: str = Field(default="activity_service", json_schema_extra={"example": "activity_service"})
    ModifiedById: str = Field(default="activity_service", json_schema_extra={"example": "activity_service"})

    model_config = ConfigDict(from_attributes=True)
