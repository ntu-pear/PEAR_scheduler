from sqlalchemy import Column, Integer, String, Date, Time, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from pear_schedule.database import Base

class RefCentreActivityAvailability(Base):
    __tablename__ = "REF_CENTRE_ACTIVITY_AVAILABILITY"

    CentreActivityAvailabilityID = Column(Integer, primary_key=True, index=True, autoincrement=False)
    CentreActivityID = Column(Integer, ForeignKey('REF_CENTRE_ACTIVITY.CentreActivityID'), nullable=False)
    IsDeleted = Column(String(1), default='0', nullable=False)
    # Bitmask: 1=Mon, 2=Tue, 4=Wed, 8=Thu, 16=Fri, 32=Sat, 64=Sun
    DaysOfWeek = Column(Integer, nullable=False, default=0)
    StartTime = Column(Time, nullable=False)
    EndTime = Column(Time, nullable=False)
    StartDate = Column(Date, nullable=True)
    EndDate = Column(Date, nullable=True)

    CreatedDateTime = Column(DateTime, nullable=False)
    UpdatedDateTime = Column(DateTime, nullable=False)
    CreatedById = Column(String, nullable=False)
    ModifiedById = Column(String, nullable=True)

    centre_activity = relationship("RefCentreActivity", back_populates="availabilities")
