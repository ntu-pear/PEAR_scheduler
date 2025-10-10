from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pear_schedule.database import Base

class RefActivityExclusion(Base):
    __tablename__ = "REF_ACTIVITY_EXCLUSION"

    ActivityExclusionID = Column(Integer, primary_key=True, index=True) 
    IsDeleted = Column(String(1), default='0', nullable=False)
    PatientID = Column(Integer, ForeignKey('REF_PATIENT.PatientID')) 
    ActivityID = Column(Integer, ForeignKey('REF_ACTIVITY.ActivityID')) 
    StartDateTime = Column(DateTime, nullable=False)
    EndDateTime = Column(DateTime, nullable=False)
    ExclusionRemarks = Column(String(255))
    
    CreatedDateTime = Column(DateTime, nullable=False)
    UpdatedDateTime = Column(DateTime, nullable=False)
    CreatedById = Column(String, nullable=False) 
    ModifiedById = Column(String, nullable=False)

    patient = relationship("RefPatient", back_populates="exclusions")
    activity = relationship("RefActivity", back_populates="exclusions")