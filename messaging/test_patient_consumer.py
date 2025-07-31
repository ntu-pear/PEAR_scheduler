import logging
import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

from messaging.patient_consumer import PatientConsumer

def test_consumer_connection():
    """Test if the consumer can connect to RabbitMQ and set up properly"""
    
    # Set up detailed logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("=== Testing Patient Consumer Connection ===")
        
        # Initialize consumer
        logger.info("1. Initializing PatientConsumer...")
        consumer = PatientConsumer()
        
        # Test connection setup
        logger.info("2. Setting up consumer...")
        consumer.setup_consumer()
        
        logger.info("3. Consumer setup successful!")
        logger.info("4. Starting consumer (will listen for messages)...")
        logger.info("   Send a test message from patient service to see if it's received")
        logger.info("   Press Ctrl+C to stop...")
        
        # Start consuming (this will block and wait for messages)
        consumer.start_consuming()
        
    except KeyboardInterrupt:
        logger.info("Consumer test stopped by user")
    except Exception as e:
        logger.error(f"Consumer test failed: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False
    finally:
        if 'consumer' in locals():
            consumer.close()
        logger.info("Consumer test completed")
    
    return True

if __name__ == "__main__":
    test_consumer_connection()
