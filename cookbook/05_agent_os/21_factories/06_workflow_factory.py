"""
Build a Workflow per Request
============================

Register a WorkflowFactory that creates a fresh tenant-aware draft-and-edit
pipeline for every Workflow run.

Prerequisites: none beyond OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_factories/06_workflow_factory.py
Try: In another terminal, rerun this file with --demo
"""

import os
import sys

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.workflow import Step, Workflow, WorkflowFactory

# ---------------------------------------------------------------------------
# Create a Per-Request Workflow Factory
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
db = SqliteDb(id="workflow-factory-db", db_file="tmp/21_factories_workflow.db")


def build_content_pipeline(ctx: RequestContext) -> Workflow:
    """Build a tenant-aware draft-and-edit Workflow."""
    tenant = ctx.user_id or "anonymous"
    drafter = Agent(
        id="content-drafter",
        name="Content Drafter",
        model=OpenAIResponses(id="gpt-5.5"),
        instructions=(
            f"Draft concise content for tenant {tenant}. "
            "Include the tenant name in the draft."
        ),
    )
    editor = Agent(
        id="content-editor",
        name="Content Editor",
        model=OpenAIResponses(id="gpt-5.5"),
        instructions=(
            "Edit the supplied draft for clarity. Preserve the tenant name "
            "and return only the final version."
        ),
    )
    return Workflow(
        id="product-workflow-id-is-overridden",
        name="Tenant Content Pipeline",
        description="Draft then edit one tenant-specific message.",
        db=db,
        steps=[
            Step(name="draft", agent=drafter),
            Step(name="edit", agent=editor),
        ],
        add_workflow_history_to_steps=True,
    )


workflow_factory = WorkflowFactory(
    id="tenant-content-pipeline",
    name="Tenant Content Pipeline Factory",
    description="Builds a fresh draft-and-edit Workflow per request.",
    db=db,
    factory=build_content_pipeline,
)

agent_os = AgentOS(
    id="workflow-factory-os",
    description="AgentOS resolving a WorkflowFactory per request.",
    workflows=[workflow_factory],
)
app = agent_os.get_app()


def verify_workflow_resolution() -> None:
    """Inspect identity, persistence, event storage, and Workflow steps."""
    workflow = workflow_factory.resolve(
        RequestContext(user_id="acme"),
        expected_type=Workflow,
    )
    if workflow.id != workflow_factory.id or workflow.db is not db:
        raise RuntimeError("WorkflowFactory did not enforce identity and database")
    if workflow.store_events is not True or len(workflow.steps or []) != 2:
        raise RuntimeError("Resolved Workflow lost event storage or its steps")


def run_demo() -> None:
    """Discover and run the live Workflow factory."""
    verify_workflow_resolution()
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        health = client.get("/health")
        health.raise_for_status()

        workflows_response = client.get("/workflows")
        workflows_response.raise_for_status()
        factory = next(
            workflow
            for workflow in workflows_response.json()
            if workflow["id"] == workflow_factory.id
        )
        if factory["is_factory"] is not True:
            raise RuntimeError("Workflow discovery did not mark the factory")

        run_response = client.post(
            f"/workflows/{workflow_factory.id}/runs",
            data={
                "message": ("Write a two-sentence launch update for tenant acme."),
                "user_id": "acme",
                "stream": "false",
            },
        )
        run_response.raise_for_status()
        run = run_response.json()
        if run["status"] != "COMPLETED" or "acme" not in run["content"].lower():
            raise RuntimeError("The live Workflow factory run lost its tenant context")

    print(f"Health: {health.json()['status']}")
    print(f"Factory: {factory['id']} (is_factory={factory['is_factory']})")
    print("Resolved Workflow: 2 steps, factory DB, stored events")
    print(f"Run: {run['run_id']} -> {run['status']}")
    print(f"Response: {run['content']}")


# ---------------------------------------------------------------------------
# Run Factory AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        agent_os.serve(app=app)
