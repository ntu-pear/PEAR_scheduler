from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from datetime import datetime
from ..database import Base
from enum import Enum
import uuid

class MessageProcessingResult(Enum):
    """Result of message processing for proper acknowledgment"""
    SUCCESS = "success"
    DUPLICATE = "duplicate"  # Already processed (idempotent)
    FAILED_RETRYABLE = "failed_retryable"  # Temporary failure, can retry
    FAILED_PERMANENT = "failed_permanent"  # Permanent failure, send to DLQ


class ProcessedEvent(Base):
    """
    Table to track processed events for idempotency and traceability.
    Prevents duplicate processing of events using correlation_id from outbox pattern.
    """
    __tablename__ = "PROCESSED_EVENTS"
    
    correlation_id = Column(
        String(36),  # UUID format: 8-4-4-4-12 characters
        primary_key=True,
        nullable=False,
        comment="Correlation ID from outbox service - ensures idempotency"
    )
    event_type = Column(
        String(100), 
        nullable=False,
        comment="Type of event processed (e.g., PATIENT_CREATED, PATIENT_UPDATED)"
    )
    
    aggregate_id = Column(
        String(50),
        nullable=False,
        comment="Entity ID that was affected (e.g., patient ID)"
    )
    processed_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        comment="When the event was processed"
    )
    processed_by = Column(
        String(100),
        nullable=False,
        comment="Service/user that processed the event"
    )
    # Optional: Store the operation result for debugging
    operation_result = Column(
        Text,
        nullable=True,
        comment="Optional: JSON of the operation result for debugging"
    )
    
    # Optional: Store error information if processing partially failed
    error_message = Column(
        Text,
        nullable=True,
        comment="Error message if processing had issues (but was still marked as processed)"
    )

    def __repr__(self):
        return f"<ProcessedEvent(correlation_id='{self.correlation_id}', event_type='{self.event_type}', aggregate_id='{self.aggregate_id}')>"

    @classmethod
    def create_from_correlation_id(
        cls, 
        correlation_id: str, 
        event_type: str, 
        aggregate_id: str, 
        processed_by: str,
        operation_result: str = None,
        error_message: str = None
    ):
        """
        Factory method to create a ProcessedEvent record.
        
        Args:
            correlation_id: The correlation ID from the outbox event
            event_type: Type of event (e.g., 'PATIENT_CREATED')
            aggregate_id: The entity ID that was processed
            processed_by: Who/what processed this event
            operation_result: Optional JSON string of operation result
            error_message: Optional error message
        """
        return cls(
            correlation_id=correlation_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            processed_by=processed_by,
            operation_result=operation_result,
            error_message=error_message,
            processed_at=datetime.now()
        )


# Create indexes for better performance
# Index on processed_at for cleanup operations
Index('IX_PROCESSED_EVENTS_processed_at', ProcessedEvent.processed_at)

# Index on event_type for filtering/debugging
Index('IX_PROCESSED_EVENTS_event_type', ProcessedEvent.event_type)

# Index on aggregate_id for finding all events related to an entity
Index('IX_PROCESSED_EVENTS_aggregate_id', ProcessedEvent.aggregate_id)

# Composite index for common query patterns
Index('IX_PROCESSED_EVENTS_event_type_aggregate_id', ProcessedEvent.event_type, ProcessedEvent.aggregate_id)
