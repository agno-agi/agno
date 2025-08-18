from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.apache_kafka import ApacheKafkaTools

# Configure Kafka settings
bootstrap_servers = "localhost:9092"
topic = "notifications"

# Create an agent that can send notifications to Apache Kafka
agent = Agent(
    name="Notification Agent",
    model=OpenAIChat(id="gpt-4o"),
    description="""You are a notification agent that sends alerts and messages to a Kafka topic""",
    instructions=[
        "When asked to send a notification:",
        "1. Create a clear, well-formatted message",
        "2. Send it to the Kafka notifications topic",
        "3. Confirm successful delivery",
    ],
    tools=[
        ApacheKafkaTools(
            bootstrap_servers=bootstrap_servers,
            topic=topic,
        )
    ],
    markdown=True,
    show_tool_calls=True,
)

# Example: Send a simple notification
agent.print_response(
    "Send a notification: 'User john.doe logged in successfully at 2024-01-15 10:30 AM'"
)

"""
Simple Use Cases:
- System alerts and monitoring notifications
- User activity logging
- Application status updates
- Error notifications
- Performance metrics

Troubleshooting:
- If messages aren't sending, check:
  * Kafka cluster is running and accessible at localhost:9092
  * Topic 'notifications' exists or auto-creation is enabled
  * Network connectivity to Kafka cluster
- Use kafka-console-consumer to verify messages:
  kafka-console-consumer --bootstrap-server localhost:9092 --topic notifications --from-beginning
"""
