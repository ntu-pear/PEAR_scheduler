from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pear_schedule.database import Base

class RefActivity(Base):
    __tablename__ = "REF_ACTIVITY"

    ActivityID = Column(Integer, primary_key=True, index=True)
    IsDeleted = Column(String(1), default='0', nullable=False)
    ActivityTitle = Column(String(255))
    ActivityDesc = Column(String(255))

    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False)
    ModifiedById = Column(String, nullable=False) 

    exclusions = relationship("RefActivityExclusion", back_populates="activity", foreign_keys="[RefActivityExclusion.ActivityExclusionID]")
    routines = relationship("RefActivityRoutine", back_populates="activity", foreign_keys="[RefActivityRoutine.RoutineID]")
    centre_activities = relationship("RefCentreActivity", back_populates="activity", foreign_keys="[RefCentreActivity.CentreActivityID]")