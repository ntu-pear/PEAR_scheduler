from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from pear_schedule.database import Base
from datetime import datetime, timezone


class RefPatient(Base):
    __tablename__ = "REF_PATIENT"

    PatientID = Column(Integer, primary_key=True, index=True)
    IsDeleted = Column(String(1), default='0', nullable=False)
    Name = Column(String(255), nullable=False)
    PreferredName = Column(String(255))
    UpdateBit = Column(String(1), default="1", nullable=False)
    StartDate = Column(DateTime, nullable=False)
    EndDate = Column(DateTime)
    IsActive = Column(String(1), default="1", nullable=False)


    exclusions = relationship("RefActivityExclusion", back_populates="patient")
    preferences = relationship("RefActivityPreference", back_populates="patient")
    recommendations = relationship("RefActivityRecommendation", back_populates="patient")
    routines = relationship("RefActivityRoutine", back_populates="patient")
    medications = relationship("RefPatientMedication", back_populates="patient")
