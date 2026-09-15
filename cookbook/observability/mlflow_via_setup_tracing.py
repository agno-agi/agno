"""
MLflow Via setup_tracing
========================

Demonstrates sending traces to MLflow using Agno's setup_tracing() with an
external OTLP exporter. setup_tracing() attaches all exporters to a single
tracer provider and instruments Agno automatically, so there is no need to
call AgnoInstrumentor().instrument() manually. A database can also be passed
to setup_tracing() to export the same traces to the Agno database at the
same time.

Requirements:
    pip install -U mlflow opentelemetry-exporter-otlp-proto-http openinference-instrumentation-agno

Start MLflow with OTLP tracing enabled:
    mlflow server --host 127.0.0.1 --port 5000

    On macOS, port 5000 may be taken by AirPlay (ControlCenter). Use another
    port and point MLFLOW_TRACKING_URI at it:
        mlflow server --host 127.0.0.1 --port 5001
        export MLFLOW_TRACKING_URI=http://127.0.0.1:5001

View traces:
    Open the MLflow UI (the tracking URI) in a browser and select the
    experiment (Default = experiment id 0), then open the Traces tab.
"""

import asyncio
import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools
from agno.tracing import setup_tracing
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")

# Set up tracing with an external exporter - this instruments ALL agents automatically.
# Pass db=... as well to also export the same traces to the Agno database.
setup_tracing(
    exporters=[
        OTLPSpanExporter(
            endpoint=f"{MLFLOW_TRACKING_URI}/v1/traces",
            headers={"x-mlflow-experiment-id": "0"},
        )
    ],
)


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
