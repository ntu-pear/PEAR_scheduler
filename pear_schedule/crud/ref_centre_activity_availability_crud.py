from sqlalchemy.orm import Session
from typing import Optional, Tuple
import logging
from ..models.ref_centre_activity_availability_model import RefCentreActivityAvailability
from ..schemas.ref_centre_activity_availability import (
    RefCentreActivityAvailabilityCreate,
    RefCentreActivityAvailabilityUpdate,
    RefCentreActivityAvailabilityDelete,
)
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

# Business fields copied from the source record on create/upsert
_DATA_FIELDS = ("CentreActivityID", "DaysOfWeek", "StartTime", "EndTime", "StartDate", "EndDate", "IsDeleted")

def create_ref_centre_activity_availability(
    db: Session,
    availability: RefCentreActivityAvailabilityCreate,
    correlation_id: str,
    created_by: str,
    skip_duplicate_check: bool = False,
    record_event: bool = True
) -> Tuple[Optional[RefCentreActivityAvailability], bool]:
    """
    Create (or upsert) a centre activity availability with idempotency protection.

    Unlike exclusions, an existing row with the same ID is overwritten rather than
    rejected, so re-running the backfill sync script converges instead of failing.

    record_event=False (only valid with skip_duplicate_check) skips writing PROCESSED_EVENTS,
    for callers that already recorded this correlation_id (e.g. update -> create fallback).

    Returns:
        Tuple of (RefCentreActivityAvailability or None, was_duplicate: bool)
    """
    availability_id = availability.CentreActivityAvailabilityID

    def create_operation():
        existing = db.query(RefCentreActivityAvailability).filter(
            RefCentreActivityAvailability.CentreActivityAvailabilityID == availability_id
        ).first()

        if existing:
            logger.info(f"Centre activity availability {availability_id} already exists - overwriting with source data")
            for field in _DATA_FIELDS:
                setattr(existing, field, getattr(availability, field))
            existing.IsDeleted = availability.IsDeleted or "0"
            existing.UpdatedDateTime = availability.UpdatedDateTime
            existing.ModifiedById = created_by
            db.flush()
            return existing

        logger.info(f"Creating centre activity availability {availability_id} for centre activity {availability.CentreActivityID}")

        new_availability = RefCentreActivityAvailability(
            CentreActivityAvailabilityID=availability_id,
            CentreActivityID=availability.CentreActivityID,
            DaysOfWeek=availability.DaysOfWeek,
            StartTime=availability.StartTime,
            EndTime=availability.EndTime,
            StartDate=availability.StartDate,
            EndDate=availability.EndDate,
            IsDeleted=availability.IsDeleted or "0",
            CreatedDateTime=availability.CreatedDateTime,
            UpdatedDateTime=availability.UpdatedDateTime,
            CreatedById=created_by,
            ModifiedById=availability.ModifiedById or created_by
        )

        db.add(new_availability)
        db.flush()
        return new_availability

    aggregate_key = str(availability_id)

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for centre activity availability {aggregate_key} (sync event)")
            result = create_operation()
            was_duplicate = False

            if record_event:
                try:
                    IdempotencyService.record_processed_event(
                        db=db,
                        correlation_id=correlation_id,
                        event_type="CENTRE_ACTIVITY_AVAILABILITY_CREATED",
                        aggregate_id=aggregate_key,
                        processed_by=f"scheduler_service_{created_by}_sync"
                    )
                except Exception as e:
                    logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="CENTRE_ACTIVITY_AVAILABILITY_CREATED",
                aggregate_id=aggregate_key,
                processed_by=f"scheduler_service_{created_by}",
                operation=create_operation
            )

        if was_duplicate:
            existing_availability = db.query(RefCentreActivityAvailability).filter(
                RefCentreActivityAvailability.CentreActivityAvailabilityID == availability_id
            ).first()
            logger.info(f"Duplicate create event for centre activity availability {aggregate_key}, returning existing")
            return existing_availability, True

        db.commit()
        logger.info(f"Successfully created centre activity availability {aggregate_key}")
        return result, False

    except Exception as e:
        db.rollback()
        error_msg = str(e)
        if "FOREIGN KEY constraint" in error_msg and "REF_CENTRE_ACTIVITY" in error_msg:
            logger.warning(f"Centre activity {availability.CentreActivityID} does not exist in scheduler database for availability {aggregate_key}")
        logger.error(f"Error creating centre activity availability {aggregate_key}: {error_msg}")
        raise

