"""
LangSmith Via OpenInference
===========================

Demonstrates instrumenting an Agno agent with OpenInference and sending traces to LangSmith.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
endpoint = "https://eu.api.smith.langchain.com/otel/v1/traces"
headers = {
    "x-api-key": os.getenv("LANGSMITH_API_KEY"),
    "Langsmith-Project": os.getenv("LANGSMITH_PROJECT"),
}

tracer_provider = TracerProvider()
tracer_provider.add_span_processor(
    SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
)

# Start instrumenting agno
AgnoInstrumentor().instrument(tracer_provider=tracer_provider)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Market Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    markdown=True,
    debug_mode=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is news on the stock market?")
