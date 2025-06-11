from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base

class RefActivity(Base):
    __tablename__ = "REF_ACTIVITY"

    Id = Column(Integer, primary_key=True, index=True)
    IsDeleted = Column(String(1), default='0', nullable=False)
    ActivityTitle = Column(String(255))
    ActivityDesc = Column(String(255))
    StartDate = Column(DateTime, nullable=False, default=datetime.now)
    EndDate = Column(DateTime, nullable=False, default=datetime.now)

    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False)
    ModifiedById = Column(String, nullable=False) 

    exclusions = relationship("RefActivityExclusion", back_populates="activity")
    preferences = relationship("RefActivityPreference", back_populates="activity")
    recommendations = relationship("RefActivityRecommendation", back_populates="activity")
    routines = relationship("RefActivityRoutine", back_populates="activity")