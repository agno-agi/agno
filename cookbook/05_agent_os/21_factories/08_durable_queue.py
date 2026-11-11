"""
Queue Factory Runs Durably
==========================

Background runs on a factory ride the durable job queue like any other
component. The accepted ticket stores the request context the factory was
built with (user_id, session_id, raw factory_input, verified claims and
scopes), and whichever replica's worker claims the ticket invokes the factory
again with it - so the run survives a crash or deploy of the accepting replica.

The worker has no HTTP request. There, ctx.request is a QueuedRequest: falsy,
and any attribute read fails the run with an error naming the fix. Build the
component from the context's data fields only, and pass anything else through
factory_input or trusted claims set by middleware.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh), OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_factories/08_durable_queue.py
Try: In another terminal, rerun this file with --demo
"""

import json
import os
import sys
import time
from typing import Literal, cast

import httpx
from agno.agent import Agent, AgentFactory
from agno.db.postgres import PostgresDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, QueueConfig
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Create the Factories
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
db = PostgresDb(
    id="durable-factory-db",
    db_url=os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
)


class WriterInput(BaseModel):
    """Client-controlled configuration, validated at the door and on the worker."""

    style: Literal["haiku", "limerick"] = "haiku"


def build_writer(ctx: RequestContext) -> Agent:
    """Build the Agent from the context's data fields only."""
    config = cast(WriterInput, ctx.input)
    return Agent(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        instructions=f"Reply with a single {config.style} and nothing else.",
    )


def build_from_header(ctx: RequestContext) -> Agent:
    """Reads the live request: works inline, fails on the queue worker."""
    region = ctx.request.headers.get("x-region", "us")
    return Agent(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        instructions=f"Answer for the {region} region.",
    )


writer_factory = AgentFactory(
    id="durable-writer",
    name="Durable Writer",
    description="Builds a writer from validated factory_input.",
    db=db,
    factory=build_writer,
    input_schema=WriterInput,
)

header_factory = AgentFactory(
    id="header-writer",
    name="Header Writer",
    description="Builds an agent from a request header.",
    db=db,
    factory=build_from_header,
)

agent_os = AgentOS(
    id="durable-factory-os",
    description="AgentOS queueing factory-built runs on the durable job queue.",
    agents=[writer_factory, header_factory],
    db=db,
    queue=QueueConfig(durable=True),
)
app = agent_os.get_app()


def wait_for_run(
    client: httpx.Client, agent_id: str, run_id: str, session_id: str
) -> dict:
    """Poll the run until it leaves PENDING/RUNNING."""
    deadline = time.monotonic() + 60
    while True:
        run = client.get(
            f"/agents/{agent_id}/runs/{run_id}", params={"session_id": session_id}
        )
        run.raise_for_status()
        body = run.json()
        if body["status"] not in ("PENDING", "RUNNING") or time.monotonic() > deadline:
            return body
        time.sleep(0.5)


def run_demo() -> None:
    """Queue a run on each factory and show both outcomes."""
    with httpx.Client(base_url=BASE_URL, timeout=90.0) as client:
        client.get("/health").raise_for_status()

        accepted = client.post(
            f"/agents/{writer_factory.id}/runs",
            data={
                "message": "Write about job queues.",
                "factory_input": json.dumps({"style": "limerick"}),
                "user_id": "mira",
                "background": "true",
                "stream": "false",
            },
        )
        if accepted.status_code != 202:
            raise RuntimeError(
                f"Expected 202, got {accepted.status_code}: {accepted.text}"
            )
        run_id, session_id = accepted.json()["run_id"], accepted.json()["session_id"]
        run = wait_for_run(client, writer_factory.id, run_id, session_id)
        if run["status"] != "COMPLETED":
            raise RuntimeError(f"Queued factory run did not complete: {run}")
        ticket = client.get(f"/queue/jobs/{run_id}").json()
        context = ticket["payload"]["scope"]["context"]
        if context["input"] != {"style": "limerick"}:
            raise RuntimeError("The ticket did not carry the factory_input")

        rejected = client.post(
            f"/agents/{header_factory.id}/runs",
            headers={"x-region": "eu"},
            data={
                "message": "Hello",
                "user_id": "mira",
                "background": "true",
                "stream": "false",
            },
        )
        rejected.raise_for_status()
        failed = wait_for_run(
            client,
            header_factory.id,
            rejected.json()["run_id"],
            rejected.json()["session_id"],
        )
        if failed["status"] != "ERROR":
            raise RuntimeError(
                f"A factory reading ctx.request should fail on the worker: {failed}"
            )

    print(f"Writer run {run_id}: {run['status']}")
    print(f"Ticket context input: {context['input']}, claims: {context['claims']}")
    print(f"Output:\n{run['content']}")
    print(f"Header run: {failed['status']}")
    print(f"Reason: {failed['content']}")


# ---------------------------------------------------------------------------
# Run Factory AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        agent_os.serve(app=app)
