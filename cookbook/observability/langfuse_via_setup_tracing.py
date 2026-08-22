"""
Langfuse Via setup_tracing
==========================

Demonstrates sending traces to Langfuse using Agno's setup_tracing() with an
external OTLP exporter. setup_tracing() attaches all exporters to a single
tracer provider and instruments Agno automatically, so there is no need to
call AgnoInstrumentor().instrument() manually.
"""

import asyncio
import base64
import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools
from agno.tracing import setup_tracing
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

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

# Set up tracing with an external exporter - this instruments ALL agents automatically
setup_tracing(exporters=[OTLPSpanExporter()])


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIResponses(id="gpt-5.5"),
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
