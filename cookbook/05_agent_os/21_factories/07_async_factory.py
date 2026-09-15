"""
Use Sync and Async Factories Together
=====================================

Register one synchronous and one asynchronous AgentFactory on the same
AgentOS and call both through the same async-aware REST resolver.

Prerequisites: none beyond OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_factories/07_async_factory.py
Try: In another terminal, rerun this file with --demo
"""

import asyncio
import os
import sys

import httpx
from agno.agent import Agent, AgentFactory
from agno.db.sqlite import SqliteDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Sync and Async Factory Callables
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
db = SqliteDb(id="async-factory-db", db_file="tmp/21_factories_async.db")


def build_sync_agent(ctx: RequestContext) -> Agent:
    """Build an Agent through a synchronous factory callable."""
    user = ctx.user_id or "anonymous"
    return Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        instructions=f"Reply with exactly: sync factory served {user}",
    )


async def build_async_agent(ctx: RequestContext) -> Agent:
    """Build an Agent through an asynchronous factory callable."""
    await asyncio.sleep(0)
    user = ctx.user_id or "anonymous"
    return Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        instructions=f"Reply with exactly: async factory served {user}",
    )


sync_factory = AgentFactory(
    id="sync-factory-agent",
    name="Sync Factory Agent",
    description="Uses a synchronous factory callable.",
    db=db,
    factory=build_sync_agent,
)
async_factory = AgentFactory(
    id="async-factory-agent",
    name="Async Factory Agent",
    description="Uses an asynchronous factory callable.",
    db=db,
    factory=build_async_agent,
)

agent_os = AgentOS(
    id="async-factory-os",
    description="AgentOS resolving synchronous and asynchronous factories.",
    agents=[sync_factory, async_factory],
)
app = agent_os.get_app()


def run_demo() -> None:
    """Call both factory kinds through the same REST run contract."""
    if sync_factory.is_async() or not async_factory.is_async():
        raise RuntimeError("Factory callable kind detection is incorrect")

    runs: dict[str, dict] = {}
    with httpx.Client(base_url=BASE_URL, timeout=90.0) as client:
        health = client.get("/health")
        health.raise_for_status()
        for factory in (sync_factory, async_factory):
            response = client.post(
                f"/agents/{factory.id}/runs",
                data={
                    "message": "Identify the factory path.",
                    "user_id": "mira",
                    "stream": "false",
                },
            )
            response.raise_for_status()
            run = response.json()
            if run["status"] != "COMPLETED" or "mira" not in run["content"]:
                raise RuntimeError(f"{factory.id} did not complete correctly")
            runs[factory.id] = run

    print(f"Health: {health.json()['status']}")
    print(f"Sync callable detected: {not sync_factory.is_async()}")
    print(f"Async callable detected: {async_factory.is_async()}")
    for factory_id, run in runs.items():
        print(f"{factory_id}: {run['run_id']} -> {run['status']}")


# ---------------------------------------------------------------------------
# Run Factory AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        agent_os.serve(app=app)
