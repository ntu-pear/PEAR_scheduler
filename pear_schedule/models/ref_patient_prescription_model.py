from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pear_schedule.database import Base

class RefPatientPrescription(Base):
    __tablename__ = "REF_PATIENT_PRESCRIPTION"

    Id = Column(Integer, primary_key=True, index=True)
    IsDeleted = Column(String(1), default='1', nullable=False)
    PatientId = Column(Integer, ForeignKey('REF_PATIENT.Id'))
    PrescriptionListValue = Column(String(255))
    Dosage = Column(String(255), nullable=False)
    FrequencyPerDay = Column(BigInteger, nullable=False)
    Instruction = Column(String(255), nullable=False)
    StartDate = Column(DateTime, nullable=False)
    EndDate = Column(DateTime)
    IsAfterMeal = Column(String(1))
    PrescriptionRemarks = Column(String(255), nullable=False)
    Status = Column(String(255), nullable=False)
    
    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False) 
    ModifiedById = Column(String, nullable=False)  

    patient = relationship("RefPatient", back_populates="prescriptions")