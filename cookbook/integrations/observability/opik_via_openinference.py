"""
Instrument your Agno agents with OpenTelemetry and stream traces to Opik for rich debugging, cost tracking, and production monitoring.

1. Install dependencies:
   pip install -U opik agno openai opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-agno
2. Point the OTLP exporter at the Opik collector:
   - Opik Cloud:
     export OTEL_EXPORTER_OTLP_ENDPOINT=https://www.comet.com/opik/api/v1/private/otel
     export OTEL_EXPORTER_OTLP_HEADERS='Authorization=<your-api-key>,Comet-Workspace=<workspace>,projectName=<project>'
   - Self-hosted:
     export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:5173/api/v1/private/otel
     export OTEL_EXPORTER_OTLP_HEADERS='projectName=<project>'
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

# Configure OpenTelemetry to export spans to Opik
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
trace_api.set_tracer_provider(tracer_provider)

# Enable automatic instrumentation for Agno
AgnoInstrumentor().instrument()

agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    instructions="You are a stock price analyst. Answer with concise, well-sourced updates.",
    debug_mode=True,
    trace_attributes={
        "session.id": "demo-session-001",
        "environment": "development",
    },
)

if __name__ == "__main__":
    # The span hierarchy (agent → model → tool) will appear in Opik for every request
    agent.print_response(
        "What is the current price of Apple and how did it move today?"
    )
