"""
Streaming Metrics
=============================

Demonstrates how to capture metrics from streaming responses.
Use yield_run_output=True to receive a RunOutput at the end of the stream.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
)

# ---------------------------------------------------------------------------
# Run Agent (Streaming)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = None
    for event in agent.run("Count from 1 to 10.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            response = event

    if response and response.metrics:
        print("=" * 50)
        print("STREAMING RUN METRICS")
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
