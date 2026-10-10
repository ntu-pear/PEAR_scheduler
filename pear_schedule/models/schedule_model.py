from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.dialects.mssql import VARCHAR, NVARCHAR
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pear_schedule.database import Base

class Schedule(Base):
    __tablename__ = "SCHEDULE"

    ScheduleID = Column(Integer, primary_key=True, index=True) 
    IsDeleted = Column(String(1), default='0', nullable=False)
    PatientID = Column(Integer, ForeignKey('REF_PATIENT.PatientID')) 
    StartDate = Column(DateTime, nullable=False, default=datetime.now)
    EndDate = Column(DateTime, nullable=False, default=datetime.now)
    Monday = Column(VARCHAR("max"))
    Tuesday = Column(VARCHAR("max"))
    Wednesday = Column(VARCHAR("max"))
    Thursday = Column(VARCHAR("max"))
    Friday = Column(VARCHAR("max"))
    Saturday = Column(VARCHAR("max"))
    Sunday = Column(VARCHAR("max"))
    MedicationSchedule = Column(NVARCHAR("max"))
    MedicationLog = Column(NVARCHAR("max"))
    

    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False) 
    ModifiedById = Column(String, nullable=False)