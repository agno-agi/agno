"""
Give an Agent Scheduler Tools
=============================

Give one Agent a SchedulerTools toolkit with a stable default endpoint and
payload, then verify the schedule it creates from a natural-language request.

Prerequisites: OPENAI_API_KEY and ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/04_scheduler_tools_agent.py
Try: Run this file with --demo in another terminal
"""

import os
import sys
from typing import Optional

import httpx
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.scheduler import SchedulerTools

# ---------------------------------------------------------------------------
# Create Scheduler-Enabled Agent
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ai:ai@localhost:5532/ai",
)
AGENT_ID = "scheduler-tools-agent"
OS_ID = "scheduler-tools-agent-os"
SCHEDULE_NAME = "scheduler-tools-daily-brief"
DEFAULT_ENDPOINT = f"/agents/{AGENT_ID}/runs"
DEFAULT_PAYLOAD = {
    "message": "Return the scheduled daily operations brief in one sentence.",
    "session_id": "scheduler-tools-execution",
}

db = PostgresDb(
    id="scheduler-tools-agent-db",
    db_url=DATABASE_URL,
    schedules_table="scheduler_tools_schedules",
    schedule_runs_table="scheduler_tools_runs",
)


class StableSchedulerTools(SchedulerTools):
    """Keep the agent-facing create schema on the configured execution target."""

    def __deepcopy__(self, memo: dict[int, object]) -> "StableSchedulerTools":
        """Share the toolkit's live database connection across copied agents."""
        memo[id(self)] = self
        return self

    def create_schedule(
        self,
        name: str,
        cron: str,
        description: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> str:
        """Create a schedule using this toolkit's fixed endpoint and payload."""
        return super().create_schedule(
            name=name,
            cron=cron,
            description=description,
            timezone=timezone,
        )

    async def acreate_schedule(
        self,
        name: str,
        cron: str,
        description: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> str:
        """Asynchronously create a schedule with the fixed execution target."""
        return await super().acreate_schedule(
            name=name,
            cron=cron,
            description=description,
            timezone=timezone,
        )


scheduler_tools = StableSchedulerTools(
    db=db,
    default_endpoint=DEFAULT_ENDPOINT,
    default_timezone="UTC",
    default_payload=DEFAULT_PAYLOAD,
)

scheduler_agent = Agent(
    id=AGENT_ID,
    name="Scheduler Tools Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[scheduler_tools],
    instructions=[
        "Create and manage recurring schedules with the scheduler tools.",
        "The create tool already fixes the canonical endpoint and payload.",
        "Use the exact name, time, timezone, and recurrence requested by the user.",
    ],
)

agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS exposing an agent with SchedulerTools.",
    agents=[scheduler_agent],
    db=db,
    scheduler=True,
    scheduler_poll_interval=5,
    scheduler_base_url=BASE_URL,
)
app = agent_os.get_app()


def find_schedule(client: httpx.Client) -> dict | None:
    """Return this lesson's schedule, if it exists."""
    response = client.get("/schedules", params={"limit": 100, "page": 1})
    response.raise_for_status()
    return next(
        (
            schedule
            for schedule in response.json()["data"]
            if schedule["name"] == SCHEDULE_NAME
        ),
        None,
    )


def run_agentic_demo() -> None:
    """Ask the live agent to create a schedule and verify stored defaults."""
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()
        config_response = client.get("/config")
        config_response.raise_for_status()
        config = config_response.json()

        existing = find_schedule(client)
        if existing is not None:
            delete_response = client.delete(f"/schedules/{existing['id']}")
            delete_response.raise_for_status()

        run_response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": (
                    f"Create a schedule named {SCHEDULE_NAME} for a daily run "
                    "at 9:00 UTC."
                ),
                "stream": "false",
                "session_id": "scheduler-tools-setup",
            },
        )
        run_response.raise_for_status()
        agent_run = run_response.json()
        if agent_run["status"] != "COMPLETED":
            raise RuntimeError(f"Agent run ended with {agent_run['status']}")

        schedule = find_schedule(client)
        if schedule is None:
            raise RuntimeError("SchedulerTools did not create the requested schedule")
        if schedule["endpoint"] != DEFAULT_ENDPOINT:
            raise RuntimeError("SchedulerTools did not preserve the default endpoint")
        if schedule["payload"] != DEFAULT_PAYLOAD:
            raise RuntimeError("SchedulerTools did not preserve the default payload")
        if schedule["cron_expr"] != "0 9 * * *" or schedule["timezone"] != "UTC":
            raise RuntimeError("SchedulerTools created the wrong cron or timezone")

        print(f"Health: {health_response.json()['status']}")
        print(f"AgentOS: {config['os_id']}")
        print(f"Agent: {config['agents'][0]['id']}")
        print(f"Agent run: {agent_run['run_id']}")
        print(f"Schedule: {schedule['id']}")
        print(f"Cron: {schedule['cron_expr']} {schedule['timezone']}")
        print(f"Endpoint: {schedule['endpoint']}")
        print(f"Payload: {schedule['payload']}")

        delete_response = client.delete(f"/schedules/{schedule['id']}")
        delete_response.raise_for_status()


# ---------------------------------------------------------------------------
# Run Scheduler AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_agentic_demo()
    else:
        agent_os.serve(app=app)
