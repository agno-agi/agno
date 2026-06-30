"""
Team Streaming Metrics
=============================

Demonstrates how to capture metrics from team streaming responses.
Use yield_run_output=True to receive a TeamRunOutput at the end of the stream.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.team import Team
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
assistant = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Helpful assistant that answers questions.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Streaming Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[assistant],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team (Streaming)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = None
    for event in team.run("Count from 1 to 5.", stream=True, yield_run_output=True):
        if isinstance(event, TeamRunOutput):
            response = event

    if response and response.metrics:
        print("=" * 50)
        print("STREAMING TEAM METRICS")
        print("=" * 50)
        pprint(response.metrics)

        print("=" * 50)
        print("MODEL DETAILS")
        print("=" * 50)
        if response.metrics.details:
            for model_type, model_metrics_list in response.metrics.details.items():
                print(f"\n{model_type}:")
                for model_metric in model_metrics_list:
                    pprint(model_metric)
