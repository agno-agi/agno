"""
Latitude Via OpenInference
==========================

Demonstrates instrumenting an Agno agent with OpenInference and sending traces to Latitude.
"""

import asyncio
import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Latitude's ingestion endpoint speaks standard OTLP over HTTP. The exporter
# appends "/v1/traces" to the base OTEL_EXPORTER_OTLP_ENDPOINT.
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://ingest.latitude.so"
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = (
    f"Authorization=Bearer {os.getenv('LATITUDE_API_KEY')},"
    f"X-Latitude-Project={os.getenv('LATITUDE_PROJECT')}"
)

tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))

# Start instrumenting agno
AgnoInstrumentor().instrument(tracer_provider=tracer_provider)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-5.2"),
    tools=[YFinanceTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
async def main() -> None:
    await agent.aprint_response(
        "What is the current price of Tesla? Then find the current price of NVIDIA",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
