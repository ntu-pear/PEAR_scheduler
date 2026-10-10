from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Tuple
import logging
import math
from ..models.ref_activity_routine_model import RefActivityRoutine
from ..schemas.ref_activity_routine import (
    RefActivityRoutineCreate,
    RefActivityRoutineUpdate,
    RefActivityRoutineDelete,
)
from ..services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)


def create_ref_activity_routine(
    db: Session,
    routine: RefActivityRoutineCreate,
    correlation_id: str,
    created_by: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityRoutine], bool]:
    """
    Create a new activity routine with idempotency protection.

    Args:
        db: Database session
        routine: Activity routine data to create
        correlation_id: Correlation ID from outbox service for deduplication
        created_by: User/service creating the routine
        skip_duplicate_check: If True, bypass idempotency check (for sync events)

    Returns:
        Tuple of (RefActivityRoutine or None, was_duplicate: bool)

    Raises:
        ValueError: If routine with same RoutineID already exists (business logic error)
        Exception: For database or other errors
    """

    def create_operation():
        existing = db.query(RefActivityRoutine).filter(
            RefActivityRoutine.RoutineID == routine.RoutineID
        ).first()

        if existing:
            if existing.IsDeleted == "1":
                logger.info(f"Reactivating soft-deleted routine {routine.RoutineID}")
                existing.IsDeleted = "0"
                existing.PatientID = routine.PatientID
                existing.ActivityID = routine.ActivityID
                existing.IncludeInSchedule = routine.IncludeInSchedule
                existing.RoutineIssues = routine.RoutineIssues
                existing.RoutineTimeSlots = routine.RoutineTimeSlots
                existing.UpdatedDateTime = routine.UpdatedDateTime
                existing.ModifiedById = created_by
                db.flush()
                return existing
            else:
                raise ValueError(f"Activity routine with RoutineID {routine.RoutineID} already exists.")

        logger.info(f"Creating new activity routine {routine.RoutineID}")

        new_routine = RefActivityRoutine(
            RoutineID=routine.RoutineID,
            PatientID=routine.PatientID,
            ActivityID=routine.ActivityID,
            IncludeInSchedule=routine.IncludeInSchedule,
            RoutineIssues=routine.RoutineIssues,
            RoutineTimeSlots=routine.RoutineTimeSlots,
            IsDeleted=routine.IsDeleted or "0",
            CreatedDateTime=routine.CreatedDateTime,
            UpdatedDateTime=routine.UpdatedDateTime,
            CreatedById=created_by,
            ModifiedById=created_by
        )

        db.add(new_routine)
        db.flush()
        return new_routine

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity routine {routine.RoutineID} (sync event)")
            result = create_operation()
            was_duplicate = False

            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ROUTINE_CREATED",
                    aggregate_id=str(routine.RoutineID),
                    processed_by=f"scheduler_service_{created_by}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ROUTINE_CREATED",
                aggregate_id=str(routine.RoutineID),
                processed_by=f"scheduler_service_{created_by}",
                operation=create_operation
            )

        if was_duplicate:
            existing_routine = db.query(RefActivityRoutine).filter(
                RefActivityRoutine.RoutineID == routine.RoutineID
            ).first()
            logger.info(f"Duplicate create event for activity routine {routine.RoutineID}, returning existing")
            return existing_routine, True

        db.commit()
        logger.info(f"Successfully created activity routine {routine.RoutineID}")
        return result, False

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating activity routine {routine.RoutineID}: {str(e)}")
        raise


