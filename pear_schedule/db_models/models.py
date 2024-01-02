## NOT USED: ONLY IF WE NEED TO MANUALLY CREATE AND ALTER THE TABLES

from sqlalchemy import Column, Integer, DateTime, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Schedule(Base):
    __tablename__ = 'Schedule'

    ScheduleID = Column(Integer, primary_key=True)
    PatientID = Column(Integer)  
    # PatientID = Column(Integer, ForeignKey('Patient.PatientID'))  

    StartDate = Column(DateTime)
    EndDate = Column(DateTime)
    Monday = Column(String)
    Tuesday = Column(String)
    Wednesday = Column(String)
    Thursday = Column(String)
    Friday = Column(String)
    
    IsDeleted = Column(Integer)
    CreatedDateTime = Column(DateTime)
    UpdatedDateTime = Column(DateTime)

