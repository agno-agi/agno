"""
MLflow Via Autolog
==================

Demonstrates tracing an Agno agent with MLflow's built-in autolog integration.

Requirements:
    pip install mlflow agno

Start MLflow:
    mlflow server --host 127.0.0.1 --port 5000

Then open http://127.0.0.1:5000 to view traces.

NOTE: You can also configure the tracking URI and experiment via environment
variables instead of calling the Python APIs:

    export MLFLOW_TRACKING_URI="http://127.0.0.1:5000"
    export MLFLOW_EXPERIMENT_NAME="Agno Agent"
"""

import mlflow
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Setup — must be called BEFORE mlflow.agno.autolog()
# ---------------------------------------------------------------------------

# Point MLflow at a running tracking server
mlflow.set_tracking_uri("http://127.0.0.1:5000")
mlflow.set_experiment("Agno Agent")

# Enable MLflow tracing for Agno
mlflow.agno.autolog()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[YFinanceTools()],
    instructions="Use tables to display data. Don't include any other text.",
    markdown=True,
)
agent.print_response("What is the stock price of Apple?", stream=False)
