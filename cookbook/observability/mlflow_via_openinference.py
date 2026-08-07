"""
MLflow Via OpenInference
========================

Demonstrates instrumenting an Agno agent with OpenInference and sending traces to MLflow.

Requirements:
    pip install -U mlflow opentelemetry-exporter-otlp-proto-http openinference-instrumentation-agno

Start MLflow with OTLP tracing enabled:
    mlflow server --host 127.0.0.1 --port 5000
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
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")

endpoint = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/traces"

tracer_provider = TracerProvider()
tracer_provider.add_span_processor(
    SimpleSpanProcessor(
        OTLPSpanExporter(
            endpoint=endpoint,
            headers={"x-mlflow-experiment-id": "0"},
        )
    )
)
# Start instrumenting agno
AgnoInstrumentor().instrument(tracer_provider=tracer_provider)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o"),
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
