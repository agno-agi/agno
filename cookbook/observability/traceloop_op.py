"""
Traceloop Integration
=====================

Demonstrates wrapping Agno calls in Traceloop workflow spans.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
Traceloop.init(app_name="agno_workflows")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="AnalysisAgent",
    model=OpenAIChat(id="gpt-5.2"),
    debug_mode=True,
)


@workflow(name="data_analysis_pipeline")
def analyze_data(query: str) -> str:
    """Custom workflow that wraps agent execution."""
    response = agent.run(query)
    return response.content


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The workflow decorator creates a parent span
    result = analyze_data("Analyze the benefits of observability in AI systems")
    print(result)
