"""AgentOS under load test: durable, Redis-coordinated job queue.

One agent + one team + one workflow. REAL model end-to-end (OpenAIResponses,
gpt-5.5) so the queue runs the true prod path. Set MODEL=stub to fall back to
the free offline LatencyModel for pure throughput ramps.

Env:
  OPENAI_API_KEY  required unless MODEL=stub
  MODEL           "real" (default) | "stub"
  MODEL_ID        real model id (default gpt-5.5)
  PG_URL          postgres url (shared across replicas)
  REDIS_URL       redis url (shared across replicas)
  MAX_CONCURRENCY, MAX_QUEUE_DEPTH, LOCK_GRACE, MAX_ATTEMPTS, TIMEOUT_SECONDS
"""

import os

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig
from agno.os import AgentOS
from agno.team import Team
from agno.workflow import Step, Workflow

PG_URL = os.environ.get("PG_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
MODEL_KIND = os.environ.get("MODEL", "real").lower()
MODEL_ID = os.environ.get("MODEL_ID", "gpt-5.5")

db = PostgresDb(db_url=PG_URL)


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def make_model():
    """Fresh model instance per component (never share/reuse across agents)."""
    if MODEL_KIND == "stub":
        from stub_model import LatencyModel

        return LatencyModel()
    from agno.models.openai import OpenAIResponses

    return OpenAIResponses(id=MODEL_ID)


# Keep prompts SHORT to bound cost — a load test should not pay for long generations.
_TERSE = "Answer in one short sentence."


# --- HITL confirmation tool: the run pauses until /continue with the tool result ---
from agno.tools import tool  # noqa: E402


@tool(requires_confirmation=True)
def publish(title: str) -> str:
    """Publish an item (requires human approval before it runs)."""
    return f"published: {title}"


agent = Agent(id="load-agent", name="Load Agent", model=make_model(), instructions=_TERSE, db=db)

# Dedicated HITL agent — instructed to always call the confirmation tool.
hitl_agent = Agent(
    id="hitl-agent",
    name="HITL Agent",
    model=make_model(),
    tools=[publish],
    instructions="When asked to publish anything, call the publish tool. Keep replies short.",
    db=db,
)

team = Team(
    id="load-team",
    name="Load Team",
    model=make_model(),
    members=[Agent(id="load-member", name="Member", model=make_model(), instructions=_TERSE, db=db)],
    instructions=_TERSE,
    db=db,
)

workflow = Workflow(
    id="load-workflow",
    name="Load Workflow",
    db=db,
    steps=[
        Step(name="step-one", agent=Agent(id="wf-a", model=make_model(), instructions=_TERSE, db=db)),
        Step(name="step-two", agent=Agent(id="wf-b", model=make_model(), instructions=_TERSE, db=db)),
    ],
)

# WorkflowAgent-orchestrated workflow — exercises the two-run / orphan path.
from agno.workflow import WorkflowAgent  # noqa: E402

wf_agent_workflow = Workflow(
    id="load-wf-agent",
    name="Load WorkflowAgent Flow",
    agent=WorkflowAgent(model=make_model(), num_history_runs=3),
    steps=[
        Step(name="wfa-step-one", agent=Agent(id="wfa-a", model=make_model(), instructions=_TERSE, db=db)),
        Step(name="wfa-step-two", agent=Agent(id="wfa-b", model=make_model(), instructions=_TERSE, db=db)),
    ],
    db=db,
)

agent_os = AgentOS(
    id="loadtest-os",
    description="Load-test AgentOS with a durable Redis-coordinated job queue.",
    agents=[agent, hitl_agent],
    teams=[team],
    workflows=[workflow, wf_agent_workflow],
    db=db,
    # DURABLE=0 disables the queue -> background runs take the INLINE
    # (_arun_background) path. The WorkflowAgent empty-ghost regression only
    # manifests inline; with the durable queue on, the worker runs foreground
    # and never produces the ghost. So the regression test needs a non-durable
    # replica (DURABLE=0) to reproduce the FAIL.
    queue=(
        QueueConfig(
            durable=True,
            redis=REDIS_URL,
            max_concurrency=_int("MAX_CONCURRENCY", 8),
            max_queue_depth=_int("MAX_QUEUE_DEPTH", 1000),
            max_attempts=_int("MAX_ATTEMPTS", 1),
            lock_grace_seconds=_int("LOCK_GRACE", 60),
            timeout_seconds=_int("TIMEOUT_SECONDS", 3600),
        )
        if os.environ.get("DURABLE", "1") != "0"
        else None
    ),
)
app = agent_os.get_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 7777)), reload=False)
