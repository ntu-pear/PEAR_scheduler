from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Tuple, List
from datetime import datetime
import logging

from ..models.ref_adhoc_model import RefAdhoc
from ..schemas.ref_adhoc import RefAdhocCreate, RefAdhocUpdate, RefAdhocDelete
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)


def create_ref_adhoc(
    db: Session,
    adhoc: RefAdhocCreate,
    correlation_id: str,
    created_by: str,
    skip_duplicate_check: bool = False,
) -> Tuple[RefAdhoc, bool]:
    """
    Create a new adhoc activity scheduling record with idempotency protection.

    Args:
        db: Database session
        adhoc: Adhoc activity data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the adhoc record
        skip_duplicate_check: If True, bypass idempotency check (for sync events)

    Returns:
        Tuple of (Adhoc, was_duplicate: bool)

    Raises:
        ValueError: If adhoc record with same ID already exists
        Exception: For database or other errors
    """

    def create_operation():
        existing = db.query(RefAdhoc).filter(RefAdhoc.AdhocID == adhoc.AdhocID).first()
        if existing:
            raise ValueError(f"Adhoc with ID {adhoc.AdhocID} already exists. Use update operation instead.")

        logger.info(f"Creating new adhoc activity {adhoc.AdhocID} for patient {adhoc.PatientID}")

        query = text(
            """
            SET IDENTITY_INSERT [ADHOC] ON;

            INSERT INTO [ADHOC] (
                AdhocID, PatientID, OldCentreActivityID, NewCentreActivityID,
                StartDate, EndDate, Status, IsDeleted,
                CreatedDateTime, UpdatedDateTime, CreatedById, ModifiedById
            ) VALUES (
                :AdhocID, :PatientID, :OldCentreActivityID, :NewCentreActivityID,
                :StartDate, :EndDate, :Status, :IsDeleted,
                :CreatedDateTime, :UpdatedDateTime, :CreatedById, :ModifiedById
            );

            SET IDENTITY_INSERT [ADHOC] OFF;
        """
        )

        params = {
            "AdhocID": adhoc.AdhocID,
            "PatientID": adhoc.PatientID,
            "OldCentreActivityID": adhoc.OldCentreActivityID,
            "NewCentreActivityID": adhoc.NewCentreActivityID,
            "StartDate": adhoc.StartDate,
            "EndDate": adhoc.EndDate,
            "Status": adhoc.Status,
            "IsDeleted": adhoc.IsDeleted or "0",
            "CreatedDateTime": adhoc.CreatedDateTime,
            "UpdatedDateTime": adhoc.UpdatedDateTime,
            "CreatedById": created_by,
            "ModifiedById": created_by,
        }

        db.execute(query, params)
        db.flush()

        created_adhoc = db.query(RefAdhoc).filter(RefAdhoc.AdhocID == adhoc.AdhocID).first()
        if not created_adhoc:
            raise Exception(f"Failed to create adhoc {adhoc.AdhocID}")

        return created_adhoc

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for adhoc {adhoc.AdhocID} (sync event)")
            result = create_operation()
            was_duplicate = False

            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ADHOC_CREATED",
                    aggregate_id=str(adhoc.AdhocID),
                    processed_by=f"scheduler_service_{created_by}_sync",
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ADHOC_CREATED",
                aggregate_id=str(adhoc.AdhocID),
                processed_by=f"scheduler_service_{created_by}",
                operation=create_operation,
            )

        if was_duplicate:
            existing_adhoc = db.query(RefAdhoc).filter(RefAdhoc.AdhocID == adhoc.AdhocID).first()
            logger.info(f"Duplicate create event for adhoc {adhoc.AdhocID}, returning existing")
            return existing_adhoc, True

        db.commit()
        logger.info(f"Successfully created adhoc {adhoc.AdhocID}")
        return result, False

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating adhoc {adhoc.AdhocID}: {str(e)}")
        raise


