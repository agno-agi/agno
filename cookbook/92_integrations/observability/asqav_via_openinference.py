"""
Asqav Via OpenInference
=======================

Demonstrates instrumenting an Agno agent with asqav for governance
audit trails, cryptographic signing, and compliance reporting.

asqav signs every agent action with ML-DSA post-quantum signatures,
producing a verifiable audit trail alongside Agno's OpenTelemetry traces.

Requirements:
    pip install asqav opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno

More info: https://github.com/jagmarques/asqav-sdk
"""

import os

import asqav
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace as trace_api
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

# ---------------------------------------------------------------------------
# Setup - asqav governance layer
# ---------------------------------------------------------------------------
# Initialize asqav with your API key (get one at https://asqav.com)
asqav.init(api_key=os.getenv("ASQAV_API_KEY", "sk_..."))

# Create an asqav agent identity for cryptographic action signing
asqav_agent = asqav.Agent.create("agno-stock-analyst")

# Configure asqav to export its governance spans via OpenTelemetry
asqav.configure_otel(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))

# ---------------------------------------------------------------------------
# Setup - Agno OpenTelemetry tracing
# ---------------------------------------------------------------------------
# Use any OTel-compatible exporter (OTLP, console, etc.)
# asqav governance events are captured separately via asqav.configure_otel()
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace_api.set_tracer_provider(tracer_provider)

# Enable automatic OpenInference instrumentation for Agno
AgnoInstrumentor().instrument()


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
    instructions="You are a stock price analyst. Answer with concise, sourced updates.",
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
    # Sign the agent run as a governance event in asqav's audit trail.
    # This creates a cryptographic record that this agent was authorized to run.
    asqav_agent.sign("agent:run", {"task": "stock-analysis", "framework": "agno"})

    # Run the agent - OpenInference captures the full trace (agent, model, tool spans)
    # while asqav records the governance signature for compliance.
    agent.print_response(
        "What is the current price of Apple and how did it move today?"
    )

    # Flush asqav governance spans
    asqav.flush_spans()
