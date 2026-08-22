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

# Set up tracing with both destinations:
# - the Agno database, queryable via db.get_trace() and the AgentOS traces API
# - Arize Phoenix, via the OTLP exporter
setup_tracing(
    db=db,
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
    response = await agent.arun("What is the current price of Tesla?")
    print(response.content)

    # The trace is now in the Agno database AND in Phoenix with the same
    # trace_id. Look it up by run_id:
    trace = db.get_trace(run_id=response.run_id)
    if trace:
        print(f"Trace ID: {trace.trace_id}")
        print(f"Total Spans: {trace.total_spans}")
        print(f"Duration: {trace.duration_ms}ms")
    else:
        print(
            "No trace found. Make sure openinference-instrumentation-agno is installed."
        )


if __name__ == "__main__":
    asyncio.run(main())
