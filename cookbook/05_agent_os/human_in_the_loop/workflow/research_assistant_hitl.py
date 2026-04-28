"""AgentOS Workflow HITL: Research Assistant (WebSocket, multi-step)

A multi-step workflow that demonstrates several HITL patterns:
1. collect_research_input  — pauses for user input (topic + details)
2. do_research             — agent runs a research step (no pause)
3. review_output           — pauses for output review (approve/reject/edit)

Workflow start, pause, continue, and reconnect all use the AgentOS workflow
WebSocket endpoint at /workflows/ws.

Run (server):
    .venvs/demo/bin/python cookbook/05_agent_os/human_in_the_loop/workflow/research_assistant_hitl.py

Frontend handoff:
    See cookbook/05_agent_os/human_in_the_loop/WORKFLOW_WEBSOCKET_HITL_FE.md

WebSocket test flow:
    Connect to ws://localhost:7777/workflows/ws

    Start:
        {"action":"start-workflow","workflow_id":"research-assistant","message":"start research"}

    Continue collect_research_input:
        {
          "action": "continue-workflow",
          "workflow_id": "research-assistant",
          "run_id": "<run_id from StepPaused>",
          "session_id": "<session_id from StepPaused>",
          "step_requirements": [
            {
              "step_name": "collect_research_input",
              "step_index": 0,
              "user_input": {
                "topic": "Artificial Intelligence in Healthcare",
                "extra_details": "Focus on diagnostic applications"
              }
            }
          ]
        }

    Continue confirm_research:
        {
          "action": "continue-workflow",
          "workflow_id": "research-assistant",
          "run_id": "<same run_id>",
          "session_id": "<same session_id>",
          "step_requirements": [
            {
              "step_name": "confirm_research",
              "step_index": 1,
              "confirmed": true
            }
          ]
        }
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.workflow.step import Step
from agno.workflow.types import OnReject, UserInputField
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/agent_os_research_hitl.db",
    session_table="research_hitl_sessions",
)

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

research_agent = Agent(
    name="ResearchAgent",
    model=OpenAIResponses(id="gpt-4o-mini"),
    instructions=[
        "You are a research assistant.",
        "Produce a concise, well-structured summary on the given topic.",
        "Include key facts, recent developments, and practical insights.",
        "Use the extra details provided by the user to focus your research.",
    ],
    db=db,
    telemetry=False,
)

summary_agent = Agent(
    name="SummaryAgent",
    model=OpenAIResponses(id="gpt-4o-mini"),
    instructions=[
        "You are a summary editor.",
        "Take the research output and produce a polished final summary.",
        "Keep it concise — no more than 3 paragraphs.",
    ],
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

research_workflow = Workflow(
    id="research-assistant",
    name="Research Assistant",
    description="Collects a research topic, does research, then lets you review the output",
    db=db,
    steps=[
        # Step 1: Pause for user input — what to research
        Step(
            name="collect_research_input",
            agent=research_agent,
            requires_user_input=True,
            user_input_message="Please provide your research request:",
            user_input_schema=[
                UserInputField(
                    name="topic",
                    field_type="str",
                    description="The main research topic or subject to investigate",
                    required=True,
                ),
                UserInputField(
                    name="extra_details",
                    field_type="str",
                    description="Additional context, specific aspects to focus on, or special requirements",
                    required=False,
                ),
            ],
        ),
        # Step 2: Pause for confirmation before running the expensive research
        Step(
            name="confirm_research",
            agent=research_agent,
            requires_confirmation=True,
            confirmation_message="Ready to start researching. This may take a moment. Continue?",
            on_reject=OnReject.cancel,
        ),
        # Step 3: Polish the output (no pause)
        Step(
            name="polish_summary",
            agent=summary_agent,
        ),
    ],
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="research-hitl-demo",
    description="Research assistant with HITL — user input + confirmation + output review",
    agents=[research_agent, summary_agent],
    workflows=[research_workflow],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="research_assistant_hitl:app", port=7777, reload=True)
