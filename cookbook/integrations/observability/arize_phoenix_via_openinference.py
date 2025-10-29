"""
This example shows how to instrument your agno agent with OpenInference and send traces to Arize Phoenix.

1. Install dependencies: pip install arize-phoenix openai openinference-instrumentation-agno opentelemetry-sdk opentelemetry-exporter-otlp
2. Setup your Arize Phoenix account and get your API key: https://phoenix.arize.com/.
3. Set your Arize Phoenix API key as an environment variable:
  - export PHOENIX_API_KEY=<your-key>
"""

import asyncio
import os

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from phoenix.otel import register
from pydantic import BaseModel

os.environ["PHOENIX_API_KEY"] = os.getenv("PHOENIX_API_KEY")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = (
    "https://app.phoenix.arize.com/"  # Add the suffix for your organization
)
# configure the Phoenix tracer
tracer_provider = register(
    project_name="default",  # Default is 'default'
    auto_instrument=True,  # Automatically use the installed OpenInference instrumentation
)


class StockPrice(BaseModel):
    stock_price: float


agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[YFinanceTools()],
    db=InMemoryDb(),
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    session_id="test_123",
    output_schema=StockPrice,
)

asyncio.run(agent.aprint_response("What is the current price of Tesla?", stream=True))
