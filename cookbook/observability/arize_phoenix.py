"""
This example shows how to instrument your agno agent with OpenInference and send traces to Arize Phoenix.

1. Install dependencies: pip install arize-phoenix openai openinference-instrumentation-agno opentelemetry-sdk opentelemetry-exporter-otlp
2. Setup your Arize Phoenix account and get your API key: https://phoenix.arize.com/ OR run Arize Phoenix locally: https://github.com/Arize-ai/phoenix. 
3. If running locally, run `phoenix serve` to start the listener.
4. If running through the cloud, set your Arize Phoenix API key as an environment variable:
  - export ARIZE_PHOENIX_API_KEY=<your-key>
"""

import base64
import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

endpoint = "http://127.0.0.1:6006/v1/traces"

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry import trace as trace_api
from openinference.instrumentation.agno import AgnoInstrumentor
 
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
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
