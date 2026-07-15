"""
Opik Via OpenInference
======================

Demonstrates instrumenting Agno with OpenTelemetry and exporting traces to Opik.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Configure OpenTelemetry to export spans to Opik
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
trace_api.set_tracer_provider(tracer_provider)

# Enable automatic instrumentation for Agno
AgnoInstrumentor().instrument()


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-5.2"),
    tools=[YFinanceTools()],
    instructions="You are a stock price analyst. Answer with concise, well-sourced updates.",
    debug_mode=True,
    trace_attributes={
        "session.id": "demo-session-001",
        "environment": "development",
    },
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The span hierarchy (agent -> model -> tool) will appear in Opik for every request
    agent.print_response(
        "What is the current price of Apple and how did it move today?"
    )
