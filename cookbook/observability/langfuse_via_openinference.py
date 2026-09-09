"""
Langfuse Via OpenInference
==========================

Demonstrates instrumenting an Agno agent with OpenInference and sending traces to Langfuse.
"""

import asyncio
import base64
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
LANGFUSE_AUTH = base64.b64encode(
    f"{os.getenv('LANGFUSE_PUBLIC_KEY')}:{os.getenv('LANGFUSE_SECRET_KEY')}".encode()
).decode()
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
#     "https://us.cloud.langfuse.com/api/public/otel"  # US data region
# )
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
    "https://cloud.langfuse.com/api/public/otel"  # EU data region
)
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:3000/api/public/otel"  # Local deployment (>= v3.22.0)

os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {LANGFUSE_AUTH}"

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
