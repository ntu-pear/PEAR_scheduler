from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pear_schedule.database import Base

class RefActivityPreference(Base):
    __tablename__ = "REF_ACTIVITY_PREFERENCE"

    Id = Column(Integer, primary_key=True, index=True) 
    IsDeleted = Column(String(1), default='0', nullable=False)
    PatientId = Column(Integer, ForeignKey('REF_PATIENT.Id')) 
    ActivityId = Column(Integer, ForeignKey('REF_ACTIVITY.Id'))
    IsLike = Column(String(1), default='0', nullable=False)

    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False) 
    ModifiedById = Column(String, nullable=False)  

    patient = relationship("RefPatient", back_populates="preferences")
    activity = relationship("RefActivity", back_populates="preferences")