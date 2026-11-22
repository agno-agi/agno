"""
Metadata Resolution
=============================

Demonstrates the three-layer metadata resolution for Workflows:
  workflow.metadata < session.metadata < call-site metadata

Session-stored metadata overrides workflow defaults, and call-site
metadata overrides both. This works for both sync and async runs.
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.session.workflow import WorkflowSession
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = InMemoryDb()

# Pre-seed a session with metadata (simulates a returning user)
session = WorkflowSession(
    session_id="demo-session",
    workflow_id="metadata-demo-workflow",
    metadata={
        "user_tier": "premium",  # Will override workflow's "free"
        "session_pref": "dark_mode",  # Session-only key
    },
    created_at=int(time.time()),
)
db.upsert_session(session)


# ---------------------------------------------------------------------------
# Create a simple agent and step
# ---------------------------------------------------------------------------
echo_agent = Agent(
    name="Echo Agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=["Echo back the input briefly."],
)


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    id="metadata-demo-workflow",
    name="Metadata Demo Workflow",
    steps=[Step(name="echo", agent=echo_agent)],
    db=db,
    metadata={
        "user_tier": "free",  # Will be overridden by session
        "workflow_env": "production",  # Workflow-only key
    },
)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
async def run_async_demo() -> None:
    print("\n=== Async run with all three layers ===")
    result = await workflow.arun(
        input="async test",
        session_id="demo-session",
        metadata={"user_tier": "vip"},
    )
    print(f"Metadata: {result.metadata}")
    print(f"  user_tier = '{result.metadata['user_tier']}' (call-site wins)")
    print(f"  session_pref = '{result.metadata['session_pref']}' (from session)")
    print(f"  workflow_env = '{result.metadata['workflow_env']}' (from workflow)")


if __name__ == "__main__":
    # Session metadata overrides workflow metadata
    print("=== Session overrides workflow (sync) ===")
    result1 = workflow.run(input="test1", session_id="demo-session")
    print(f"Metadata: {result1.metadata}")
    print(
        f"  user_tier = '{result1.metadata['user_tier']}' (session wins over workflow)"
    )

    # Call-site metadata overrides both
    print("\n=== Call-site overrides all (sync) ===")
    result2 = workflow.run(
        input="test2",
        session_id="demo-session",
        metadata={"user_tier": "enterprise", "request_id": "req-123"},
    )
    print(f"Metadata: {result2.metadata}")
    print(f"  user_tier = '{result2.metadata['user_tier']}' (call-site wins)")

    # Async run
    asyncio.run(run_async_demo())

    # New session uses workflow defaults
    print("\n=== New session uses workflow defaults ===")
    result4 = workflow.run(input="test4", session_id="new-session")
    print(f"Metadata: {result4.metadata}")
    print(f"  user_tier = '{result4.metadata['user_tier']}' (workflow default)")

    print("\n" + "=" * 50)
    print("Resolution order: workflow < session < call-site")
    print("=" * 50)
