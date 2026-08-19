"""
Run a served Workflow over HTTP
===============================

Call basic.py through raw HTTP: create a non-streaming run, consume an SSE
event stream, and list the persisted runs for the shared workflow session.

Prerequisites: basic.py running on http://localhost:7777
Run: .venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/run_over_api.py
Try: Compare these calls with the workflow routes at http://localhost:7777/docs
"""

import json
import os
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Create Workflow API Helpers
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://localhost:7777")
WORKFLOW_ID = "release-notes-workflow"
SESSION_ID = "workflow-http-session"


def create_run(client: httpx.Client) -> dict[str, Any]:
    """Create one complete, non-streaming workflow run."""
    response = client.post(
        f"/workflows/{WORKFLOW_ID}/runs",
        data={
            "message": "Document a faster AgentOS startup and clearer health checks.",
            "stream": "false",
            "session_id": SESSION_ID,
        },
    )
    response.raise_for_status()
    result = response.json()
    if result["status"] != "COMPLETED":
        raise RuntimeError(f"Non-streaming run ended with {result['status']}")
    return result


def stream_run(client: httpx.Client) -> tuple[str, list[str]]:
    """Create a workflow run and consume its server-sent events."""
    event_types: list[str] = []
    run_id: str | None = None

    with client.stream(
        "POST",
        f"/workflows/{WORKFLOW_ID}/runs",
        data={
            "message": "Document a safer deployment check and concise failure output.",
            "stream": "true",
            "session_id": SESSION_ID,
        },
    ) as response:
        response.raise_for_status()
        if "text/event-stream" not in response.headers.get("content-type", ""):
            raise RuntimeError("Expected a text/event-stream response")

        event_name = "message"
        for line in response.iter_lines():
            if line.startswith("event: "):
                event_name = line[7:]
                continue
            if not line.startswith("data: "):
                continue

            payload = json.loads(line[6:])
            event_types.append(event_name)
            run_id = run_id or payload.get("run_id")

            if event_name == "WorkflowCompleted":
                break
            if event_name in {"WorkflowCancelled", "WorkflowError"}:
                raise RuntimeError(f"Stream ended with {event_name}: {payload}")

    if not run_id:
        raise RuntimeError("The workflow stream did not include a run_id")
    if "WorkflowCompleted" not in event_types:
        raise RuntimeError("The workflow stream did not complete")
    return run_id, event_types


def list_runs(client: httpx.Client) -> list[dict[str, Any]]:
    """List persisted runs for the workflow session."""
    response = client.get(
        f"/workflows/{WORKFLOW_ID}/runs",
        params={"session_id": SESSION_ID},
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Run Workflow API Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as http_client:
        health_response = http_client.get("/health")
        health_response.raise_for_status()

        config_response = http_client.get("/config")
        config_response.raise_for_status()
        workflow_ids = {
            workflow["id"] for workflow in config_response.json()["workflows"]
        }
        if WORKFLOW_ID not in workflow_ids:
            raise RuntimeError(f"Workflow {WORKFLOW_ID} was not discovered")

        completed_run = create_run(http_client)
        streamed_run_id, streamed_events = stream_run(http_client)
        stored_runs = list_runs(http_client)

    stored_run_ids = {run["run_id"] for run in stored_runs}
    expected_run_ids = {completed_run["run_id"], streamed_run_id}
    if not expected_run_ids.issubset(stored_run_ids):
        raise RuntimeError("Run listing did not include both new workflow runs")

    print(f"Health: {health_response.json()['status']}")
    print(f"Non-streaming run: {completed_run['run_id']}")
    print(f"Non-streaming result: {completed_run['content']}")
    print(f"Streamed run: {streamed_run_id}")
    print(f"Stream event count: {len(streamed_events)}")
    print(f"Stream event types: {list(dict.fromkeys(streamed_events))}")
    print(f"Stored runs in session: {len(stored_runs)}")
