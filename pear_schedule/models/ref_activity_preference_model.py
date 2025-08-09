from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pear_schedule.database import Base

class RefActivityPreference(Base):
    __tablename__ = "REF_ACTIVITY_PREFERENCE"

    CentreActivityPreferenceID = Column(Integer, primary_key=True, index=True) 
    IsDeleted = Column(String(1), default='0', nullable=False)
    PatientID = Column(Integer, ForeignKey('REF_PATIENT.PatientID')) 
    CentreActivityID = Column(Integer, ForeignKey('REF_CENTRE_ACTIVITY.CentreActivityID'))
    IsLike = Column(String(2), default='0', nullable=False)

    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False) 
    ModifiedById = Column(String, nullable=False)  

    patient = relationship("RefPatient", back_populates="preferences")
    centre_activity = relationship("RefCentreActivity", back_populates="preferences")