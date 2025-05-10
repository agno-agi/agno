"""
This example shows how to instrument your agno agent with OpenInference and send traces to LangSmith.

1. Create a LangSmith account and get your API key: https://smith.langchain.com/
2. Set your LangSmith API key as an environment variable:
  - export LANGSMITH_API_KEY=<your-key>
3. Install dependencies: pip install openai openinference-instrumentation-agno opentelemetry-sdk opentelemetry-exporter-otlp
"""

import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry import trace as trace_api
from openinference.instrumentation.agno import AgnoInstrumentor

endpoint = "https://api.smith.langchain.com/otel"
headers = {"x-api-key": os.getenv("LANGSMITH_API_KEY")}

tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint, headers=headers)))
trace_api.set_tracer_provider(tracer_provider=tracer_provider)

# Start instrumenting agno
AgnoInstrumentor().instrument()

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
    debug_mode=True,
)

agent.run("What is currently trending on Twitter?")
