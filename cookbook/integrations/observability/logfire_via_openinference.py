"""
This example shows how to instrument your agno agent with OpenInference and send traces to Logfire.

Sign up to Logfire at https://logfire.dev

1. Install dependencies: pip install openai langfuse opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-agno
2. Either self-host or sign up for an account at https://logfire.dev
3. Set your Logfire API key as an environment variables:
  - export LOGFIRE_WRITE_TOKEN=<your-key>
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

LOGFIRE_WRITE_TOKEN = os.getenv("LOGFIRE_WRITE_TOKEN")

# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
#     "https://logfire-us.pydantic.dev"  # 🇺🇸 US data region
# )
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
    "https://logfire-eu.pydantic.dev"  # 🇪🇺 EU data region
)
# os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] = 'http://localhost:4318' # 🏠 Local deployment

os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization={LOGFIRE_WRITE_TOKEN}"


tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))

# Start instrumenting agno
AgnoInstrumentor().instrument(tracer_provider=tracer_provider)


agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
)

asyncio.run(
    agent.aprint_response(
        "What is the current price of Tesla? Then find the current price of NVIDIA",
        stream=True,
    )
)
