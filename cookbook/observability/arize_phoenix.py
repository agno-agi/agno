"""
This example shows how to instrument your agno agent with OpenInference and send traces to Arize Phoenix.

1. Install dependencies: pip install arize-phoenix openai openinference-instrumentation-openai opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc opentelemetry-distro
2. Setup your Arize Phoenix account and get your API key: https://phoenix.arize.com/ OR run Arize Phoenix locally: https://github.com/Arize-ai/phoenix. If running locally, run `phoenix serve` to start the listener.
3. Set your Arize Phoenix API key as an environment variable:
  - export ARIZE_PHOENIX_API_KEY=<your-key>
"""

import base64
import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

LANGFUSE_AUTH = base64.b64encode(f"{os.getenv('LANGFUSE_PUBLIC_KEY')}:{os.getenv('LANGFUSE_SECRET_KEY')}".encode()).decode()

os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]="https://us.cloud.langfuse.com/api/public/otel" # 🇺🇸 US data region
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]="https://cloud.langfuse.com/api/public/otel" # 🇪🇺 EU data region
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]="http://localhost:3000/api/public/otel" # 🏠 Local deployment (>= v3.22.0)
 
os.environ["OTEL_EXPORTER_OTLP_HEADERS"]=f"Authorization=Basic {LANGFUSE_AUTH}"

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
 
trace_provider = TracerProvider()
trace_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
 
# Sets the global default tracer provider
from opentelemetry import trace
trace.set_tracer_provider(trace_provider)
 
# Creates a tracer from the global tracer provider
tracer = trace.get_tracer(__name__)

import openlit
# Initialize OpenLIT instrumentation. The disable_batch flag is set to true to process traces immediately.
openlit.init(tracer=tracer, disable_batch=True)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"), 
    tools=[DuckDuckGoTools()],
    markdown=True, 
    debug_mode=True,
)

agent.run("What is currently trending on Twitter?")
