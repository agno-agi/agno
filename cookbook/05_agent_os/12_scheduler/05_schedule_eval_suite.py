"""
Schedule an Eval Suite in AgentOS
=================================

Serve a Postgres-backed AgentOS scheduler with a registered eval suite, seed a
one-minute schedule that runs the suite, and observe the schedule run and the
suite's eval run it points to.

Prerequisites: OPENAI_API_KEY and ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/05_schedule_eval_suite.py
Try: Run this file with --demo in another terminal and wait for the next minute
"""

import os
import sys
import time

import httpx
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.eval import Case, EvalSuite
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.scheduler import ScheduleManager
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Scheduled AgentOS
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ai:ai@localhost:5532/ai",
)
AGENT_ID = "scheduled-math-tutor"
SUITE_ID = "nightly-math-quality"
OS_ID = "scheduler-eval-suite-os"
SCHEDULE_NAME = "natural-minute-eval-suite"
SCHEDULER_POLL_INTERVAL_SECONDS = 5
SCHEDULE_TIMEOUT_SECONDS = 180
OBSERVER_MARGIN_SECONDS = 15
OBSERVER_TIMEOUT_SECONDS = (
    60
    + SCHEDULER_POLL_INTERVAL_SECONDS
    + SCHEDULE_TIMEOUT_SECONDS
    + OBSERVER_MARGIN_SECONDS
)

db = PostgresDb(
    id="scheduler-eval-suite-os-db",
    db_url=DATABASE_URL,
    schedules_table="eval_suite_scheduler_schedules",
    schedule_runs_table="eval_suite_scheduler_runs",
)

math_tutor = Agent(
    id=AGENT_ID,
    name="Scheduled Math Tutor",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[CalculatorTools()],
    instructions="Use the calculator tools for any arithmetic.",
)

suite = EvalSuite(
    id=SUITE_ID,
    name="Nightly math quality",
    cases=(
        Case(
            name="multiplies",
            agent=math_tutor,
            input="What is 12 times 7?",
            expected_tool_calls=("multiply",),
        ),
        Case(
            name="adds",
            agent=math_tutor,
            input="What is 40 plus 2?",
            expected_tool_calls=("add",),
        ),
    ),
)

agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS that runs an eval suite on a schedule.",
    agents=[math_tutor],
    eval_suites=[suite],
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
            endpoint=f"/eval-suites/{SUITE_ID}/runs",
            description="A naturally firing one-minute eval suite run.",
            timezone="UTC",
            timeout_seconds=SCHEDULE_TIMEOUT_SECONDS,
        )
        print(f"Seeded schedule: {schedule.id}")
        print(f"First due time: {schedule.next_run_at}")
    finally:
        manager.close()


def watch_natural_run() -> None:
    """Wait for the poller to record a suite run, then read the eval run it ran."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()

        schedules_response = client.get(
            "/schedules",
            params={"limit": 100, "page": 1},
        )
        schedules_response.raise_for_status()
        schedule = next(
            (
                item
                for item in schedules_response.json()["data"]
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
        print(f"Schedule: {schedule['id']}")
        print("Waiting for the next natural cron firing...")

        deadline = time.monotonic() + OBSERVER_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            history_response = client.get(
                runs_path,
                params={"limit": 100, "page": 1},
            )
            history_response.raise_for_status()
            new_runs = [
                run
                for run in history_response.json()["data"]
                if run["id"] not in initial_ids
            ]
            finished = [
                run
                for run in new_runs
                if run["status"]
                in {"success", "failed", "paused", "cancelled", "timeout"}
            ]
            if finished:
                run = finished[0]
                if run["run_id"] is None:
                    raise RuntimeError(
                        f"Natural schedule run ended with {run['status']}: "
                        f"{run.get('error')}"
                    )
                # A FAIL suite fails the schedule run with "N of M cases failed".
                print(f"Schedule run: {run['id']}")
                print(f"Status: {run['status']}")
                print(f"Error: {run.get('error')}")
                eval_run_response = client.get(f"/eval-runs/{run['run_id']}")
                eval_run_response.raise_for_status()
                summary = eval_run_response.json()["eval_data"]["summary"]
                print(f"Eval run: {run['run_id']}")
                print(
                    f"Suite: {summary['status']}, "
                    f"{summary['passed']} of {summary['total']} passed"
                )
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
