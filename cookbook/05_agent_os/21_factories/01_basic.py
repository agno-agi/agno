"""
Build an Agent per Request
==========================

Register an AgentFactory that creates a fresh tenant-aware Agent for every
run. The factory owns the public ID and database inherited by each product.

Prerequisites: none beyond OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_factories/01_basic.py
Try: In another terminal, rerun this file with --demo
"""

import os
import sys

import httpx
from agno.agent import Agent, AgentFactory
from agno.db.sqlite import SqliteDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create a Per-Request Agent Factory
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
db = SqliteDb(id="basic-factory-db", db_file="tmp/21_factories_basic.db")


def build_tenant_agent(ctx: RequestContext) -> Agent:
    """Build one isolated Agent for the current caller."""
    tenant = ctx.user_id or "anonymous"
    return Agent(
        id="product-id-is-overridden",
        model=OpenAIResponses(id="gpt-5.5"),
        instructions=(
            f"You are the assistant for tenant {tenant}. "
            "Always include the tenant name in your concise reply."
        ),
    )


tenant_factory = AgentFactory(
    id="tenant-assistant",
    name="Tenant Assistant",
    description="Builds a fresh tenant-aware Agent for every request.",
    db=db,
    factory=build_tenant_agent,
)

agent_os = AgentOS(
    id="basic-factory-os",
    description="AgentOS resolving one AgentFactory per request.",
    agents=[tenant_factory],
)
app = agent_os.get_app()


def verify_resolution_contract() -> None:
    """Prove the factory enforces identity, database, events, and freshness."""
    first = tenant_factory.resolve(
        RequestContext(user_id="mira"),
        expected_type=Agent,
    )
    second = tenant_factory.resolve(
        RequestContext(user_id="mira"),
        expected_type=Agent,
    )
    if first is second:
        raise RuntimeError("AgentFactory reused a produced Agent")
    if first.id != tenant_factory.id:
        raise RuntimeError("Factory ID did not override the produced Agent ID")
    if first.db is not db:
        raise RuntimeError("Produced Agent did not inherit the factory database")
    if first.store_events is not True:
        raise RuntimeError("Factory resolution did not force store_events")


def run_demo() -> None:
    """Inspect factory discovery and run a live tenant-specific Agent."""
    verify_resolution_contract()
    with httpx.Client(base_url=BASE_URL, timeout=90.0) as client:
        health = client.get("/health")
        health.raise_for_status()

        agents_response = client.get("/agents")
        agents_response.raise_for_status()
        factory = next(
            agent
            for agent in agents_response.json()
            if agent["id"] == tenant_factory.id
        )
        if factory["is_factory"] is not True or factory["db_id"] != db.id:
            raise RuntimeError("Factory discovery metadata is incomplete")

        run_response = client.post(
            f"/agents/{tenant_factory.id}/runs",
            data={
                "message": "Introduce yourself and identify my tenant.",
                "user_id": "mira",
                "session_id": "basic-factory-session",
                "stream": "false",
            },
        )
        run_response.raise_for_status()
        run = run_response.json()
        if run["status"] != "COMPLETED" or "mira" not in run["content"].lower():
            raise RuntimeError("The live factory run lost its tenant context")

    print(f"Health: {health.json()['status']}")
    print(f"Factory: {factory['id']} (is_factory={factory['is_factory']})")
    print("Resolution: fresh Agent, enforced ID, inherited DB, stored events")
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
