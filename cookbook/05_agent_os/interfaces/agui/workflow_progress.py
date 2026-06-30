"""
Workflow Progress (native AG-UI STATE)
======================================

A simple SEQUENTIAL workflow whose live progress renders out of the box in any
AG-UI client -- no custom event handling required. As each step runs, the AG-UI
interface maintains a flat ``state.workflow_progress.steps`` list (each entry:
name, status, step_index, output) via STATE_SNAPSHOT/STATE_DELTA -- the one AG-UI
channel that auto-renders -- plus native STEP_STARTED/STEP_FINISHED for protocol
consistency. No structural CustomEvent is emitted.

This is the "simple case" the native-first rework unlocks: point CopilotKit / the
Dojo at POST /agui and render ``state.workflow_progress.steps`` with
``useCoAgentStateRender`` -- the same pattern the ``agentic_generative_ui`` example
uses for ``state.steps``. A sample render component ships with this feature (see the
PR description).

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/agui/workflow_progress.py
then point an AG-UI client at http://localhost:9001/agui.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

MODEL_ID = "gpt-5.5"
PORT = 9001

researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id=MODEL_ID),
    instructions="Research the topic and return three concise factual bullets.",
    markdown=True,
)
analyst = Agent(
    name="Analyst",
    model=OpenAIResponses(id=MODEL_ID),
    instructions="Analyze the research and state the single most important insight.",
    markdown=True,
)
summarizer = Agent(
    name="Summarizer",
    model=OpenAIResponses(id=MODEL_ID),
    instructions="Write a one-paragraph summary for a busy reader.",
    markdown=True,
)

# Three named steps run in order. Each step's start/finish updates
# state.workflow_progress.steps, so an AG-UI client renders live progress.
progress_workflow = Workflow(
    name="Research Pipeline",
    description="Research, analyze, then summarize -- a simple sequential workflow.",
    steps=[
        Step(name="research", agent=researcher),
        Step(name="analyze", agent=analyst),
        Step(name="summarize", agent=summarizer),
    ],
)

# Setup your AgentOS app
agent_os = AgentOS(
    workflows=[progress_workflow],
    interfaces=[AGUI(workflow=progress_workflow)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    # reload=False keeps a single serving process (set reload=True for auto-reload during development).
    agent_os.serve(app="workflow_progress:app", reload=False, port=PORT)
