"""
Arize Phoenix Via setup_tracing
===============================

Demonstrates exporting the same traces to Arize Phoenix and to the Agno
database at the same time using setup_tracing().

Both exporters are attached to the same tracer provider, so both destinations
receive the same spans with the same trace_id. The trace can be looked up by
run_id in the Agno database (or the AgentOS traces API) and the same trace_id
identifies the trace in Phoenix.
"""

import asyncio
import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools
from agno.tracing import setup_tracing
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Set up database
db = SqliteDb(db_file="tmp/traces.db")

# Set up tracing with Arize Phoenix:
setup_tracing(
    exporters=[
        OTLPSpanExporter(
            # For Phoenix Cloud spaces use https://app.phoenix.arize.com/s/<your-space>/v1/traces
            # The endpoint is used as-is, so it must include the /v1/traces path.
            endpoint="https://app.phoenix.arize.com/v1/traces",
            headers={"authorization": f"Bearer {os.getenv('PHOENIX_API_KEY')}"},
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
    db=db,
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
