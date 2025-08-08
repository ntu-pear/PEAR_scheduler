from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from pear_schedule.database import Base

class RefCentreActivity(Base):
    __tablename__ = "REF_CENTRE_ACTIVITY"

    Id = Column(Integer, primary_key=True, index=True)
    ActivityId = Column(Integer, ForeignKey('REF_ACTIVITY.Id'), nullable=False)
    IsDeleted = Column(String(1), default='0', nullable=False)
    IsCompulsory = Column(String(1), default='0', nullable=False)
    IsFixed = Column(String(1), default='0', nullable=False) 
    IsGroup = Column(String(1), default='0', nullable=False)
    StartDate = Column(Date, nullable=False)
    EndDate = Column(Date, nullable=True)
    MinDuration = Column(Integer, nullable=False)
    MaxDuration = Column(Integer, nullable=False)
    MinPeopleReq = Column(Integer, nullable=False)
    FixedTimeSlots = Column(String, nullable=True)
    
    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=True, default=datetime.now)
    CreatedById = Column(String, nullable=False)
    ModifiedById = Column(String, nullable=True)

    # Relationships
    activity = relationship("RefActivity", back_populates="centre_activities")
    preferences = relationship("RefActivityPreference", back_populates="centre_activity")
    recommendations = relationship("RefActivityRecommendation", back_populates="centre_activity")
