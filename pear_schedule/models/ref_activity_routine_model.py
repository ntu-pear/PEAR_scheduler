from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pear_schedule.database import Base

class RefActivityRoutine(Base):
    __tablename__ = "REF_ACTIVITY_ROUTINE"

    Id = Column(Integer, primary_key=True, index=True) 
    IsDeleted = Column(String(1), default='0', nullable=False)
    PatientId = Column(Integer, ForeignKey('REF_PATIENT.Id')) 
    ActivityId = Column(Integer, ForeignKey('REF_ACTIVITY.Id'))
    IncludeInSchedule = Column(String(1), default='1', nullable=False)
    RoutineIssues = Column(String(255))
    RoutineTimeSlots = Column(String(255))

    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False) 
    ModifiedById = Column(String, nullable=False)  

    patient = relationship("RefPatient", back_populates="routines")
    activity = relationship("RefActivity", back_populates="routines")