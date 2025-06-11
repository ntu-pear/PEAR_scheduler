from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base

class Schedule(Base):
    __tablename__ = "SCHEDULE"

    Id = Column(Integer, primary_key=True, index=True) 
    IsDeleted = Column(String(1), default='0', nullable=False)
    PatientId = Column(Integer, ForeignKey('REF_PATIENT.Id')) 
    StartDate = Column(DateTime, nullable=False, default=datetime.now)
    EndDate = Column(DateTime, nullable=False, default=datetime.now)
    Monday = Column(String(255))
    Tuesday = Column(String(255))
    Wednesday = Column(String(255))
    Thursday = Column(String(255))
    Friday = Column(String(255))
    Saturday = Column(String(255))
    Sunday = Column(String(255))
    

    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False) 
    ModifiedById = Column(String, nullable=False)  