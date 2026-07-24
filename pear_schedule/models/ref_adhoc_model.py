from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from pear_schedule.database import Base


class RefAdhoc(Base):
    __tablename__ = "REF_ADHOC"

    AdhocID = Column(Integer, primary_key=True, index=True)
    PatientID = Column(Integer, ForeignKey("REF_PATIENT.PatientID"), nullable=False)
    OldCentreActivityID = Column(Integer, ForeignKey("REF_CENTRE_ACTIVITY.CentreActivityID"), nullable=False)
    NewCentreActivityID = Column(Integer, ForeignKey("REF_CENTRE_ACTIVITY.CentreActivityID"), nullable=False)
    StartDate = Column(Date, nullable=False)
    EndDate = Column(Date, nullable=False)
    Status = Column(String, nullable=False)
    IsDeleted = Column(String(1), default="0", nullable=False)

    CreatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    UpdatedDateTime = Column(DateTime, nullable=False, default=datetime.now)
    CreatedById = Column(String, nullable=False)
    ModifiedById = Column(String, nullable=True)

    # Relationships
    patient = relationship("RefPatient", foreign_keys=[PatientID])
    old_centre_activity = relationship("RefCentreActivity", foreign_keys=[OldCentreActivityID])
    new_centre_activity = relationship("RefCentreActivity", foreign_keys=[NewCentreActivityID])
