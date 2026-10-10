"""
CodexAgent metrics on AgentOS
=============================
Serve a CodexAgent through AgentOS and read its metrics the way the UI does:
tokens on each run, totals on the session, the token column in the sessions
list, and the daily aggregation on the metrics page. Codex reports no cost.

Run normally to serve AgentOS; pass --verify to drive two runs through the
HTTP API and print what each endpoint reports.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_metrics_agentos.py
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_metrics_agentos.py --verify

Then open the AgentOS UI, chat with the agent, and check the session's metrics
and the Metrics page. Or with curl:
    curl -X POST http://localhost:7777/agents/codex-metrics/runs \
        -F "message=Reply with exactly OK." -F "session_id=demo" -F "stream=false" | jq .metrics
    curl "http://localhost:7777/sessions/demo?type=agent" | jq .metrics
    curl "http://localhost:7777/metrics" | jq
"""

import json
import sys
import tempfile

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

AGENT_ID = "codex-metrics"

db = SqliteDb(db_file="tmp/codex-metrics.db")
agent = CodexAgent(
    id=AGENT_ID,
    name="Codex Metrics",
    model="gpt-5.6-luna",
    sandbox="read-only",
    db=db,
)
agent_os = AgentOS(agents=[agent], db=db)
app = agent_os.get_app()


def verify():
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(prefix="agno-codex-metrics-") as workdir:
        agent.db = SqliteDb(db_file=f"{workdir}/runs.db")
        agent.cwd = workdir
        session_id = "codex-metrics-agentos"
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
            metrics = response.json()["metrics"]
            print("Run 1 metrics:")
            print(
                f"  input={metrics['input_tokens']} cached={metrics.get('cache_read_tokens', 0)} "
                f"output={metrics['output_tokens']} total={metrics['total_tokens']} duration={metrics['duration']:.2f}s"
            )

            # 2. A streamed run: the RunCompleted event carries the metrics.
            response = client.post(
                f"/agents/{AGENT_ID}/runs",
                data={
                    "message": "What is 17 times 3? Reply with just the number.",
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
                f"  total={streamed['total_tokens']} ttft={streamed['time_to_first_token']:.2f}s"
            )

            # 3. Session totals, the sessions list and the daily aggregation.
            session = client.get(
                f"/sessions/{session_id}", params={"type": "agent"}
            ).json()
            totals = session["metrics"]
            print(f"Session metrics: total_tokens={totals['total_tokens']}")
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
    print("PASS: Codex run, session and OS metrics are visible through AgentOS")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        agent_os.serve(app="codex_metrics_agentos:app", reload=False)
