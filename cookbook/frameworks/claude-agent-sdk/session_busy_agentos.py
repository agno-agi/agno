"""
One turn per session through AgentOS
====================================
A ClaudeAgent takes one turn per session at a time. While a turn is running, a second
request for the same session is answered with 409 and a session_busy error body, and
AgentOS keeps the client's keep-alive connection open, so a pooled HTTP client (an SDK,
a load balancer) is not torn down by a routine conflict.

The script serves an AgentOS in-process, starts a long turn in the background, then
sends further turns for the same session over a single raw HTTP connection: the ones
sent while the first turn runs get 409 on that same connection, and the one sent after
it finished gets 200.

Prerequisites: claude-agent-sdk and Claude authentication
Run: .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/session_busy_agentos.py
"""

import http.client
import json
import socket
import tempfile
import threading
import time
import urllib.parse

import uvicorn
from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

workdir = tempfile.mkdtemp(prefix="agno-session-busy-")
db = SqliteDb(db_file=f"{workdir}/runs.db")
agent = ClaudeAgent(
    id="claude",
    name="Claude",
    model="claude-sonnet-4-6",
    cwd=workdir,
    db=db,
    system_prompt=f"You work in {workdir}. One line answers.",
    allowed_tools=["Bash"],
    permission_mode="bypassPermissions",
    max_turns=4,
)
app = AgentOS(agents=[agent], db=db).get_app()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def post_run(conn: http.client.HTTPConnection, message: str, **fields: str) -> dict:
    """Send one run request on an existing connection and return the parsed response."""
    body = urllib.parse.urlencode(
        {"message": message, "session_id": "chat", "stream": "false", **fields}
    )
    conn.request(
        "POST",
        "/agents/claude/runs",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = conn.getresponse()
    payload = json.loads(response.read() or b"{}")
    return {
        "status": response.status,
        "keep_alive": not response.will_close,
        "body": payload,
    }


if __name__ == "__main__":
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    # 1. A long turn in the background: Claude runs a 10 second command.
    first = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    started = post_run(
        first,
        "Run `sleep 10; echo slow` with Bash and reply with what it printed.",
        background="true",
    )
    run_id = started["body"]["run_id"]
    print(f"first turn accepted: {started['status']} run {run_id[:8]}")
    time.sleep(2)

    # 2. Two more turns for the same session on one keep-alive connection while it runs.
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    for attempt in (1, 2):
        result = post_run(conn, "Reply with exactly the word SECOND.")
        body = result["body"]
        print(
            f"turn while busy, request {attempt} on the same connection: {result['status']} "
            f"error_id={body.get('error_id')} keep_alive={result['keep_alive']}"
        )
        assert (
            result["status"] == 409
            and body.get("error_id") == "session_busy"
            and result["keep_alive"]
        )

    # 3. Wait for the first turn, then the same connection serves a normal turn.
    for _ in range(60):
        conn.request("GET", f"/agents/claude/runs/{run_id}?session_id=chat")
        poll = json.loads(conn.getresponse().read())
        if poll.get("status") in ("COMPLETED", "ERROR", "CANCELLED"):
            break
        time.sleep(1)
    print(
        f"first turn finished: {poll.get('status')} {str(poll.get('content'))[:40]!r}"
    )
    result = post_run(conn, "Reply with exactly the word THIRD.")
    print(
        f"turn after it finished, same connection: {result['status']} {str(result['body'].get('content'))[:20]!r}"
    )
    assert result["status"] == 200
    server.should_exit = True
    print(
        "PASS: a busy session answers 409 without dropping the connection, and serves the next turn after"
    )
