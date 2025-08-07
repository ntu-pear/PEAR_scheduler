import logging

def configure_rabbitmq_logging():
    """Configure RabbitMQ logging to reduce noise while keeping important info"""
    
    # Suppress the noisy EOF errors that are handled by auto-restart
    pika_loggers = [
        'pika.adapters.utils.io_services_utils',
        'pika.adapters.base_connection', 
        'pika.adapters.blocking_connection'
    ]
    
    class RecoverableErrorFilter(logging.Filter):
        """Filter out errors that are automatically recovered from"""
        def filter(self, record):
            message = record.getMessage().lower()
            
            # These are handled by auto-restart, so just log as DEBUG
            recoverable_errors = [
                "transport indicated eof",
                "client unexpectedly closed tcp connection", 
                "unexpected connection close detected"
            ]
            
            if any(error in message for error in recoverable_errors):
                # Change to DEBUG level instead of ERROR
                record.levelno = logging.DEBUG
                record.levelname = "DEBUG"
                
            return True
    
    # Apply filter to reduce noise
    for logger_name in pika_loggers:
        logger = logging.getLogger(logger_name)
        logger.addFilter(RecoverableErrorFilter())
        
    # Also clean up the consumer manager logs
    consumer_logger = logging.getLogger('consumer_manager')
    consumer_logger.addFilter(RecoverableErrorFilter())
