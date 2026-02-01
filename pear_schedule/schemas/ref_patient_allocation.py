from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class RefPatientAllocationBase(BaseModel):
    """Base schema for ref patient allocation with common fields"""
    patient_id: int = Field(..., description="Patient ID")
    doctor_id: str = Field(..., max_length=255, description="Doctor ID")
    game_therapist_id: str = Field(..., max_length=255, description="Game Therapist ID")
    supervisor_id: str = Field(..., max_length=255, description="Supervisor ID")
    caregiver_id: str = Field(..., max_length=255, description="Caregiver ID")
    temp_doctor_id: Optional[str] = Field(None, max_length=255, description="Temporary Doctor ID")
    temp_caregiver_id: Optional[str] = Field(None, max_length=255, description="Temporary Caregiver ID")


class RefPatientAllocationCreate(RefPatientAllocationBase):
    """Schema for creating a new ref patient allocation - includes id for message queue operations"""
    id: int = Field(..., description="Patient Allocation ID from source system")
    active: str = Field(default="Y", pattern="^[YN]$", description="Active status: Y or N")
    is_deleted: str = Field(default="0", pattern="^[01]$", description="Deletion status: 0 or 1")
    created_date: datetime = Field(..., description="Creation timestamp")
    modified_date: datetime = Field(..., description="Last modification timestamp")
    created_by_id: str = Field(..., max_length=50, description="Creator user/service ID")
    modified_by_id: str = Field(..., max_length=50, description="Last modifier user/service ID")


class RefPatientAllocationUpdate(BaseModel):
    """Schema for updating an existing ref patient allocation"""
    patient_id: Optional[int] = None
    doctor_id: Optional[str] = Field(None, max_length=255)
    game_therapist_id: Optional[str] = Field(None, max_length=255)
    supervisor_id: Optional[str] = Field(None, max_length=255)
    caregiver_id: Optional[str] = Field(None, max_length=255)
    temp_doctor_id: Optional[str] = Field(None, max_length=255)
    temp_caregiver_id: Optional[str] = Field(None, max_length=255)
    active: Optional[str] = Field(None, pattern="^[YN]$")
    is_deleted: Optional[str] = Field(None, pattern="^[01]$")
    modified_date: datetime = Field(..., description="Last modification timestamp")
    modified_by_id: str = Field(..., max_length=50, description="Modifier user/service ID")


class RefPatientAllocationDelete(BaseModel):
    """Schema for soft-deleting a ref patient allocation"""
    modified_date: datetime = Field(..., description="Deletion timestamp")
    modified_by_id: str = Field(..., max_length=50, description="Deleter user/service ID")


class RefPatientAllocation(RefPatientAllocationBase):
    """Schema for ref patient allocation response"""
    id: int
    active: str = Field(default="Y", pattern="^[YN]$")
    is_deleted: str = Field(default="0", pattern="^[01]$")
    created_date: datetime
    modified_date: datetime
    created_by_id: str
    modified_by_id: str
    
    model_config = ConfigDict(from_attributes=True)