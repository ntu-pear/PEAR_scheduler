import logging
import threading
import time
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor

from .patient_consumer import PatientConsumer
# from .activity_consumer import ActivityConsumer

logger = logging.getLogger(__name__)

class ConsumerManager:
    """
    Manages multiple RabbitMQ consumers for the scheduler service
    Allows easy scaling and management of different consumer types
    """
    
    def __init__(self):
        self.consumers = {}
        self.threads = {}
        self.executor = None
        self.running = False
        
    def register_consumer(self, name: str, consumer_class):
        """Register a consumer class"""
        self.consumers[name] = consumer_class
        logger.info(f"Registered consumer: {name}")
    
    def start_all_consumers(self):
        """Start all registered consumers in separate threads"""
        if self.running:
            logger.warning("Consumers are already running")
            return
        
        if not self.consumers:
            logger.warning("No consumers registered")
            return
        
        self.executor = ThreadPoolExecutor(max_workers=len(self.consumers))
        self.running = True
        
        for name, consumer_class in self.consumers.items():
            future = self.executor.submit(self._run_consumer, name, consumer_class)
            self.threads[name] = future
            logger.info(f"Started consumer thread: {name}")
    
    def start_consumer(self, name: str):
        """Start a specific consumer"""
        if name not in self.consumers:
            logger.error(f"Consumer {name} not registered")
            return False
        
        if name in self.threads and not self.threads[name].done():
            logger.warning(f"Consumer {name} is already running")
            return False
        
        if not self.executor:
            self.executor = ThreadPoolExecutor(max_workers=len(self.consumers))
            self.running = True
        
        consumer_class = self.consumers[name]
        future = self.executor.submit(self._run_consumer, name, consumer_class)
        self.threads[name] = future
        logger.info(f"Started consumer: {name}")
        return True
    
    def stop_consumer(self, name: str):
        """Stop a specific consumer"""
        if name not in self.threads:
            logger.warning(f"Consumer {name} is not running")
            return False
        
        # Note: This is a graceful shutdown request
        # The actual consumer shutdown depends on the consumer implementation
        future = self.threads[name]
        if not future.done():
            future.cancel()
            logger.info(f"Sent stop signal to consumer: {name}")
        
        return True
    
    def stop_all_consumers(self):
        """Stop all running consumers"""
        if not self.running:
            logger.warning("No consumers are running")
            return
        
        logger.info("Stopping all consumers...")
        
        if self.executor:
            self.executor.shutdown(wait=True)
        
        self.threads.clear()
        self.running = False
        logger.info("All consumers stopped")
    
    def get_consumer_status(self) -> Dict[str, str]:
        """Get status of all consumers"""
        status = {}
        for name, future in self.threads.items():
            if future.done():
                if future.exception():
                    status[name] = f"Error: {future.exception()}"
                else:
                    status[name] = "Completed"
            else:
                status[name] = "Running"
        
        return status
    
    def _run_consumer(self, name: str, consumer_class):
        """Run a consumer in a separate thread"""
        try:
            logger.info(f"Starting consumer: {name}")
            consumer = consumer_class()
            consumer.start_consuming()
        except KeyboardInterrupt:
            logger.info(f"Consumer {name} interrupted by user")
        except Exception as e:
            logger.error(f"Consumer {name} failed: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise
        finally:
            if 'consumer' in locals():
                consumer.close()
            logger.info(f"Consumer {name} shutdown complete")


# Pre-configured manager instance
def create_scheduler_consumer_manager() -> ConsumerManager:
    """Create a consumer manager with all scheduler consumers registered"""
    manager = ConsumerManager()
    
    # Register all available consumers
    manager.register_consumer("patient", PatientConsumer)
    # manager.register_consumer("activity", ActivityConsumer)  # Add when available
    
    return manager


# Usage example
if __name__ == "__main__":
    import signal
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    # Create and configure the manager
    manager = create_scheduler_consumer_manager()
    
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        manager.stop_all_consumers()
        sys.exit(0)
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start all consumers
        manager.start_all_consumers()
        
        # Keep the main thread alive
        while manager.running:
            time.sleep(1)
            
            # Optionally print status
            status = manager.get_consumer_status()
            if any(s.startswith("Error") for s in status.values()):
                logger.error(f"Consumer errors detected: {status}")
                break
                
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    finally:
        manager.stop_all_consumers()
