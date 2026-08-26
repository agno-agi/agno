"""
Run an Agent over HTTP
======================

Call the server from full_os.py through its raw FastAPI surface. This example
discovers the OS, runs one non-streaming request, consumes one SSE stream, and
then lists the resulting persisted session.

Prerequisites: full_os.py running on http://localhost:7777
Run: .venvs/demo/bin/python cookbook/05_agent_os/01_getting_started/run_over_http.py
Try: Compare the discovered components with http://localhost:7777/config
"""

import json

import httpx

# ---------------------------------------------------------------------------
# Create HTTP Request Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "getting-started-agent"
SESSION_ID = "getting-started-http-session"
USER_ID = "getting-started-user"


def show_config(client: httpx.Client) -> None:
    """Print the components discovered through GET /config."""
    response = client.get("/config")
    response.raise_for_status()
    config = response.json()

    print(f"AgentOS: {config['os_id']}")
    print(f"Agents: {[agent['id'] for agent in config['agents']]}")
    print(f"Teams: {[team['id'] for team in config['teams']]}")
    print(f"Workflows: {[workflow['id'] for workflow in config['workflows']]}")


def run_non_streaming(client: httpx.Client) -> None:
    """Run the agent with an application/x-www-form-urlencoded request."""
    response = client.post(
        f"/agents/{AGENT_ID}/runs",
        data={
            "message": "What does this AgentOS expose? Answer in one sentence.",
            "stream": "false",
            "session_id": SESSION_ID,
            "user_id": USER_ID,
        },
    )
    response.raise_for_status()
    result = response.json()

    print(f"Run ID: {result['run_id']}")
    print(f"Session ID: {result['session_id']}")
    print(f"Response: {result['content']}")


def run_streaming(client: httpx.Client) -> None:
    """Run the agent with SSE streaming enabled."""
    with client.stream(
        "POST",
        f"/agents/{AGENT_ID}/runs",
        data={
            "message": "Give me a short streamed welcome to AgentOS.",
            "stream": "true",
            "session_id": SESSION_ID,
            "user_id": USER_ID,
        },
    ) as response:
        response.raise_for_status()
        if "text/event-stream" not in response.headers.get("content-type", ""):
            raise RuntimeError("Expected an SSE response")

        event_name = "message"
        for line in response.iter_lines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
                if event_name == "RunContent" and payload.get("content"):
                    print(payload["content"], end="", flush=True)
                elif event_name == "RunCompleted":
                    print(f"\nCompleted run: {payload['run_id']}")


def show_sessions(client: httpx.Client) -> None:
    """List the paginated sessions created by the two runs."""
    response = client.get(
        "/sessions",
        params={
            "type": "agent",
            "component_id": AGENT_ID,
            "user_id": USER_ID,
        },
    )
    response.raise_for_status()
    payload = response.json()

    print(f"Sessions found: {payload['meta']['total_count']}")
    for session in payload["data"]:
        print(f"- {session['session_id']}")


# ---------------------------------------------------------------------------
# Run HTTP Walkthrough
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as http_client:
        show_config(http_client)
        print("\nNon-streaming run")
        run_non_streaming(http_client)
        print("\nStreaming run")
        run_streaming(http_client)
        print("\nStored sessions")
        show_sessions(http_client)
