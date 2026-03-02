from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.mssql import VARCHAR
from pear_schedule.database import Base

class MedicationSchedule(Base):
    __tablename__ = "MEDICATION_SCHEDULE"

    MedicationID = Column(Integer, ForeignKey('REF_PATIENT_MEDICATION.MedicationID'), primary_key=True)
    ScheduleID = Column(Integer, ForeignKey('SCHEDULE.ScheduleID'), primary_key=True)
    AdministerDate = Column(DateTime, primary_key=True)
    AdministerTime = Column(String(255), primary_key=True)
    AssignedTo = Column(VARCHAR("max"))
    Status = Column(String(1), default='0', nullable=False)
    ActualAdministerTime = Column(DateTime, nullable=True)
    AdministeredBy = Column(VARCHAR("max"), nullable=True)