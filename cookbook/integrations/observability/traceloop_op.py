"""
Integrate Agno with Traceloop to send traces and gain insights into your agent's performance.

Prerequisites:
- Traceloop account
- Traceloop API key

Steps:
1. `pip install agno openai traceloop-sdk`
2. Set the Traceloop API key as an environment variable: `export TRACELOOP_API_KEY=<your-api-key>`
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import workflow

Traceloop.init(app_name="agno_workflows")

agent = Agent(
    name="AnalysisAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    debug_mode=True,
)


@workflow(name="data_analysis_pipeline")
def analyze_data(query: str) -> str:
    """Custom workflow that wraps agent execution."""
    response = agent.run(query)
    return response.content


# The workflow decorator creates a parent span
result = analyze_data("Analyze the benefits of observability in AI systems")
print(result)
