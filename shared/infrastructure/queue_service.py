"""
QueueService - Handles RabbitMQ queue management functionality
Extracted from the monolithic queue_worker.py
"""
import json
import time
import pika
from typing import Callable, Dict, Any
from shared.config import config
from shared.utils.logging import get_logger


class QueueService:
    """Service responsible for RabbitMQ queue management"""
    
    def __init__(self, queue_name: str = 'scan_tasks'):
        self.queue_name = queue_name
        self.connection = None
        self.channel = None
        self.rabbitmq_config = config.rabbitmq
        self.logger = get_logger(__name__)
        self.max_retries = 5
        self.retry_delay_base = 2  # seconds

    def connect(self) -> bool:
        """
        Establish connection to RabbitMQ with retry logic
        
        Returns:
            True if connection successful, False otherwise
        """
        for attempt in range(self.max_retries):
            try:
                self.logger.info(f"Attempting to connect to RabbitMQ (attempt {attempt + 1}/{self.max_retries})...")
                self.logger.debug(f"Using RABBITMQ_HOST={self.rabbitmq_config.host}")
                
                connection_params = pika.ConnectionParameters(
                    host=self.rabbitmq_config.host,
                    port=self.rabbitmq_config.port,
                    credentials=pika.PlainCredentials(
                        self.rabbitmq_config.username,
                        self.rabbitmq_config.password
                    ),
                    heartbeat=600,  # 10 minutes
                    blocked_connection_timeout=300  # 5 minutes
                )
                
                self.connection = pika.BlockingConnection(connection_params)
                self.logger.info("Connection to RabbitMQ established.")
                
                self.channel = self.connection.channel()
                self.logger.debug(f"Declaring queue '{self.queue_name}'...")
                
                # Set prefetch to 1 so each worker only gets 1 message at a time
                # This ensures queue length reflects actual work in progress for KEDA scaling
                self.channel.basic_qos(prefetch_count=1)
                self.logger.debug("Set prefetch_count=1 for proper KEDA scaling")
                
                self.channel.queue_declare(queue=self.queue_name)
                self.logger.debug(f"Queue '{self.queue_name}' declared.")
                
                # Log current queue state
                queue_state = self.channel.queue_declare(queue=self.queue_name, passive=True)
                self.logger.info(f"{self.queue_name} queue message count: {queue_state.method.message_count}")
                
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to connect to RabbitMQ (attempt {attempt + 1}/{self.max_retries}): {e}")
                
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay_base ** attempt
                    self.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    self.logger.error("Max retry attempts reached. Connection failed.")
                    
        return False

    def disconnect(self):
        """Close RabbitMQ connection"""
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
                print("[DEBUG] RabbitMQ connection closed.")
        except Exception as e:
            print(f"[ERROR] Error closing RabbitMQ connection: {e}")

    def publish_task(self, task_data: Dict[str, Any]) -> bool:
        """
        Publish a task to the queue
        
        Args:
            task_data: Dictionary containing task information
            
        Returns:
            True if published successfully, False otherwise
        """
        try:
            if not self.channel:
                if not self.connect():
                    return False
                    
            message = json.dumps(task_data)
            self.channel.basic_publish(
                exchange='',
                routing_key=self.queue_name,
                body=message
            )
            # Log task info without the full message content to avoid polluting logs
            task_info = {k: v for k, v in task_data.items() if k != 'page_content'}
            print(f"[DEBUG] Published task to queue: {json.dumps(task_info)}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to publish task: {e}")
            return False
    
    def publish_batch(self, queue_name: str, messages: list) -> bool:
        """
        Publish multiple messages to a queue in a batch
        
        Args:
            queue_name: Name of the queue to publish to
            messages: List of message dictionaries
            
        Returns:
            True if all messages published successfully, False otherwise
        """
        try:
            if not self.channel:
                if not self.connect():
                    return False
            
            # Publish all messages in the batch
            for message in messages:
                message_body = json.dumps(message)
                self.channel.basic_publish(
                    exchange='',
                    routing_key=queue_name,
                    body=message_body
                )
            
            self.logger.info(f"Published {len(messages)} messages to {queue_name} queue")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to publish batch to {queue_name}: {e}")
            return False
    
    def publish(self, queue_name: str, message: Dict[str, Any]) -> bool:
        """
        Publish a single message to a specific queue
        
        Args:
            queue_name: Name of the queue to publish to
            message: Message dictionary to publish
            
        Returns:
            True if published successfully, False otherwise
        """
        try:
            if not self.channel:
                if not self.connect():
                    return False
            
            message_body = json.dumps(message)
            self.channel.basic_publish(
                exchange='',
                routing_key=queue_name,
                body=message_body
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to publish to {queue_name}: {e}")
            return False

    def consume_tasks(self, callback: Callable[[Dict[str, Any]], None]):
        """
        Start consuming tasks from the queue with automatic reconnection
        
        Args:
            callback: Function to call for each received task
        """
        while True:
            try:
                if not self.channel or self.connection.is_closed:
                    if not self.connect():
                        self.logger.error("Failed to connect to RabbitMQ, waiting before retry...")
                        time.sleep(self.retry_delay_base)
                        continue
                        
                def message_callback(ch, method, properties, body):
                    """Internal callback wrapper for RabbitMQ messages"""
                    try:
                        self.logger.info(f"Received task: {body.decode()}")
                        
                        task_data_raw = body.decode()
                        task_data = json.loads(task_data_raw)
                        
                        self.logger.debug(f"Parsed task data: {task_data}")
                        
                        # Validate required fields based on queue type
                        if self.queue_name == 'scan_tasks':
                            # Original scan task validation
                            if not task_data.get('url') or not task_data.get('scan_id'):
                                self.logger.error(f"Invalid scan task data: missing url or scan_id in {task_data_raw}")
                                self._safe_nack(ch, method.delivery_tag, requeue=False)
                                return
                        elif self.queue_name == 'doc_processing':
                            # Document processing task validation
                            if not task_data.get('page_id') or not task_data.get('scan_id'):
                                self.logger.error(f"Invalid document task data: missing page_id or scan_id in {task_data_raw}")
                                self._safe_nack(ch, method.delivery_tag, requeue=False)
                                return
                        else:
                            # Generic validation - require at least scan_id
                            if not task_data.get('scan_id'):
                                self.logger.error(f"Invalid task data: missing scan_id in {task_data_raw}")
                                self._safe_nack(ch, method.delivery_tag, requeue=False)
                                return
                            
                        # Call the provided callback
                        success = callback(task_data)
                        
                        # Acknowledge message only after successful processing
                        if success is not False:  # None or True = success, False = failure
                            self._safe_ack(ch, method.delivery_tag)
                            
                            # Log success based on queue type
                            if self.queue_name == 'scan_tasks':
                                self.logger.info(f"Successfully processed scan task: {task_data.get('url')} for scan_id: {task_data.get('scan_id')}")
                            elif self.queue_name == 'doc_processing':
                                self.logger.info(f"Successfully processed document task: page_id {task_data.get('page_id')} for scan_id: {task_data.get('scan_id')}")
                            else:
                                self.logger.info(f"Successfully processed task for scan_id: {task_data.get('scan_id')}")
                        else:
                            self.logger.error("Task processing returned False, rejecting message")
                            self._safe_nack(ch, method.delivery_tag, requeue=True)
                        
                    except json.JSONDecodeError as e:
                        self.logger.error(f"Failed to parse JSON task data: {body.decode()}. Error: {e}")
                        self._safe_nack(ch, method.delivery_tag, requeue=False)
                    except Exception as e:
                        self.logger.error(f"Failed to process task: {body.decode()}. Error: {e}")
                        self._safe_nack(ch, method.delivery_tag, requeue=True)

                self.logger.info(f"Starting to consume messages from '{self.queue_name}' queue...")
                self.channel.basic_consume(
                    queue=self.queue_name,
                    on_message_callback=message_callback,
                    auto_ack=False  # Use manual acknowledgment for proper KEDA scaling
                )
                
                self.channel.start_consuming()
                
            except KeyboardInterrupt:
                self.logger.info("Stopping queue consumption...")
                try:
                    if self.channel:
                        self.channel.stop_consuming()
                except:
                    pass
                break
            except (pika.exceptions.ConnectionClosed, 
                   pika.exceptions.ChannelClosed,
                   pika.exceptions.ConnectionWrongStateError) as e:
                self.logger.warning(f"Connection lost: {e}. Attempting to reconnect...")
                self._cleanup_connection()
                time.sleep(self.retry_delay_base)
            except Exception as e:
                self.logger.error(f"Unexpected error in consume_tasks: {e}", exc_info=True)
                self._cleanup_connection()
                time.sleep(self.retry_delay_base)
        
        self.disconnect()

    def _safe_ack(self, channel, delivery_tag):
        """Safely acknowledge a message, handling channel state errors"""
        try:
            channel.basic_ack(delivery_tag=delivery_tag)
        except (pika.exceptions.ChannelClosed, pika.exceptions.ChannelWrongStateError):
            self.logger.warning("Channel closed during message acknowledgment")
        except Exception as e:
            self.logger.error(f"Error acknowledging message: {e}")

    def _safe_nack(self, channel, delivery_tag, requeue=True):
        """Safely reject a message, handling channel state errors"""
        try:
            channel.basic_nack(delivery_tag=delivery_tag, requeue=requeue)
        except (pika.exceptions.ChannelClosed, pika.exceptions.ChannelWrongStateError):
            self.logger.warning(f"Channel closed during message rejection, message lost (requeue={requeue})")
        except Exception as e:
            self.logger.error(f"Error rejecting message: {e}")

    def _cleanup_connection(self):
        """Clean up connection and channel references"""
        try:
            if self.channel and not self.channel.is_closed:
                self.channel.close()
        except:
            pass
        
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except:
            pass
        
        self.channel = None
        self.connection = None

    def get_queue_length(self) -> int:
        """
        Get the current number of messages in the queue
        
        Returns:
            Number of messages in queue, or -1 if error
        """
        try:
            if not self.channel:
                if not self.connect():
                    return -1
                    
            queue_state = self.channel.queue_declare(queue=self.queue_name, passive=True)
            return queue_state.method.message_count
            
        except Exception as e:
            print(f"[ERROR] Failed to get queue length: {e}")
            return -1

    def purge_queue(self) -> bool:
        """
        Remove all messages from the queue
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.channel:
                if not self.connect():
                    return False
                    
            purged_method = self.channel.queue_purge(queue=self.queue_name)
            purged_count = purged_method.method.message_count if hasattr(purged_method, 'method') else 0
            print(f"[DEBUG] Purged {purged_count} messages from '{self.queue_name}' queue")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to purge queue: {e}")
            return False

    def cancel_scan_tasks(self, scan_id: int) -> int:
        """
        Cancel all tasks in the queue for a specific scan ID
        Note: This implementation purges all tasks since RabbitMQ doesn't support
        selective message removal without consuming them.
        
        Args:
            scan_id: The scan ID to cancel tasks for
            
        Returns:
            Number of tasks purged, or -1 if error
        """
        try:
            if not self.channel:
                if not self.connect():
                    return -1
            
            # Get current queue length before purging
            queue_state = self.channel.queue_declare(queue=self.queue_name, passive=True)
            original_count = queue_state.method.message_count
            
            # Purge the queue (removes ALL tasks)
            # TODO: For production, we'd want selective removal, but this works for now
            purged_method = self.channel.queue_purge(queue=self.queue_name)
            purged_count = purged_method.method.message_count if hasattr(purged_method, 'method') else 0
            
            print(f"[DEBUG] Cancelled {purged_count} tasks from '{self.queue_name}' queue for scan {scan_id}")
            return purged_count
            
        except Exception as e:
            print(f"[ERROR] Failed to cancel scan tasks: {e}")
            return -1

    def is_scan_cancelled(self, scan_id: int) -> bool:
        """
        Check if a scan has been cancelled by querying the database
        
        Args:
            scan_id: The scan ID to check
            
        Returns:
            True if scan is cancelled, False otherwise
        """
        try:
            from shared.utils.database import SessionLocal
            from shared.models import Scan
            
            db = SessionLocal()
            try:
                scan = db.query(Scan).filter(Scan.id == scan_id).first()
                if scan and scan.cancellation_requested:
                    print(f"[DEBUG] Scan {scan_id} has been cancelled")
                    return True
                return False
            finally:
                db.close()
                
        except Exception as e:
            print(f"[ERROR] Failed to check scan cancellation status: {e}")
            return False