def update_ref_centre_activity_availability(
    db: Session,
    availability_id: int,
    availability_update: RefCentreActivityAvailabilityUpdate,
    correlation_id: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefCentreActivityAvailability], bool]:
    """
    Update an existing centre activity availability with idempotency protection.

    Returns:
        Tuple of (RefCentreActivityAvailability or None, was_duplicate: bool)
        None if availability not found
    """

    def update_operation():
        db_availability = db.query(RefCentreActivityAvailability).filter(
            RefCentreActivityAvailability.CentreActivityAvailabilityID == availability_id
        ).first()

        if not db_availability:
            logger.warning(f"Centre activity availability {availability_id} not found for update")
            return None

        logger.debug(f"Updating centre activity availability {availability_id}")

        update_data = availability_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_availability, field) and field != 'CentreActivityAvailabilityID':
                setattr(db_availability, field, value)

        db.flush()
        return db_availability

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for centre activity availability {availability_id} (sync event)")
            result = update_operation()
            was_duplicate = False

            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="CENTRE_ACTIVITY_AVAILABILITY_UPDATED",
                    aggregate_id=str(availability_id),
                    processed_by=f"scheduler_service_{availability_update.ModifiedById}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="CENTRE_ACTIVITY_AVAILABILITY_UPDATED",
                aggregate_id=str(availability_id),
                processed_by=f"scheduler_service_{availability_update.ModifiedById}",
                operation=update_operation
            )

        if was_duplicate:
            existing_availability = db.query(RefCentreActivityAvailability).filter(
                RefCentreActivityAvailability.CentreActivityAvailabilityID == availability_id
            ).first()
            logger.info(f"Duplicate update event for centre activity availability {availability_id}, returning current state")
            return existing_availability, True

        db.commit()
        if result is None:
            return None, False

        logger.debug(f"Successfully updated centre activity availability {availability_id}")
        return result, False

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating centre activity availability {availability_id}: {str(e)}")
        raise

def delete_ref_centre_activity_availability(
    db: Session,
    availability_id: int,
    availability_delete: RefCentreActivityAvailabilityDelete,
    correlation_id: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefCentreActivityAvailability], bool]:
    """
    Soft delete a centre activity availability with idempotency protection.

    Returns:
        Tuple of (RefCentreActivityAvailability or None, was_duplicate: bool)
        None if availability not found
    """

    def delete_operation():
        db_availability = db.query(RefCentreActivityAvailability).filter(
            RefCentreActivityAvailability.CentreActivityAvailabilityID == availability_id
        ).first()

        if not db_availability:
            logger.warning(f"Centre activity availability {availability_id} not found for deletion")
            return None

        if db_availability.IsDeleted == "1":
            logger.info(f"Centre activity availability {availability_id} already deleted")
            return db_availability

        logger.info(f"Soft deleting centre activity availability {availability_id}")

        db_availability.IsDeleted = "1"
        db_availability.ModifiedById = availability_delete.ModifiedById
        db_availability.UpdatedDateTime = availability_delete.UpdatedDateTime

        db.flush()
        return db_availability

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for centre activity availability {availability_id} (sync event)")
            result = delete_operation()
            was_duplicate = False

            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="CENTRE_ACTIVITY_AVAILABILITY_DELETED",
                    aggregate_id=str(availability_id),
                    processed_by=f"scheduler_service_{availability_delete.ModifiedById}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="CENTRE_ACTIVITY_AVAILABILITY_DELETED",
                aggregate_id=str(availability_id),
                processed_by=f"scheduler_service_{availability_delete.ModifiedById}",
                operation=delete_operation
            )

        if was_duplicate:
            existing_availability = db.query(RefCentreActivityAvailability).filter(
                RefCentreActivityAvailability.CentreActivityAvailabilityID == availability_id
            ).first()
            logger.info(f"Duplicate delete event for centre activity availability {availability_id}, returning current state")
            return existing_availability, True

        db.commit()
        if result is None:
            return None, False

        logger.info(f"Successfully deleted centre activity availability {availability_id}")
        return result, False

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting centre activity availability {availability_id}: {str(e)}")
        raise

def is_event_already_processed(db: Session, correlation_id: str) -> bool:
    """Check if a specific correlation_id was already processed."""
    return IdempotencyService.is_already_processed(db, correlation_id)
