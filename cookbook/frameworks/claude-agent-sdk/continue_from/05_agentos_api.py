"""
Continue and checkpoints over the AgentOS API
=============================================
Serve a ClaudeAgent through AgentOS and use the same continue endpoints as
native agents:

    GET  /agents/{agent_id}/runs/{run_id}/checkpoints?session_id=...
    POST /agents/{agent_id}/runs/{run_id}/continue

Run normally to serve AgentOS; pass --verify for a live end-to-end check
through the HTTP API: a three-step analysis of a CSV file, its checkpoint
list, a fork after the first step, and a streamed follow-up on the finished
run.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/05_agentos_api.py
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/05_agentos_api.py --verify

Then call the API (the server runs in the current directory, so give it a CSV to look at):
    # Start a run
    curl -X POST http://localhost:7777/agents/continue-demo/runs \
        -F "message=Count the data rows in sales.csv with Bash, then sum its amount column with awk in a second call, then reply rows=<n> total=<sum>." \
        -F "session_id=demo" -F "stream=false"

    # List its checkpoints
    curl "http://localhost:7777/agents/continue-demo/runs/<run_id>/checkpoints?session_id=demo"

    # Fork from the first checkpoint
    curl -X POST http://localhost:7777/agents/continue-demo/runs/<run_id>/continue \
        -F "session_id=demo" -F "continue_from=3" -F "fork=true" -F "stream=false" \
        -F "input=Without tools: what do you know about sales.csv so far?"

    # Continue the finished run with a follow-up (streamed)
    curl -N -X POST http://localhost:7777/agents/continue-demo/runs/<run_id>/continue \
        -F "session_id=demo" -F "continue_from=end" -F "input=Which region had the largest single amount?"
"""

import json
import sys
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

AGENT_ID = "continue-demo"

SALES_CSV = """region,amount
north,120
south,80
east,200
west,45
north,55
"""

db = SqliteDb(db_file="tmp/claude-agent-sdk-continue.db")
agent = ClaudeAgent(
    id=AGENT_ID,
    name="Continue Demo",
    model="claude-sonnet-4-6",
    db=db,
    allowed_tools=["Bash"],
    permission_mode="bypassPermissions",
    max_turns=8,
    max_budget_usd=0.5,
)
agent_os = AgentOS(agents=[agent], db=db)
app = agent_os.get_app()


def verify():
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(prefix="agno-continue-") as workdir:
        (Path(workdir) / "sales.csv").write_text(SALES_CSV)
        agent.db = SqliteDb(db_file=str(Path(workdir) / "runs.db"))
        agent.cwd = workdir
        agent.system_prompt = (
            f"Your working directory is {workdir}. Use Bash for every step."
        )
        session_id = "agentos-api"
        with TestClient(AgentOS(agents=[agent], db=agent.db).get_app()) as client:
            # 1. Start a three-step tool run.
            response = client.post(
                f"/agents/{AGENT_ID}/runs",
                data={
                    "message": "sales.csv has a header row and an amount column. Do these steps in "
                    "order, one Bash call each, waiting for each result before the next: "
                    "(1) count the data rows with `tail -n +2 sales.csv | wc -l`; "
                    "(2) sum the amount column with awk; "
                    "(3) print the largest amount and its region with sort. "
                    "Then reply with just: rows=<n> total=<sum> max=<region>.",
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
            print("Checkpoints:")
            for checkpoint in checkpoints:
                print(
                    f"  {checkpoint['message_index']}: {checkpoint['reason']} {checkpoint['message_preview']!r}"
                )

            # 3. Fork from the first checkpoint and ask what the branch knows.
            first_step = checkpoints[0]["message_index"]
            response = client.post(
                f"/agents/{AGENT_ID}/runs/{run['run_id']}/continue",
                data={
                    "session_id": session_id,
                    "continue_from": str(first_step),
                    "fork": "true",
                    "stream": "false",
                    "input": "Do not run any tools. From this conversation only: how many data rows does "
                    "sales.csv have, and what is the total of the amount column? If you have not "
                    "computed one of them yet, say exactly 'not computed yet' for it.",
                },
            )
            assert response.status_code == 200, response.text
            branch = response.json()
            assert branch["forked_from_run_id"] == run["run_id"]
            branch_tools = [
                m for m in branch.get("messages", []) if m.get("role") == "tool"
            ]
            kept_tools = [
                m for m in run["messages"][:first_step] if m.get("role") == "tool"
            ]
            assert len(branch_tools) == len(kept_tools), (
                "the branch should carry only the kept tool results"
            )
            print(f"Branch from step {first_step}: {branch['content']!r}")

            # 4. Continue the finished run from its end, streamed.
            response = client.post(
                f"/agents/{AGENT_ID}/runs/{run['run_id']}/continue",
                data={
                    "session_id": session_id,
                    "continue_from": "end",
                    "stream": "true",
                    "input": "Without running tools: which region had the largest single amount? "
                    "Reply with just the region.",
                },
            )
            assert response.status_code == 200, response.text
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            kinds = [event.get("event") for event in events]
            final = next(
                (e for e in reversed(events) if e.get("event") == "RunCompleted"), None
            )
            assert final is not None, kinds
            print(
                f"Streamed follow-up: {len(events)} events, answer={final.get('content')!r}"
            )

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
