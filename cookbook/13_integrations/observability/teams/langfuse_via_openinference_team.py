import base64
import os
from uuid import uuid4

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

LANGFUSE_AUTH = base64.b64encode(
    f"{os.getenv('LANGFUSE_PUBLIC_KEY')}:{os.getenv('LANGFUSE_SECRET_KEY')}".encode()
).decode()
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
    "https://us.cloud.langfuse.com/api/public/otel"  # 🇺🇸 US data region
)
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]="https://cloud.langfuse.com/api/public/otel" # 🇪🇺 EU data region
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]="http://localhost:3000/api/public/otel" # 🏠 Local deployment (>= v3.22.0)

os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {LANGFUSE_AUTH}"


tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))

# Start instrumenting agno
AgnoInstrumentor().instrument(tracer_provider=tracer_provider)

# First agent for market data
market_data_agent = Agent(
    name="Market Data Agent",
    role="Fetch and analyze stock market data",
    id="market-data",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[YFinanceTools()],
    instructions=[
        "You are a market data specialist.",
        "Focus on current stock prices and key metrics.",
        "Always present data in tables.",
    ],
)

# Second agent for news and research
news_agent = Agent(
    name="News Research Agent",
    role="Research company news",
    id="news-research",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You are a financial news analyst.",
        "Focus on recent company news and developments.",
        "Always cite your sources.",
    ],
)

# Create team with both agents
financial_team = Team(
    name="Financial Analysis Team",
    id=str(uuid4()),
    user_id=str(uuid4()),
    model=OpenAIChat(id="gpt-4.1"),
    members=[
        market_data_agent,
        news_agent,
    ],
    instructions=[
        "Coordinate between market data and news analysis.",
        "First get market data, then relevant news.",
        "Combine the information into a clear summary.",
    ],
    show_members_responses=True,
    markdown=True,
)

if __name__ == "__main__":
    financial_team.print_response(
        "Analyze Tesla (TSLA) stock - provide both current market data and recent significant news.",
        stream=True,
    )
