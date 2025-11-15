import json
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from confluent_kafka import Producer
except ImportError:
    logger.error("confluent-kafka is not installed. Please install it using 'pip install confluent-kafka'")
    raise


class ApacheKafkaTools(Toolkit):
    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        sasl_mechanism: Optional[str] = "PLAIN",
    ):
        """
        Initialize the Apache Kafka Tools.

        Args:
            bootstrap_servers (str): Kafka bootstrap servers
            topic (str): Default topic to publish messages to
            username (Optional[str]): SASL username for authentication
            password (Optional[str]): SASL password for authentication
            sasl_mechanism (Optional[str]): SASL mechanism (PLAIN, SCRAM-SHA-256, etc.)
        """
        super().__init__(name="Apache Kafka Tools", tools=[self.produce_message])
        """
        https://developer.confluent.io/get-started/python/#build-producer
        """
        config = {"bootstrap.servers": bootstrap_servers, "acks": "all", "security.protocol": "PLAINTEXT"}
        if username and password:
            config["security.protocol"] = "SASL_SSL"
            config["sasl.mechanisms"] = sasl_mechanism or "PLAIN"
            config["sasl.username"] = username
            config["sasl.password"] = password

        try:
            self.producer = Producer(config)
            self.topic = topic
            logger.info(f"Apache Kafka producer initialized for topic: {topic}")
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            raise

    def produce_message(self, message: str, topic: Optional[str] = None) -> str:
        """
        Produce a message to a Kafka topic.

        Args:
            message (str): The message to send to Kafka
            topic (Optional[str]): Topic to send to. If not provided, uses default topic

        Returns:
            str: JSON string containing the result of the operation
        """
        try:
            target_topic = topic or self.topic

            # Use a synchronous approach to get delivery confirmation
            self.producer.produce(target_topic, message, callback=self._delivery_callback)
            self.producer.flush()  # Wait for delivery

            result = {
                "status": "success",
                "message": "Message sent successfully",
                "topic": target_topic,
                "content": message,
            }
            logger.info(f"Message produced to topic '{target_topic}': {message[:100]}...")
            return json.dumps(result)

        except Exception as e:
            error_result = {
                "status": "error",
                "message": f"Failed to produce message: {str(e)}",
                "topic": topic or self.topic,
            }
            logger.error(f"Error producing message: {e}")
            return json.dumps(error_result)

    def _delivery_callback(self, err, msg):
        """Callback for message delivery confirmation."""
        if err:
            logger.error(f"Message delivery failed: {err}")
        else:
            logger.info(f"Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")
