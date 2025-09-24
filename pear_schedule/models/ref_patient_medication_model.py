from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pear_schedule.database import Base

class RefPatientMedication(Base):
    __tablename__ = "REF_PATIENT_MEDICATION"

    MedicationID = Column(Integer, primary_key=True, index=True)
    IsDeleted = Column(String(1), default='1', nullable=False)
    PatientID = Column(Integer, ForeignKey('REF_PATIENT.PatientID'))
    PrescriptionName = Column(String(255))
    Dosage = Column(String(255), nullable=False)
    AdministerTime = Column(String(255), nullable=False)
    Instruction = Column(String(255), nullable=False)
    StartDateTime = Column(DateTime, nullable=False)
    EndDateTime = Column(DateTime)
    PrescriptionRemarks = Column(String(255), nullable=False)
    
    CreatedDateTime = Column(DateTime, nullable=False)
    UpdatedDateTime = Column(DateTime, nullable=False)
    CreatedById = Column(String, nullable=False) 
    ModifiedById = Column(String, nullable=False)  

    patient = relationship("RefPatient", back_populates="medications")