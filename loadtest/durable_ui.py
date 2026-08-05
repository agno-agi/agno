"""Durable multi-worker AgentOS for the AgentOS UI + real-time worker tracing.

This is `libs/agno/agno/test.py`'s durable-agent, but wired for the multi-
container fleet (2 replicas + nginx LB + shared Postgres + shared Redis) so you
can point the AgentOS UI at http://localhost:7777 and watch WHICH replica's
worker claims/executes each background run in real time.

What it adds over test.py:
  - container-internal hostnames (postgres:5432 / redis:6379) so replicas talk
    over the docker network;
  - MODEL=real|stub (real by default) via the shared make_model();
  - a per-worker CLAIM/COMPLETE log hook: each replica prints
        [replica1] CLAIMED   run=<id> component=<id>
        [replica1] COMPLETED run=<id> status=<status>
    so the combined `docker compose logs -f` (prefixed replica1-1 / replica2-1)
    tells you exactly which worker handled each run.

Run it in the fleet:  see loadtest/README (or ./run.sh ui  once wired).
"""

import os

from agno.agent import Agent
from agno.job_queue.config import QueueConfig
from agno.os import AgentOS
from agno.tools import Toolkit
from agno.tools.user_control_flow import UserControlFlowTools

# Reuse the harness's model factory (respects MODEL=real|stub) and DB wiring.
from app import _int, db, make_model  # noqa: E402

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
# A stable, human-readable label for THIS replica (set per-service in compose).
# Falls back to the container hostname if unset.
WORKER_LABEL = os.environ.get("WORKER_LABEL") or os.environ.get("HOSTNAME", "worker")


# --- HITL user-input agent (from cookbook/02_agents/10_human_in_the_loop) ----
# UserControlFlowTools lets the agent PAUSE mid-run to ask the user for missing
# input (e.g. an email's to_address). The run pauses with a needs_user_input
# requirement; the UI collects the field(s) and continues it - and here that
# whole pause/continue rides the DURABLE multi-worker queue, so the pause
# survives crashes and the continue can land on either replica.
class EmailTools(Toolkit):
    def __init__(self, *args, **kwargs):
        super().__init__(name="EmailTools", tools=[self.send_email, self.get_emails], *args, **kwargs)

    def send_email(self, subject: str, body: str, to_address: str) -> str:
        """Send an email to the given address with the given subject and body.

        Args:
            subject (str): The subject of the email.
            body (str): The body of the email.
            to_address (str): The address to send the email to.
        """
        return f"Sent email to {to_address} with subject {subject} and body {body}"

    def get_emails(self, date_from: str, date_to: str) -> list[dict]:
        """Get all emails between the given dates.

        Args:
            date_from (str): The start date (in YYYY-MM-DD format).
            date_to (str): The end date (in YYYY-MM-DD format).
        """
        return [
            {"subject": "Hello", "body": "Hello, world!", "to_address": "test@test.com", "date": date_from},
            {"subject": "Random other email", "body": "This is a random other email", "to_address": "john@doe.com", "date": date_to},
        ]


durable_agent = Agent(
    id="durable-agent",
    name="Durable HITL Agent",
    model=make_model(),
    tools=[EmailTools(), UserControlFlowTools()],
    markdown=True,
    description="A HITL agent that pauses to ask the user for input - durable across crashes and replicas",
    db=db,
)

agent_os = AgentOS(
    id="durable-ui-os",
    description="Durable multi-worker AgentOS (UI + per-worker tracing)",
    agents=[durable_agent],
    db=db,
    queue=QueueConfig(
        durable=True,
        redis=REDIS_URL,
        max_concurrency=_int("MAX_CONCURRENCY", 8),
        max_queue_depth=_int("MAX_QUEUE_DEPTH", 1000),
        max_attempts=_int("MAX_ATTEMPTS", 1),
        allow_multi_attempt_experimental=_int("MAX_ATTEMPTS", 1) > 1,
        lock_grace_seconds=_int("LOCK_GRACE", 60),
        timeout_seconds=_int("TIMEOUT_SECONDS", 3600),
    ),
)
app = agent_os.get_app()


# --- Per-worker CLAIM/COMPLETE tracing --------------------------------------
# The worker's claim/complete are quiet by default; wrap the queue store so each
# replica prints which run it claimed and how it finished. This is the "which
# worker did what" signal you watch in the combined docker logs.
def _install_worker_tracing() -> None:
    from agno.os import job_queue as _jq

    _orig_init = _jq.QueueWorker.__init__

    def _init(self, *a, **k):
        _orig_init(self, *a, **k)
        store = self.store

        _claim = store.claim_job
        _complete = store.complete_job

        async def _traced_claim(*ca, **ck):
            job = await _claim(*ca, **ck)
            if job:
                print(
                    f"[{WORKER_LABEL}] CLAIMED   run={job.get('id')} "
                    f"component={job.get('component_id')} "
                    f"{'(continue)' if (job.get('payload') or {}).get('continue') else ''}",
                    flush=True,
                )
            return job

        async def _traced_complete(job_id, worker_id, attempt, status, error=None, *ca, **ck):
            print(f"[{WORKER_LABEL}] COMPLETED run={job_id} status={status}", flush=True)
            return await _complete(job_id, worker_id, attempt, status, error, *ca, **ck)

        # only wrap once per store instance
        if not getattr(store, "_ui_traced", False):
            store.claim_job = _traced_claim  # type: ignore[assignment]
            store.complete_job = _traced_complete  # type: ignore[assignment]
            store._ui_traced = True  # type: ignore[attr-defined]

    _jq.QueueWorker.__init__ = _init  # type: ignore[assignment]


_install_worker_tracing()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("durable_ui:app", host="0.0.0.0", port=int(os.environ.get("PORT", 7777)), reload=False)
