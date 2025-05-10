"""
This example shows how to instrument your agno agent with OpenInference and send traces to Arize Phoenix.

1. Install dependencies: pip install openai langfuse opentelemetry-sdk opentelemetry-exporter-otlp
2. Set your Langfuse API key as an environment variables: 
  - export LANGFUSE_PUBLIC_KEY=<your-key>
  - export LANGFUSE_SECRET_KEY=<your-key>
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
from opentelemetry import trace as trace_api
from openinference.instrumentation.agno import AgnoInstrumentor
 
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
trace_api.set_tracer_provider(tracer_provider=tracer_provider)

# Start instrumenting agno
AgnoInstrumentor().instrument()

agent = Agent(
    name="News Agent",  # For best results, set a name that will be used by the tracer
    model=OpenAIChat(id="gpt-4o-mini"), 
    tools=[DuckDuckGoTools()],
    markdown=True, 
    debug_mode=True,
)
response = agent.run("What is currently trending on Twitter?")
print(response.content)