def update_ref_activity_routine(
    db: Session,
    routine_id: int,
    routine_update: RefActivityRoutineUpdate,
    correlation_id: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityRoutine], bool]:
    """
    Update an existing activity routine with idempotency protection.

    Args:
        db: Database session
        routine_id: RoutineID of routine to update
        routine_update: Fields to update (includes UpdatedDateTime and ModifiedById)
        correlation_id: Correlation ID from outbox service for deduplication
        skip_duplicate_check: If True, bypass idempotency check (for sync events)

    Returns:
        Tuple of (RefActivityRoutine or None, was_duplicate: bool)
        None if routine not found

    Raises:
        Exception: For database or other errors
    """

    def update_operation():
        db_routine = db.query(RefActivityRoutine).filter(
            RefActivityRoutine.RoutineID == routine_id
        ).first()

        if not db_routine:
            logger.warning(f"Activity routine {routine_id} not found for update")
            return None

        logger.debug(f"Updating activity routine {routine_id}")

        update_data = routine_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_routine, field) and field != 'RoutineID':
                setattr(db_routine, field, value)

        db.flush()
        return db_routine

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity routine {routine_id} (sync event)")
            result = update_operation()
            was_duplicate = False

            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ROUTINE_UPDATED",
                    aggregate_id=str(routine_id),
                    processed_by=f"scheduler_service_{routine_update.ModifiedById}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ROUTINE_UPDATED",
                aggregate_id=str(routine_id),
                processed_by=f"scheduler_service_{routine_update.ModifiedById}",
                operation=update_operation
            )

        if was_duplicate:
            existing_routine = db.query(RefActivityRoutine).filter(
                RefActivityRoutine.RoutineID == routine_id,
                RefActivityRoutine.IsDeleted == "0"
            ).first()
            logger.info(f"Duplicate update event for activity routine {routine_id}, returning current state")
            return existing_routine, True

        if result is None:
            logger.warning(f"Activity routine {routine_id} not found for update")
            db.commit()
            return None, False

        db.commit()
        logger.debug(f"Successfully updated activity routine {routine_id}")
        return result, False

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating activity routine {routine_id}: {str(e)}")
        raise


def delete_ref_activity_routine(
    db: Session,
    routine_id: int,
    routine_delete: RefActivityRoutineDelete,
    correlation_id: str,
    skip_duplicate_check: bool = False
) -> Tuple[Optional[RefActivityRoutine], bool]:
    """
    Soft delete an activity routine with idempotency protection.

    Args:
        db: Database session
        routine_id: RoutineID of routine to delete
        routine_delete: Delete data including timestamp and user info
        correlation_id: Correlation ID from outbox service for deduplication
        skip_duplicate_check: If True, bypass idempotency check (for sync events)

    Returns:
        Tuple of (RefActivityRoutine or None, was_duplicate: bool)
        None if routine not found

    Raises:
        Exception: For database or other errors
    """

    def delete_operation():
        db_routine = db.query(RefActivityRoutine).filter(
            RefActivityRoutine.RoutineID == routine_id
        ).first()

        if not db_routine:
            logger.warning(f"Activity routine {routine_id} not found for deletion")
            return None

        if db_routine.IsDeleted == "1":
            logger.info(f"Activity routine {routine_id} already deleted")
            return db_routine

        logger.info(f"Soft deleting activity routine {routine_id}")

        db_routine.IsDeleted = "1"
        db_routine.ModifiedById = routine_delete.ModifiedById
        db_routine.UpdatedDateTime = routine_delete.UpdatedDateTime

        db.flush()
        return db_routine

    try:
        if skip_duplicate_check:
            logger.info(f"Skipping duplicate check for activity routine {routine_id} (sync event)")
            result = delete_operation()
            was_duplicate = False

            try:
                IdempotencyService.record_processed_event(
                    db=db,
                    correlation_id=correlation_id,
                    event_type="ROUTINE_DELETED",
                    aggregate_id=str(routine_id),
                    processed_by=f"scheduler_service_{routine_delete.ModifiedById}_sync"
                )
            except Exception as e:
                logger.warning(f"Failed to record sync event (non-critical): {str(e)}")
        else:
            result, was_duplicate = IdempotencyService.process_idempotent(
                db=db,
                correlation_id=correlation_id,
                event_type="ROUTINE_DELETED",
                aggregate_id=str(routine_id),
                processed_by=f"scheduler_service_{routine_delete.ModifiedById}",
                operation=delete_operation
            )

        if was_duplicate:
            existing_routine = db.query(RefActivityRoutine).filter(
                RefActivityRoutine.RoutineID == routine_id
            ).first()
            logger.info(f"Duplicate delete event for activity routine {routine_id}, returning current state")
            return existing_routine, True

        if result is None:
            logger.warning(f"Activity routine {routine_id} not found for deletion")
            db.commit()
            return None, False

        db.commit()
        logger.info(f"Successfully deleted activity routine {routine_id}")
        return result, False

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting activity routine {routine_id}: {str(e)}")
        raise


