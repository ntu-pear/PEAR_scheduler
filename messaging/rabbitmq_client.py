import pika
import json
import logging
import os
import time
import threading
from typing import Dict, Any, Callable
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class RabbitMQClient:
    """
    Base RabbitMQ client for PEAR Scheduler Service
    Handles connection management and basic operations
    """
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.host = os.getenv('RABBITMQ_HOST')
        self.port = int(os.getenv('RABBITMQ_PORT'))
        self.username = os.getenv('RABBITMQ_USER')
        self.password = os.getenv('RABBITMQ_PASS')
        self.virtual_host = os.getenv('RABBITMQ_VIRTUAL_HOST')
        
        self.connection = None
        self.channel = None
        self.is_connected = False
        self.shutdown_event = None
        self.consuming = False
        self.consumer_tags = []  # Track our own consumer tags
    
    def set_shutdown_event(self, shutdown_event: threading.Event):
        """Set the shutdown event for graceful shutdown"""
        self.shutdown_event = shutdown_event
    
    def connect(self, max_retries: int = 5) -> bool:
        """Connect to RabbitMQ with retry logic"""
        for attempt in range(max_retries):
            try:
                credentials = pika.PlainCredentials(self.username, self.password)
                parameters = pika.ConnectionParameters(
                    host=self.host,
                    port=self.port,
                    virtual_host=self.virtual_host,
                    credentials=credentials,
                    heartbeat=30,
                    blocked_connection_timeout=300
                )
                
                self.connection = pika.BlockingConnection(parameters)
                self.channel = self.connection.channel()
                self.is_connected = True
                
                logger.info(f"{self.service_name} connected to RabbitMQ at {self.host}:{self.port}")
                return True
                
            except Exception as e:
                logger.error(f"Connection attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    
        self.is_connected = False
        return False
    
    def ensure_connection(self):
        """Ensure connection is active"""
        if not self.is_connected or not self.connection or self.connection.is_closed:
            if not self.connect():
                raise ConnectionError(f"{self.service_name}: Failed to connect to RabbitMQ")
    
    def publish(self, exchange: str, routing_key: str, message: Dict[str, Any], 
                max_retries: int = 3) -> bool:
        """
        Publish message with fault tolerance
        """
        message_body = {
            'timestamp': datetime.utcnow().isoformat(),
            'source_service': self.service_name,
            'data': message
        }
        
        for attempt in range(max_retries):
            try:
                self.ensure_connection()
                
                self.channel.basic_publish(
                    exchange=exchange,
                    routing_key=routing_key,
                    body=json.dumps(message_body, default=str),
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Persistent message
                        timestamp=int(time.time()),
                        content_type='application/json'
                    )
                )
                
                logger.info(f"{self.service_name} published: {exchange}/{routing_key}")
                return True
                
            except Exception as e:
                logger.error(f"Publish attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    
        logger.error(f"{self.service_name} failed to publish after {max_retries} attempts")
        return False
    
    def consume(self, queue_name: str, callback: Callable, auto_ack: bool = False):
        """
        Set up consumer for a queue
        """
        def wrapped_callback(channel, method, properties, body):
            try:
                # Check if we should stop processing
                if self.shutdown_event and self.shutdown_event.is_set():
                    logger.info(f"{self.service_name} stopping due to shutdown signal")
                    if not auto_ack:
                        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    return
                
                message = json.loads(body.decode('utf-8'))
                logger.info(f"{self.service_name} received message from {queue_name}")
                
                # Call the actual callback
                success = callback(message)
                
                if not auto_ack:
                    if success:
                        channel.basic_ack(delivery_tag=method.delivery_tag)
                        logger.info(f"{self.service_name} acknowledged message")
                    else:
                        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        logger.warning(f"{self.service_name} rejected message")
                        
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {str(e)}")
                if not auto_ack:
                    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                if not auto_ack:
                    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        
        try:
            self.ensure_connection()
            self.channel.basic_qos(prefetch_count=1)
            
            # Set up consumer and track the consumer tag
            consumer_tag = self.channel.basic_consume(
                queue=queue_name,
                on_message_callback=wrapped_callback,
                auto_ack=auto_ack
            )
            self.consumer_tags.append(consumer_tag)
            logger.info(f"{self.service_name} set up consumer for {queue_name} with tag {consumer_tag}")
            
        except Exception as e:
            logger.error(f"Failed to set up consumer: {str(e)}")
            raise
    
    def start_consuming(self):
        """Start consuming messages (blocking)"""
        try:
            self.ensure_connection()
            logger.info(f"{self.service_name} starting to consume messages...")
            self.consuming = True
            
            # Use Pika's built-in start_consuming but with custom stop logic
            while self.consuming and not (self.shutdown_event and self.shutdown_event.is_set()):
                try:
                    # Process events with a timeout to allow checking shutdown signal
                    self.connection.process_data_events(time_limit=1)
                    
                    # Check if there are any pending events
                    if not self.connection.is_open:
                        logger.warning(f"{self.service_name} connection closed")
                        break
                        
                except pika.exceptions.AMQPConnectionError:
                    logger.warning(f"{self.service_name} connection lost, attempting to reconnect...")
                    if not self.connect():
                        break
                except Exception as e:
                    logger.error(f"Error processing data events: {str(e)}")
                    break
            
            logger.info(f"{self.service_name} stopping consumption...")
            
        except KeyboardInterrupt:
            logger.info(f"{self.service_name} stopping consumption due to KeyboardInterrupt...")
        except Exception as e:
            logger.error(f"Error during consumption: {str(e)}")
            raise
        finally:
            self.consuming = False
            self.stop_consuming()
    
    def stop_consuming(self):
        """Stop consuming messages"""
        try:
            self.consuming = False
            if self.channel and not self.channel.is_closed:
                # Cancel all our tracked consumers (only once each)
                if self.consumer_tags:  # Only if we have consumers to cancel
                    consumer_tags_to_cancel = self.consumer_tags[:]  # Make a copy
                    self.consumer_tags.clear()  # Clear the original list immediately
                    
                    for consumer_tag in consumer_tags_to_cancel:
                        try:
                            self.channel.basic_cancel(consumer_tag)
                            logger.info(f"{self.service_name} cancelled consumer: {consumer_tag}")
                        except Exception as e:
                            # Log at debug level to reduce noise - these errors are often harmless
                            logger.debug(f"Error cancelling consumer {consumer_tag}: {str(e)}")
                            
                    logger.info(f"{self.service_name} stopped consuming")
        except Exception as e:
            logger.debug(f"Error stopping consumption: {str(e)}")
    
    def close(self):
        """Close connection"""
        try:
            self.consuming = False
            
            # First stop consuming (but only if we haven't already)
            if self.consumer_tags:  # Only if we have consumers to cancel
                self.stop_consuming()
            
            # Then close channel
            if self.channel and not self.channel.is_closed:
                try:
                    self.channel.close()
                    logger.debug(f"{self.service_name} channel closed")
                except Exception as e:
                    logger.debug(f"Error closing channel: {str(e)}")
                
            # Finally close connection
            if self.connection and not self.connection.is_closed:
                try:
                    self.connection.close()
                    logger.debug(f"{self.service_name} connection closed")
                except Exception as e:
                    logger.debug(f"Error closing connection: {str(e)}")
                
            self.is_connected = False
            logger.info(f"{self.service_name} RabbitMQ connection closed")
        except Exception as e:
            logger.debug(f"Error closing connection: {str(e)}")
