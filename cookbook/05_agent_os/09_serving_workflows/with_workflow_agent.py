"""
Chat with a WorkflowAgent through AgentOS
=========================================

A WorkflowAgent decides whether a new message should execute the workflow or
can be answered from workflow history. The --demo client sends both turns over
the served AgentOS API.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/with_workflow_agent.py
Try: Run this file with --demo in another terminal
"""

import argparse
import os

import httpx
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.workflow import Step, StepInput, StepOutput, Workflow, WorkflowAgent

# ---------------------------------------------------------------------------
# Create WorkflowAgent Workflow
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://localhost:7777")
WORKFLOW_ID = "brief-workflow-agent"
SESSION_ID = "workflow-agent-chat"


def draft_brief(step_input: StepInput) -> StepOutput:
    """Create a deterministic brief from the workflow input."""
    return StepOutput(
        content=(
            f"Brief topic: {step_input.input}\n"
            "Recommendation: define the operating contract, then verify it "
            "through the served API."
        )
    )


def add_next_step(step_input: StepInput) -> StepOutput:
    """Add an actionable next step to the previous workflow output."""
    previous = step_input.previous_step_content or ""
    return StepOutput(
        content=f"{previous}\nNext step: automate one end-to-end acceptance test."
    )


db = SqliteDb(
    id="workflow-agent-db",
    db_file="tmp/workflow_agent.db",
)

workflow_agent = WorkflowAgent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=(
        "Use the workflow for a new brief topic. Answer follow-up questions "
        "from workflow history when the requested information is already there."
    ),
    num_history_runs=4,
)

brief_workflow = Workflow(
    id=WORKFLOW_ID,
    name="Brief Workflow Agent",
    description="Create a brief, then chat about it from workflow history.",
    db=db,
    agent=workflow_agent,
    steps=[
        Step(name="Draft Brief", executor=draft_brief),
        Step(name="Add Next Step", executor=add_next_step),
    ],
)

agent_os = AgentOS(
    id="workflow-agent-os",
    db=db,
    workflows=[brief_workflow],
)
app = agent_os.get_app()


def send_message(client: httpx.Client, message: str) -> dict:
    """Send one non-streaming chat turn to the WorkflowAgent workflow."""
    response = client.post(
        f"/workflows/{WORKFLOW_ID}/runs",
        data={
            "message": message,
            "stream": "false",
            "session_id": SESSION_ID,
        },
    )
    response.raise_for_status()
    result = response.json()
    if result["status"] != "COMPLETED":
        raise RuntimeError(f"WorkflowAgent turn ended with {result['status']}")
    return result


def run_chat_demo() -> None:
    """Execute a new topic and a history-aware follow-up over HTTP."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        detail_response = client.get(f"/workflows/{WORKFLOW_ID}")
        detail_response.raise_for_status()
        detail = detail_response.json()
        if not detail["workflow_agent"]:
            raise RuntimeError("Workflow detail did not identify the WorkflowAgent")

        first = send_message(
            client,
            "Create a short brief about reliable agent infrastructure.",
        )
        follow_up = send_message(
            client,
            "What next step did the brief recommend? Answer from our history.",
        )

    print(f"WorkflowAgent exposed: {detail['workflow_agent']}")
    print(f"First run: {first['run_id']}")
    print(f"First response: {first['content']}")
    print(f"Follow-up run: {follow_up['run_id']}")
    print(f"Follow-up response: {follow_up['content']}")


# ---------------------------------------------------------------------------
# Run WorkflowAgent Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Chat with a server already running on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_chat_demo()
    else:
        agent_os.serve(app=app)