def get_ref_activity_routines(db: Session, pageNo: int = 0, pageSize: int = 10,
                             patient_id: Optional[int] = None, activity_id: Optional[int] = None,
                             include_in_schedule: Optional[str] = None):
    """Get activity routines with pagination and filtering"""
    offset = pageNo * pageSize
    query = db.query(RefActivityRoutine).filter(RefActivityRoutine.IsDeleted == "0")

    # Apply patient filter if provided
    if patient_id:
        query = query.filter(RefActivityRoutine.PatientID == patient_id)

    # Apply activity filter if provided
    if activity_id:
        query = query.filter(RefActivityRoutine.ActivityID == activity_id)

    # Apply include_in_schedule filter if provided
    if include_in_schedule in ["0", "1"]:
        query = query.filter(RefActivityRoutine.IncludeInSchedule == include_in_schedule)

    # Apply the same filters to count query
    count_query = db.query(func.count(RefActivityRoutine.RoutineID)).filter(RefActivityRoutine.IsDeleted == "0")

    if patient_id:
        count_query = count_query.filter(RefActivityRoutine.PatientID == patient_id)
    if activity_id:
        count_query = count_query.filter(RefActivityRoutine.ActivityID == activity_id)
    if include_in_schedule in ["0", "1"]:
        count_query = count_query.filter(RefActivityRoutine.IncludeInSchedule == include_in_schedule)

    totalRecords = count_query.scalar()
    totalPages = math.ceil(totalRecords / pageSize) if pageSize > 0 else 1

    db_routines = query.order_by(RefActivityRoutine.PatientID.asc()).offset(offset).limit(pageSize).all()

    return db_routines, totalRecords, totalPages

def get_ref_activity_routine_by_id(db: Session, routine_id: int):
    """Get activity routine by ID"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.RoutineID == routine_id,
        RefActivityRoutine.IsDeleted == "0"
    ).first()

def get_routine_by_patient_and_activity(db: Session, patient_id: int, activity_id: int):
    """Get routine for a specific patient and activity"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.PatientID == patient_id,
        RefActivityRoutine.ActivityID == activity_id,
        RefActivityRoutine.IsDeleted == "0"
    ).first()

def get_patient_scheduled_routines(db: Session, patient_id: int):
    """Get all routines included in schedule for a patient"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.PatientID == patient_id,
        RefActivityRoutine.IncludeInSchedule == "1",
        RefActivityRoutine.IsDeleted == "0"
    ).all()

def get_patient_excluded_routines(db: Session, patient_id: int):
    """Get all routines excluded from schedule for a patient"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.PatientID == patient_id,
        RefActivityRoutine.IncludeInSchedule == "0",
        RefActivityRoutine.IsDeleted == "0"
    ).all()

def get_activity_routines_by_time_slot(db: Session, time_slot: str):
    """Get all routines for a specific time slot"""
    return db.query(RefActivityRoutine).filter(
        RefActivityRoutine.RoutineTimeSlots.ilike(f"%{time_slot}%"),
        RefActivityRoutine.IncludeInSchedule == "1",
        RefActivityRoutine.IsDeleted == "0"
    ).all()


def get_idempotency_stats(db: Session) -> dict:
    """Get statistics about processed events for monitoring."""
    return IdempotencyService.get_processing_stats(db)


def cleanup_old_processed_events(db: Session, older_than_days: int = 30) -> int:
    """Clean up old processed events - should be run periodically."""
    return IdempotencyService.cleanup_old_events(db, older_than_days)


def is_event_already_processed(db: Session, correlation_id: str) -> bool:
    """Check if a specific correlation_id was already processed."""
    return IdempotencyService.is_already_processed(db, correlation_id)
