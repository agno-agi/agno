"""
Run a Schedule inside AgentOS
=============================

Serve a Postgres-backed AgentOS scheduler, seed one minute schedule before
startup, and observe a naturally claimed run appear in persisted history.

Prerequisites: OPENAI_API_KEY and ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/01_run_in_agentos.py
Try: Run this file with --demo in another terminal and wait for the next minute
"""

import os
import sys
import time

import httpx
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.scheduler import ScheduleManager

# ---------------------------------------------------------------------------
# Create Scheduled AgentOS
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ai:ai@localhost:5532/ai",
)
AGENT_ID = "scheduled-greeter"
OS_ID = "scheduler-agent-os"
SCHEDULE_NAME = "natural-minute-greeting"
SCHEDULER_POLL_INTERVAL_SECONDS = 5
SCHEDULE_TIMEOUT_SECONDS = 120
OBSERVER_MARGIN_SECONDS = 15
OBSERVER_TIMEOUT_SECONDS = (
    60
    + SCHEDULER_POLL_INTERVAL_SECONDS
    + SCHEDULE_TIMEOUT_SECONDS
    + OBSERVER_MARGIN_SECONDS
)

db = PostgresDb(
    id="scheduler-agent-os-db",
    db_url=DATABASE_URL,
    schedules_table="agent_os_scheduler_schedules",
    schedule_runs_table="agent_os_scheduler_runs",
)

scheduled_agent = Agent(
    id=AGENT_ID,
    name="Scheduled Greeter",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Reply with one concise sentence confirming the scheduled run.",
)

agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS with a Postgres-backed schedule poller.",
    agents=[scheduled_agent],
    db=db,
    scheduler=True,
    scheduler_poll_interval=SCHEDULER_POLL_INTERVAL_SECONDS,
    scheduler_base_url=BASE_URL,
)
app = agent_os.get_app()


def seed_schedule() -> None:
    """Create a fresh schedule whose first due time follows server startup."""
    manager = ScheduleManager(db)
    try:
        for existing in manager.list(limit=1000, page=1):
            if existing.name == SCHEDULE_NAME:
                manager.delete(existing.id)

        seconds_to_next_minute = 60 - (int(time.time()) % 60)
        if seconds_to_next_minute < 12:
            time.sleep(seconds_to_next_minute + 1)

        schedule = manager.create(
            name=SCHEDULE_NAME,
            cron="* * * * *",
            endpoint=f"/agents/{AGENT_ID}/runs",
            description="A naturally firing one-minute AgentOS schedule.",
            payload={
                "message": "Confirm that this naturally scheduled run fired.",
                "session_id": "natural-scheduler-session",
            },
            timezone="UTC",
            timeout_seconds=SCHEDULE_TIMEOUT_SECONDS,
        )
        print(f"Seeded schedule: {schedule.id}")
        print(f"First due time: {schedule.next_run_at}")
    finally:
        manager.close()


def watch_natural_run() -> None:
    """Wait for the poller to create a new persisted schedule-run row."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()
        config_response = client.get("/config")
        config_response.raise_for_status()
        config = config_response.json()

        schedules_response = client.get(
            "/schedules",
            params={"limit": 100, "page": 1},
        )
        schedules_response.raise_for_status()
        schedules_payload = schedules_response.json()
        schedule = next(
            (
                item
                for item in schedules_payload["data"]
                if item["name"] == SCHEDULE_NAME
            ),
            None,
        )
        if schedule is None:
            raise RuntimeError(f"Schedule not found: {SCHEDULE_NAME}")

        runs_path = f"/schedules/{schedule['id']}/runs"
        initial_response = client.get(runs_path, params={"limit": 100, "page": 1})
        initial_response.raise_for_status()
        initial_ids = {run["id"] for run in initial_response.json()["data"]}

        print(f"Health: {health_response.json()['status']}")
        print(f"AgentOS: {config['os_id']}")
        print(f"Agent: {config['agents'][0]['id']}")
        print(f"Schedule: {schedule['id']}")
        print("Waiting for the next natural cron firing...")

        deadline = time.monotonic() + OBSERVER_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            history_response = client.get(
                runs_path,
                params={"limit": 100, "page": 1},
            )
            history_response.raise_for_status()
            history = history_response.json()
            new_runs = [run for run in history["data"] if run["id"] not in initial_ids]
            finished = [
                run
                for run in new_runs
                if run["status"] in {"success", "failed", "paused", "timeout"}
            ]
            if finished:
                run = finished[0]
                if run["status"] != "success":
                    raise RuntimeError(
                        f"Natural schedule run ended with {run['status']}: "
                        f"{run.get('error')}"
                    )
                print(f"Schedule run: {run['id']}")
                print(f"Agent run: {run['run_id']}")
                print(f"History total: {history['meta']['total_count']}")
                print(f"Status: {run['status']}")
                return
            time.sleep(2)

    raise TimeoutError(
        f"No natural schedule run completed within {OBSERVER_TIMEOUT_SECONDS} seconds"
    )


# ---------------------------------------------------------------------------
# Run Scheduled AgentOS or Observer
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        watch_natural_run()
    else:
        seed_schedule()
        agent_os.serve(app=app)
