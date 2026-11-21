"""
Agnost AI Via OpenInference
===========================

Demonstrates instrumenting an Agno agent with OpenInference and sending traces to Agnost AI.

Setup:
    pip install agno openai openinference-instrumentation-agno opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

Set AGNOST_ORG_ID and OPENAI_API_KEY before running this example.
See https://docs.agnost.ai/agno for the complete setup guide.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from openinference.instrumentation import using_attributes
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# The exporter appends "/v1/traces" to the base OTEL_EXPORTER_OTLP_ENDPOINT.
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://otel.agnost.ai"
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = (
    f"X-Agnost-Org-ID={os.getenv('AGNOST_ORG_ID')}"
)

tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))

# Start instrumenting agno
AgnoInstrumentor().instrument(tracer_provider=tracer_provider)


def get_order_status(order_id: str) -> str:
    """Look up the shipping status of an order."""
    return f"Order {order_id} shipped on 2026-11-10."


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Support Agent",
    model=OpenAIChat(id="gpt-5.2"),
    tools=[get_order_status],
    session_id="session-123",
    user_id="user-42",
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Agnost AI groups runs into conversations by session.id and attributes them by user.id
    with using_attributes(session_id="session-123", user_id="user-42"):
        agent.print_response("Where is order 1042?")
        agent.print_response("When was it shipped?")
