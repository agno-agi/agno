"""
Continue and checkpoints over the AgentOS API
=============================================
Serve a ClaudeAgent through AgentOS and use the same continue endpoints as
native agents:

    GET  /agents/{agent_id}/runs/{run_id}/checkpoints?session_id=...
    POST /agents/{agent_id}/runs/{run_id}/continue

Run normally to serve AgentOS; pass --verify for a live end-to-end check
through the HTTP API.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/05_agentos_api.py
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/05_agentos_api.py --verify

Then call the API:
    # Start a run
    curl -X POST http://localhost:7777/agents/continue-demo/runs \
        -F "message=Run echo alpha with Bash, then echo beta in a separate call, then reply DONE." \
        -F "session_id=demo" -F "stream=false"

    # List its checkpoints
    curl "http://localhost:7777/agents/continue-demo/runs/<run_id>/checkpoints?session_id=demo"

    # Fork from a checkpoint
    curl -X POST http://localhost:7777/agents/continue-demo/runs/<run_id>/continue \
        -F "session_id=demo" -F "continue_from=3" -F "fork=true" -F "stream=false" \
        -F "input=List every echo command you have run, nothing else."

    # Continue a finished run with a new instruction (streamed)
    curl -N -X POST http://localhost:7777/agents/continue-demo/runs/<run_id>/continue \
        -F "session_id=demo" -F "continue_from=end" -F "input=Reply with exactly: ok"
"""

import json
import sys
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

AGENT_ID = "continue-demo"

db = SqliteDb(db_file="tmp/claude-agent-sdk-continue.db")
agent = ClaudeAgent(
    id=AGENT_ID,
    name="Continue Demo",
    model="claude-sonnet-4-6",
    db=db,
    allowed_tools=["Bash"],
    permission_mode="bypassPermissions",
    max_turns=6,
    max_budget_usd=0.5,
)
agent_os = AgentOS(agents=[agent], db=db)
app = agent_os.get_app()


def verify():
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(prefix="agno-continue-") as workdir:
        agent.db = SqliteDb(db_file=str(Path(workdir) / "runs.db"))
        agent.cwd = workdir
        session_id = "agentos-api"
        with TestClient(AgentOS(agents=[agent], db=agent.db).get_app()) as client:
            # 1. Start a two-step tool run.
            response = client.post(
                f"/agents/{AGENT_ID}/runs",
                data={
                    "message": "Run `echo alpha` with Bash. After it finishes, run `echo beta` in a "
                    "separate Bash call. Then reply with just DONE.",
                    "session_id": session_id,
                    "stream": "false",
                },
            )
            assert response.status_code == 200, response.text
            run = response.json()
            print(f"Run {run['run_id'][:8]}: {run['status']} {run['content']!r}")

            # 2. List checkpoints.
            response = client.get(
                f"/agents/{AGENT_ID}/runs/{run['run_id']}/checkpoints",
                params={"session_id": session_id},
            )
            assert response.status_code == 200, response.text
            checkpoints = response.json()["checkpoints"]
            print(
                "Checkpoints:", [(c["message_index"], c["reason"]) for c in checkpoints]
            )

            # 3. Fork from the first checkpoint.
            first_step = checkpoints[0]["message_index"]
            response = client.post(
                f"/agents/{AGENT_ID}/runs/{run['run_id']}/continue",
                data={
                    "session_id": session_id,
                    "continue_from": str(first_step),
                    "fork": "true",
                    "stream": "false",
                    "input": "List every echo command you have run in this conversation, nothing else.",
                },
            )
            assert response.status_code == 200, response.text
            branch = response.json()
            assert branch["forked_from_run_id"] == run["run_id"]
            print(f"Branch from step {first_step}: {branch['content']!r}")

            # 4. Continue the finished run from its end, streamed.
            response = client.post(
                f"/agents/{AGENT_ID}/runs/{run['run_id']}/continue",
                data={
                    "session_id": session_id,
                    "continue_from": "end",
                    "stream": "true",
                    "input": "Reply with exactly: ok",
                },
            )
            assert response.status_code == 200, response.text
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            kinds = [event.get("event") for event in events]
            print(
                f"Streamed continuation: {len(events)} events, first={kinds[0]} last={kinds[-1]}"
            )
            assert kinds[-1] == "RunCompleted", kinds

            # 5. The session holds the source run and two sibling runs.
            response = client.get(
                f"/sessions/{session_id}/runs", params={"type": "agent"}
            )
            runs = response.json()
            print("Session runs:")
            for item in runs:
                lineage = (item.get("forked_from_run_id") or "")[:8] or "-"
                print(f"  {item['run_id'][:8]} {item['status']} forked_from={lineage}")
            assert len(runs) == 3
    print("PASS: checkpoints, fork and continue work over the AgentOS API")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        agent_os.serve(app="05_agentos_api:app", reload=False)
