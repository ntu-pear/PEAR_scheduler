"""
Test script to verify sync event handling in the scheduler service.

This script simulates publishing sync events and verifies they are processed correctly.
"""

import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_sync_event_message(activity_id: int, event_type: str = "ACTIVITY_UPDATED") -> dict:
    """
    Create a sync event message for testing.
    
    Args:
        activity_id: The activity ID to sync
        event_type: Type of event (ACTIVITY_UPDATED, ACTIVITY_DELETED, etc.)
    
    Returns:
        Dictionary representing the sync event message
    """
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "source_service": "activity-service",
        "data": {
            "correlation_id": f"sync-test-{activity_id}-{datetime.utcnow().timestamp()}",
            "event_type": event_type,
            "activity_id": activity_id,
            "activity_data": {
                "id": activity_id,
                "title": "Sync Test Activity",
                "description": "Testing sync event handling",
                "is_deleted": False,
                "created_date": "2025-09-25T09:26:30.490000",
                "modified_date": datetime.utcnow().isoformat(),
                "created_by_id": "test_user",
                "modified_by_id": "test_user"
            },
            "old_data": {},
            "new_data": {
                "id": activity_id,
                "title": "Sync Test Activity",
                "description": "Testing sync event handling",
                "is_deleted": False
            },
            "changes": {},
            "modified_by": "test_user",
            "is_sync_event": True,
            "sync_reason": "manual_test"
        }
    }


def verify_activity_updated(db: Session, activity_id: int) -> bool:
    """
    Verify that an activity was updated in the database.
    
    Args:
        db: Database session
        activity_id: Activity ID to check
    
    Returns:
        True if activity exists and was recently updated
    """
    from pear_schedule.models.ref_activity_model import RefActivity
    
    activity = db.query(RefActivity).filter(
        RefActivity.ActivityID == activity_id
    ).first()
    
    if not activity:
        logger.error(f"Activity {activity_id} not found in REF_ACTIVITY table")
        return False
    
    logger.info(f"Activity {activity_id} found:")
    logger.info(f"  Title: {activity.ActivityTitle}")
    logger.info(f"  Description: {activity.ActivityDesc}")
    logger.info(f"  IsDeleted: {activity.IsDeleted}")
    logger.info(f"  UpdatedDateTime: {activity.UpdatedDateTime}")
    logger.info(f"  ModifiedById: {activity.ModifiedById}")
    
    # Check if updated in last 5 minutes
    time_diff = datetime.utcnow() - activity.UpdatedDateTime
    if time_diff.total_seconds() < 300:  # 5 minutes
        logger.info(f"✓ Activity was updated recently ({time_diff.total_seconds():.1f} seconds ago)")
        return True
    else:
        logger.warning(f"✗ Activity was last updated {time_diff.total_seconds():.1f} seconds ago")
        return False


def verify_processed_event(db: Session, correlation_id: str) -> bool:
    """
    Verify that an event was recorded in PROCESSED_EVENTS table.
    
    Args:
        db: Database session
        correlation_id: Correlation ID to check
    
    Returns:
        True if event was recorded
    """
    from pear_schedule.models.processed_events_model import ProcessedEvent
    
    event = db.query(ProcessedEvent).filter(
        ProcessedEvent.correlation_id == correlation_id
    ).first()
    
    if not event:
        logger.error(f"Event {correlation_id} not found in PROCESSED_EVENTS table")
        return False
    
    logger.info(f"Processed event {correlation_id} found:")
    logger.info(f"  Event Type: {event.event_type}")
    logger.info(f"  Aggregate ID: {event.aggregate_id}")
    logger.info(f"  Processed By: {event.processed_by}")
    logger.info(f"  Processed At: {event.processed_at}")
    
    if "_sync" in event.processed_by:
        logger.info("✓ Event was marked as sync event (processed_by contains '_sync')")
        return True
    else:
        logger.warning("✗ Event was NOT marked as sync event")
        return False


