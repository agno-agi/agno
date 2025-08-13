"""
This example shows how to instrument your agno agent with OpenInference and send traces to Arize Phoenix.

1. Install dependencies: pip install arize-phoenix openai openinference-instrumentation-agno opentelemetry-sdk opentelemetry-exporter-otlp
2. Run `phoenix serve` to start the local collector.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from phoenix.otel import register

os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "http://localhost:6006"
# configure the Phoenix tracer
tracer_provider = register(
    project_name="agno-stock-price-agent",  # Default is 'default'
    auto_instrument=True,  # Automatically use the installed OpenInference instrumentation
)

agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    debug_mode=True,
)

agent.print_response("What is the current price of Tesla?")
