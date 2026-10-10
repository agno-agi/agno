"""
ClaudeAgent metrics on AgentOS
==============================
Serve a ClaudeAgent through AgentOS and read its metrics the way the UI does:
tokens and cost on each run, totals on the session, the token column in the
sessions list, and the daily aggregation on the metrics page.

Run normally to serve AgentOS; pass --verify to drive two runs through the
HTTP API and print what each endpoint reports.

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/metrics_agentos.py
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/metrics_agentos.py --verify

Then open the AgentOS UI, chat with the agent, and check the session's metrics
and the Metrics page. Or with curl:
    curl -X POST http://localhost:7777/agents/claude-metrics/runs \
        -F "message=Reply with exactly OK." -F "session_id=demo" -F "stream=false" | jq .metrics
    curl "http://localhost:7777/sessions/demo?type=agent" | jq .metrics
    curl "http://localhost:7777/metrics" | jq
"""

import json
import sys
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

AGENT_ID = "claude-metrics"

db = SqliteDb(db_file="tmp/claude-agent-sdk-metrics.db")
agent = ClaudeAgent(
    id=AGENT_ID,
    name="Claude Metrics",
    model="claude-sonnet-4-6",
    db=db,
    allowed_tools=["Bash"],
    permission_mode="bypassPermissions",
    max_turns=4,
    max_budget_usd=0.5,
)
agent_os = AgentOS(agents=[agent], db=db)
app = agent_os.get_app()


def verify():
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(prefix="agno-metrics-") as workdir:
        agent.db = SqliteDb(db_file=str(Path(workdir) / "runs.db"))
        agent.cwd = workdir
        session_id = "metrics-agentos"
        with TestClient(AgentOS(agents=[agent], db=agent.db).get_app()) as client:
            # 1. A non-streamed run: metrics are on the run output.
            response = client.post(
                f"/agents/{AGENT_ID}/runs",
                data={
                    "message": "Reply with exactly the word OK.",
                    "session_id": session_id,
                    "stream": "false",
                },
            )
            assert response.status_code == 200, response.text
            run = response.json()
            metrics = run["metrics"]
            print("Run 1 metrics:")
            print(
                f"  total_tokens={metrics['total_tokens']} cost=${metrics.get('cost', 0):.4f} duration={metrics['duration']:.2f}s"
            )
            for model in metrics["details"]["model"]:
                print(
                    f"  model {model['id']}: {model.get('total_tokens', 0)} tokens, ${model.get('cost', 0):.4f}"
                )

            # 2. A streamed run with a tool call: the RunCompleted event carries the metrics.
            response = client.post(
                f"/agents/{AGENT_ID}/runs",
                data={
                    "message": "Run `echo metrics` with Bash and reply with what it printed.",
                    "session_id": session_id,
                    "stream": "true",
                },
            )
            assert response.status_code == 200, response.text
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            completed = next(
                event
                for event in reversed(events)
                if event.get("event") == "RunCompleted"
            )
            streamed = completed["metrics"]
            print("Run 2 metrics (from the RunCompleted event):")
            print(
                f"  total_tokens={streamed['total_tokens']} cost=${streamed.get('cost', 0):.4f} ttft={streamed['time_to_first_token']:.2f}s"
            )

            # 3. Session totals, the sessions list and the daily aggregation.
            session = client.get(
                f"/sessions/{session_id}", params={"type": "agent"}
            ).json()
            totals = session["metrics"]
            print("Session metrics:")
            print(
                f"  total_tokens={totals['total_tokens']} cost=${totals.get('cost', 0):.4f}"
            )
            assert (
                totals["total_tokens"]
                == metrics["total_tokens"] + streamed["total_tokens"]
            )

            listing = client.get("/sessions", params={"type": "agent"}).json()
            rows = listing["data"] if isinstance(listing, dict) else listing
            row = next(item for item in rows if item["session_id"] == session_id)
            print(f"Sessions list: total_tokens={row['total_tokens']}")
            assert row["total_tokens"] == totals["total_tokens"]

            response = client.get("/metrics")
            assert response.status_code == 200, response.text
            body = response.json()
            days = body["metrics"] if isinstance(body, dict) else body
            today = days[-1] if days else {}
            print(
                f"Metrics page (today): agent_runs_count={today.get('agent_runs_count')} "
                f"total_tokens={(today.get('token_metrics') or {}).get('total_tokens')}"
            )
            assert today.get("agent_runs_count") == 2
    print("PASS: Claude run, session and OS metrics are visible through AgentOS")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        agent_os.serve(app="metrics_agentos:app", reload=False)
