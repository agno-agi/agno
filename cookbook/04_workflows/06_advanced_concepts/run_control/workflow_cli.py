"""
Workflow CLI
============

Demonstrates using `Workflow.cli_app()` for interactive command-line workflow runs.
"""

import os
import sys

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow import Workflow
from agno.workflow.step import Step

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
assistant_agent = Agent(
    name="CLI Assistant",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="Answer clearly and provide concise, actionable output.",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
assistant_step = Step(name="Assistant", agent=assistant_agent)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Workflow CLI Demo",
    description="Simple workflow used to demonstrate the built-in CLI app.",
    steps=[assistant_step],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    starter_prompt = os.getenv(
        "WORKFLOW_CLI_PROMPT",
        "Create a three-step plan for shipping a workflow feature.",
    )

    if sys.stdin.isatty():
        print("Starting interactive workflow CLI. Type 'exit' to stop.")
        workflow.cli_app(
            input=starter_prompt,
            stream=True,
            user="Developer",
            exit_on=["exit", "quit"],
        )
    else:
        print("Non-interactive environment detected; running a single response.")
        workflow.print_response(input=starter_prompt, stream=True)
        print("Run this script in a terminal to use interactive cli_app mode.")
