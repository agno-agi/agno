"""AgentOS Workflow HITL: User Input Required (WebSocket)

A workflow with a step that pauses for user input before the agent runs.
The workflow emits events through the AgentOS workflow WebSocket endpoint.

The frontend handles this flow:
1. Workflow runs, hits a step with requires_user_input=True
2. Backend emits StepPaused over /workflows/ws → frontend renders input form
3. User fills in the form and clicks Submit
4. Frontend sends action=continue-workflow with step_requirements
5. Backend resumes execution → WebSocket streams the remaining workflow events

Run (server):
    .venvs/demo/bin/python cookbook/05_agent_os/human_in_the_loop/workflow/user_input_hitl.py

Frontend handoff:
    See cookbook/05_agent_os/human_in_the_loop/WORKFLOW_WEBSOCKET_HITL_FE.md

WebSocket test flow:
    Connect to ws://localhost:7777/workflows/ws

    Start:
        {"action":"start-workflow","workflow_id":"user-input-hitl","message":"greet the user"}

    Continue after StepPaused:
        {
          "action": "continue-workflow",
          "workflow_id": "user-input-hitl",
          "run_id": "<run_id from StepPaused>",
          "session_id": "<session_id from StepPaused>",
          "step_requirements": [
            {
              "step_name": "collect_preferences",
              "step_index": 0,
              "user_input": {"name": "Alice", "greeting_type": "casual"}
            }
          ]
        }
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.workflow.step import Step
from agno.workflow.types import UserInputField
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/agent_os_workflow_hitl.db",
    session_table="workflow_hitl_sessions",
)

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

greeting_agent = Agent(
    name="GreetingAgent",
    model=OpenAIResponses(id="gpt-4o-mini"),
    instructions=[
        "You are a friendly greeting generator.",
        "Generate a personalized greeting using the user's name and preferred style.",
        "The user preferences are provided in the message.",
        "Keep it short — one or two sentences.",
    ],
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

greeting_workflow = Workflow(
    id="user-input-hitl",
    name="Greeting Workflow",
    description="A simple workflow that collects user preferences then generates a greeting",
    db=db,
    steps=[
        # Step 1: Pauses for user input (HITL)
        Step(
            name="collect_preferences",
            agent=greeting_agent,
            requires_user_input=True,
            user_input_message="Please provide your preferences for the greeting:",
            user_input_schema=[
                UserInputField(
                    name="name",
                    field_type="str",
                    description="The person's name to include in the greeting",
                    required=True,
                ),
                UserInputField(
                    name="greeting_type",
                    field_type="str",
                    description="Style: formal, casual, or enthusiastic",
                    required=False,
                ),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="workflow-hitl-demo",
    description="AgentOS Workflow HITL demo — user input via WebSocket",
    agents=[greeting_agent],
    workflows=[greeting_workflow],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="user_input_hitl:app", port=7777, reload=True)
