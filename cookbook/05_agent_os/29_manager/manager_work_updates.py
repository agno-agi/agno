"""Super Agent says when background work has finished, without being asked.

Super Agent starts a slow workflow in the background and answers at once. When the workflow ends,
AgentOS gives the conversation one run of Super Agent, called a work update. Super Agent reads the
result and reports it, and the reply is stored in the conversation like any other.

A work update reads and reports. Nobody is present, so it cannot start, accept, approve or change
anything. It is started only when no other run is going in the conversation, and at most three
times in a row before the person speaks again.

Turn it off with OSManager(work_updates=False). Each work update is a model run.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_work_updates.py
"""

import asyncio
import time
from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from agno.workflow import Step, StepInput, StepOutput, Workflow
from fastapi.testclient import TestClient

SECONDS = 20
SESSION = "demo-chat"
Path("tmp").mkdir(exist_ok=True)
db = SqliteDb(db_file=f"tmp/manager_work_updates_{int(time.time())}.db")


async def investigate(step_input: StepInput) -> StepOutput:
    await asyncio.sleep(SECONDS)
    return StepOutput(content="The nightly export fails because the job still uses the old IAM role.")


investigator = Workflow(
    id="investigator",
    name="Investigator",
    description="Investigates an incident. Takes a while.",
    db=db,
    steps=[Step(name="investigate", executor=investigate)],
)
agent_os = AgentOS(
    name="Work updates demo",
    db=db,
    workflows=[investigator],
    manager=OSManager(model=OpenAIResponses(id="gpt-5.6-luna"), access_docs=False),
    telemetry=False,
)
app = agent_os.get_app()


def turns() -> list:
    """The conversation's stored turns, oldest first."""
    rows, _ = db.get_runs(session_id=SESSION, deserialize=False)
    return [row for row in rows if row.get("parent_run_id") is None]


if __name__ == "__main__":
    with TestClient(app) as client:
        message = "Run the Investigator on last night's export failure in the background."
        response = client.post(
            "/teams/superagent/runs",
            data={"message": message, "session_id": SESSION, "user_id": "sam", "stream": "false"},
        )
        response.raise_for_status()
        print(f"> {message}")
        print("  " + (response.json().get("content") or "").replace("\n", "\n  "))

        print(f"\nSending nothing. Waiting for the Investigator ({SECONDS} seconds) and the work update.")
        deadline = time.monotonic() + SECONDS + 60
        while time.monotonic() < deadline:
            stored = turns()
            if len(stored) > 1 and stored[-1]["status"] == "COMPLETED":
                break
            time.sleep(1)

        update = turns()[-1]
        print("\nThe conversation now holds a reply nobody asked for:")
        print("  " + str(update["run_data"].get("content")).replace("\n", "\n  "))
        print("\nIts input, written by AgentOS:")
        print("  " + str(update["run_data"]["input"]["input_content"]).replace("\n", "\n  "))
        print("\nIts mark:", update["run_data"]["metadata"].get("agno_work_update"))
