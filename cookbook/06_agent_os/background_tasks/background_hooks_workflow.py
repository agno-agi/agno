"""
Example: Background Hooks with Workflows in AgentOS

This example demonstrates how to use background hooks with a Workflow.
Background hooks execute after the API response is sent, making them non-blocking.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run.agent import RunOutput
from agno.workflow import Workflow


async def log_step_completion(run_output: RunOutput, agent: Agent) -> None:
    """
    Background post-hook on the agent that runs after each step completes.
    """
    print(f"[Background Hook] Agent '{agent.name}' completed step")
    print(f"[Background Hook] Run ID: {run_output.run_id}")

    # Simulate async work
    await asyncio.sleep(1)
    print(f"[Background Hook] Logged metrics for {agent.name}")


# Create agents for the workflow steps
analyzer = Agent(
    name="Analyzer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Analyze the input and identify key points.",
    post_hooks=[log_step_completion],
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Summarize the analysis into a brief response.",
    post_hooks=[log_step_completion],
)

# Create the workflow
analysis_workflow = Workflow(
    id="analysis-workflow",
    name="AnalysisWorkflow",
    description="Analyzes input and provides a summary",
    steps=[analyzer, summarizer],
    db=AsyncSqliteDb(db_file="tmp/workflow.db"),
)

# Create AgentOS with background hooks enabled
agent_os = AgentOS(
    workflows=[analysis_workflow],
    run_hooks_in_background=True,
)

app = agent_os.get_app()

# Example request:
# curl -X POST http://localhost:7777/workflows/analysis-workflow/runs \
#   -F "message=Explain the benefits of exercise" \
#   -F "stream=false"

if __name__ == "__main__":
    agent_os.serve(app="background_hooks_workflow:app", port=7777, reload=True)
