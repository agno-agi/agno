"""
Trace HTTP Requests Through AgentOS
===================================

Trace the HTTP requests an AgentOS serves, not just its runs. A run started
over HTTP is stored nested inside its request span, and requests that start no
run (such as GET /sessions) become traces of their own. Requires FastAPI
0.142.0 or later.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/trace_requests.py
Try: Compare GET /traces?kind=run with GET /traces?kind=request and GET /traces/endpoints
"""

from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create Request-Traced AgentOS
# ---------------------------------------------------------------------------

AGENT_ID = "request-traced-agent"
DB_ID = "trace-requests-db"

db = SqliteDb(
    id=DB_ID,
    db_file="tmp/observability_trace_requests.db",
)

traced_agent = Agent(
    id=AGENT_ID,
    name="Request Traced Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Reply in one short sentence.",
)

agent_os = AgentOS(
    id="trace-requests-os",
    description="Trace runs and the HTTP requests around them.",
    db=db,
    agents=[traced_agent],
    tracing=True,
    trace_requests=True,
)
app = agent_os.get_app()


def print_span_tree(nodes: list[dict[str, Any]], depth: int = 0) -> None:
    """Print the recursive span tree returned by GET /traces/{trace_id}."""
    for node in nodes:
        print(f"{'  ' * depth}- {node['name']} [{node['type']}] ({node['duration']})")
        print_span_tree(node.get("spans") or [], depth + 1)


# ---------------------------------------------------------------------------
# Run Request Tracing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with TestClient(app) as client:
        run_response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": "Say hello",
                "stream": "false",
                "session_id": "trace-requests-session",
            },
        )
        run_response.raise_for_status()
        client.get("/sessions", params={"db_id": DB_ID}).raise_for_status()

        runs = client.get("/traces", params={"db_id": DB_ID, "kind": "run"}).json()
        requests = client.get(
            "/traces", params={"db_id": DB_ID, "kind": "request"}
        ).json()
        endpoints = client.get("/traces/endpoints", params={"db_id": DB_ID}).json()

        print("Run traces:")
        for trace in runs["data"]:
            request = trace.get("request") or {}
            print(
                f"- {trace['name']} via {request.get('method')} "
                f"{request.get('route')} ({request.get('status_code')})"
            )

        print("\nRequest traces without a run:")
        for trace in requests["data"]:
            print(f"- {trace['name']} ({trace['duration']})")

        print("\nEndpoints:")
        for endpoint in endpoints["data"]:
            print(f"- {endpoint['name']}: {endpoint['total_traces']} request(s)")

        run_trace_id = runs["data"][0]["trace_id"]
        detail = client.get(f"/traces/{run_trace_id}", params={"db_id": DB_ID}).json()
        print(f"\nRun trace tree (run span {detail['run_span_id']}):")
        print_span_tree(detail["tree"])