def test_sync_event_processing():
    """
    Main test function to verify sync event handling.
    """
    from pear_schedule.database import get_db
    from messaging.activity_consumer import ActivityConsumer
    
    logger.info("=" * 80)
    logger.info("Starting Sync Event Test")
    logger.info("=" * 80)
    
    # Create consumer
    consumer = ActivityConsumer()
    
    # Create a sync event message
    activity_id = 24  # Use the activity ID from your example
    sync_message = create_sync_event_message(activity_id)
    
    logger.info(f"\nCreated sync event message:")
    logger.info(json.dumps(sync_message, indent=2))
    
    # Process the message
    logger.info("\n" + "=" * 80)
    logger.info("Processing sync event...")
    logger.info("=" * 80)
    
    try:
        # Simulate message processing
        result = consumer._process_activity_message(sync_message)
        
        logger.info(f"\nProcessing result: {result}")
        
        # Verify the results
        logger.info("\n" + "=" * 80)
        logger.info("Verifying results...")
        logger.info("=" * 80)
        
        db = next(get_db())
        try:
            # Check activity was updated
            activity_ok = verify_activity_updated(db, activity_id)
            
            # Check processed event was recorded
            correlation_id = sync_message['data']['correlation_id']
            event_ok = verify_processed_event(db, correlation_id)
            
            # Summary
            logger.info("\n" + "=" * 80)
            logger.info("Test Summary")
            logger.info("=" * 80)
            
            if activity_ok and event_ok:
                logger.info("✓ All checks passed! Sync event handling is working correctly.")
                return True
            else:
                logger.error("✗ Some checks failed. Review the logs above.")
                if not activity_ok:
                    logger.error("  - Activity was not updated correctly")
                if not event_ok:
                    logger.error("  - Processed event was not recorded correctly")
                return False
                
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error during test: {str(e)}", exc_info=True)
        return False


def test_duplicate_sync_events():
    """
    Test that sync events can be processed multiple times (no idempotency blocking).
    """
    from pear_schedule.database import get_db
    from messaging.activity_consumer import ActivityConsumer
    
    logger.info("\n" + "=" * 80)
    logger.info("Testing Duplicate Sync Event Processing")
    logger.info("=" * 80)
    
    consumer = ActivityConsumer()
    activity_id = 24
    
    # Use the SAME correlation ID for both messages
    correlation_id = f"sync-duplicate-test-{activity_id}"
    
    # First message
    sync_message_1 = create_sync_event_message(activity_id)
    sync_message_1['data']['correlation_id'] = correlation_id
    sync_message_1['data']['activity_data']['description'] = "First sync event"
    
    # Second message (same correlation_id)
    sync_message_2 = create_sync_event_message(activity_id)
    sync_message_2['data']['correlation_id'] = correlation_id
    sync_message_2['data']['activity_data']['description'] = "Second sync event (duplicate correlation_id)"
    
    try:
        logger.info("\nProcessing first sync event...")
        result_1 = consumer._process_activity_message(sync_message_1)
        logger.info(f"First event result: {result_1}")
        
        logger.info("\nProcessing second sync event (same correlation_id)...")
        result_2 = consumer._process_activity_message(sync_message_2)
        logger.info(f"Second event result: {result_2}")
        
        # Verify both were processed (not marked as duplicate)
        if result_2 != "DUPLICATE":
            logger.info("✓ Second sync event was processed (not blocked by idempotency)")
            return True
        else:
            logger.error("✗ Second sync event was blocked as duplicate")
            return False
            
    except Exception as e:
        logger.error(f"Error during duplicate test: {str(e)}", exc_info=True)
        return False


if __name__ == "__main__":
    # Run tests
    logger.info("Starting sync event verification tests...\n")
    
    test_1_passed = test_sync_event_processing()
    test_2_passed = test_duplicate_sync_events()
    
    # Final summary
    logger.info("\n" + "=" * 80)
    logger.info("FINAL TEST RESULTS")
    logger.info("=" * 80)
    logger.info(f"Test 1 (Basic sync event): {'PASSED ✓' if test_1_passed else 'FAILED ✗'}")
    logger.info(f"Test 2 (Duplicate sync events): {'PASSED ✓' if test_2_passed else 'FAILED ✗'}")
    
    if test_1_passed and test_2_passed:
        logger.info("\n🎉 All tests passed! Sync event handling is working correctly.")
    else:
        logger.info("\n⚠️  Some tests failed. Please review the logs and fix the issues.")
