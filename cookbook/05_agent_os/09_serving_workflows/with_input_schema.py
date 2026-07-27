"""
Expose a Workflow input schema
==============================

Define a Pydantic input_schema on a served workflow, then use --demo to fetch
GET /workflows/{id} and inspect the JSON schema AgentOS exposes to clients.

Prerequisites: OPENAI_API_KEY is needed only for workflow runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/with_input_schema.py
Try: Run this file with --demo in another terminal
"""

import argparse
import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.workflow import Step, Workflow
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Schema-Driven Workflow
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://localhost:7777")
WORKFLOW_ID = "research-brief-workflow"


class ResearchBrief(BaseModel):
    """Structured inputs rendered as fields by an AgentOS client."""

    topic: str = Field(description="Topic to investigate")
    focus_areas: list[str] = Field(description="Specific areas to cover")
    target_audience: str = Field(description="Who will read the research")
    sources_required: int = Field(
        default=3,
        ge=1,
        description="Minimum number of sources to consider",
    )


db = SqliteDb(
    id="workflow-input-schema-db",
    db_file="tmp/workflow_input_schema.db",
)

research_agent = Agent(
    id="schema-research-agent",
    name="Schema Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Follow the structured research brief and return a concise plan.",
)

research_workflow = Workflow(
    id=WORKFLOW_ID,
    name="Research Brief Workflow",
    description="Create a plan from a structured research brief.",
    db=db,
    input_schema=ResearchBrief,
    steps=[Step(name="Create Research Plan", agent=research_agent)],
)

agent_os = AgentOS(
    id="workflow-input-schema-os",
    db=db,
    workflows=[research_workflow],
)
app = agent_os.get_app()


def show_input_schema() -> None:
    """Fetch the served workflow detail and verify its JSON schema."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()

        detail_response = client.get(f"/workflows/{WORKFLOW_ID}")
        detail_response.raise_for_status()
        detail = detail_response.json()

    input_schema = detail["input_schema"]
    properties = input_schema["properties"]
    required = set(input_schema["required"])
    expected = {"topic", "focus_areas", "target_audience", "sources_required"}

    if set(properties) != expected:
        raise RuntimeError("Workflow detail returned an unexpected input schema")
    if required != {"topic", "focus_areas", "target_audience"}:
        raise RuntimeError("Workflow detail returned unexpected required fields")

    print(f"Health: {health_response.json()['status']}")
    print(f"Workflow: {detail['id']}")
    print(f"Input schema title: {input_schema['title']}")
    print(f"Form fields: {list(properties)}")
    print(f"Required fields: {sorted(required)}")


# ---------------------------------------------------------------------------
# Run Input Schema Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Fetch workflow detail from a server already running on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        show_input_schema()
    else:
        agent_os.serve(app=app)
