"""
Tool Call Metrics
=============================

Demonstrates tool execution timing metrics.
Each tool call records start_time, end_time, and duration.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_output = agent.run("What is the stock price of AAPL and NVDA?")

    # Run-level metrics show total tokens across all model calls
    print("=" * 50)
    print("RUN METRICS")
    print("=" * 50)
    pprint(run_output.metrics)

    # Each tool call in the run carries its own timing metrics
    print("=" * 50)
    print("TOOL CALL METRICS")
    print("=" * 50)
    if run_output.tools:
        for tool_call in run_output.tools:
            print(f"Tool: {tool_call.tool_name}")
            if tool_call.metrics:
                pprint(tool_call.metrics)
            print("-" * 40)

    # Per-model breakdown from details
    print("=" * 50)
    print("MODEL DETAILS")
    print("=" * 50)
    if run_output.metrics and run_output.metrics.details:
        for model_type, model_metrics_list in run_output.metrics.details.items():
            print(f"\n{model_type}:")
            for model_metric in model_metrics_list:
                pprint(model_metric)