def update_ref_adhoc(
    db: Session,
    adhoc_id: int,
    adhoc_update: RefAdhocUpdate,
    correlation_id: str,
    skip_duplicate_check: bool = False,
) -> Tuple[Optional[RefAdhoc], bool]:
    """
    Update an existing adhoc activity record with idempotency protection.

    Args:
        db: Database session
        adhoc_id: ID of adhoc record to update
        adhoc_update: Fields to update (includes UpdatedDateTime and ModifiedById)
        correlation_id: Correlation ID from outbox service for deduplication
        skip_duplicate_check: If True, bypass idempotency check (for sync events)

    Returns:
        Tuple of (Adhoc or None, was_duplicate: bool)
        None if adhoc not found

    Raises:
        Exception: For database or other errors
    """

    def update_operation():
        db_adhoc = db.query(RefAdhoc).filter(RefAdhoc.AdhocID == adhoc_id).first()

        if not db_adhoc:
            logger.warning(f"Adhoc {adhoc_id} not found for update")
            return None

        logger.debug(f"Updating adhoc {adhoc_id}")

        update_data = adhoc_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_adhoc, field) and field != "AdhocID":
                setattr(db_adhoc, field, value)

        db.flush()
        return db_adhoc

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for adhoc {adhoc_id} (sync event)")
            result = update_operation()
            was_duplicate = False

            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ADHOC_UPDATED",
                    aggregate_id=str(adhoc_id),
                    processed_by=f"scheduler_service_{adhoc_update.ModifiedById}_sync",
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ADHOC_UPDATED",
                aggregate_id=str(adhoc_id),
                processed_by=f"scheduler_service_{adhoc_update.ModifiedById}",
                operation=update_operation,
            )

        if was_duplicate:
            existing_adhoc = db.query(RefAdhoc).filter(RefAdhoc.AdhocID == adhoc_id, RefAdhoc.IsDeleted == "0").first()
            logger.info(f"Duplicate update event for adhoc {adhoc_id}, returning current state")
            return existing_adhoc, True

        if result is None:
            logger.warning(f"Adhoc {adhoc_id} not found for update")
            db.commit()
            return None, False

        db.commit()
        logger.debug(f"Successfully updated adhoc {adhoc_id}")
        return result, False

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating adhoc {adhoc_id}: {str(e)}")
        raise


def delete_ref_adhoc(
    db: Session,
    adhoc_id: int,
    adhoc_delete: RefAdhocDelete,
    correlation_id: str,
    skip_duplicate_check: bool = False,
) -> Tuple[Optional[RefAdhoc], bool]:
    """
    Soft delete an adhoc activity record with idempotency protection.

    Args:
        db: Database session
        adhoc_id: ID of adhoc to delete
        adhoc_delete: Delete data including timestamp and user info
        correlation_id: Correlation ID from outbox service for deduplication
        skip_duplicate_check: If True, bypass idempotency check (for sync events)

    Returns:
        Tuple of (Adhoc or None, was_duplicate: bool)
        None if adhoc not found

    Raises:
        Exception: For database or other errors
    """

    def delete_operation():
        db_adhoc = db.query(RefAdhoc).filter(RefAdhoc.AdhocID == adhoc_id).first()

        if not db_adhoc:
            logger.warning(f"Adhoc {adhoc_id} not found for deletion")
            return None

        if db_adhoc.IsDeleted == "1":
            logger.info(f"Adhoc {adhoc_id} already deleted")
            return db_adhoc

        logger.info(f"Soft deleting adhoc {adhoc_id}")

        db_adhoc.IsDeleted = "1"
        db_adhoc.ModifiedById = adhoc_delete.ModifiedById
        db_adhoc.UpdatedDateTime = adhoc_delete.UpdatedDateTime

        db.flush()
        return db_adhoc

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for adhoc {adhoc_id} (sync event)")
            result = delete_operation()
            was_duplicate = False

            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ADHOC_DELETED",
                    aggregate_id=str(adhoc_id),
                    processed_by=f"scheduler_service_{adhoc_delete.ModifiedById}_sync",
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ADHOC_DELETED",
                aggregate_id=str(adhoc_id),
                processed_by=f"scheduler_service_{adhoc_delete.ModifiedById}",
                operation=delete_operation,
            )

        if was_duplicate:
            existing_adhoc = db.query(RefAdhoc).filter(RefAdhoc.AdhocID == adhoc_id).first()
            logger.info(f"Duplicate delete event for adhoc {adhoc_id}, returning current state")
            return existing_adhoc, True

        if result is None:
            logger.warning(f"Adhoc {adhoc_id} not found for deletion")
            db.commit()
            return None, False

        db.commit()
        logger.info(f"Successfully deleted adhoc {adhoc_id}")
        return result, False

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting adhoc {adhoc_id}: {str(e)}")
        raise


def get_ref_adhoc_by_id(db: Session, adhoc_id: int) -> Optional[RefAdhoc]:
    """Get an adhoc record by ID."""
    return db.query(RefAdhoc).filter(RefAdhoc.AdhocID == adhoc_id, RefAdhoc.IsDeleted == "0").first()


def get_ref_adhoc_by_patient(db: Session, patient_id: int) -> List[RefAdhoc]:
    """Get all adhoc records for a patient."""
    return (
        db.query(RefAdhoc)
        .filter(
            RefAdhoc.PatientID == patient_id,
            RefAdhoc.IsDeleted == "0",
        )
        .all()
    )


def get_idempotency_stats(db: Session) -> dict:
    """Get statistics about processed events for monitoring."""
    return IdempotencyService.get_processing_stats(db)


def cleanup_old_processed_events(db: Session, older_than_days: int = 30) -> int:
    """Clean up old processed events - should be run periodically."""
    return IdempotencyService.cleanup_old_events(db, older_than_days)


def is_event_already_processed(db: Session, correlation_id: str) -> bool:
    """Check if a specific correlation_id was already processed."""
    return IdempotencyService.is_already_processed(db, correlation_id)
