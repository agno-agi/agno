"""Opt-in real Claude test: two runs capped at $2 each by the harness SDK.

Use compose.live.yaml in addition to compose.yaml. This invokes Claude, writes a
file in its sandbox, destroys that sandbox and verifies recall on a fresh one.
"""

import json
from uuid import uuid4

import httpx
from verify import A, B, binding, completed, get, wait_for


def submit(session, message, base):
    response = httpx.post(
        base + "/agents/coder/runs",
        data={
            "message": message,
            "session_id": session,
            "user_id": "live-review",
            "background": "true",
            "stream": "false",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["run_id"]


def main():
    wait_for(lambda: get("/health", A), lambda _: True)
    wait_for(lambda: get("/health", B), lambda _: True)
    session = str(uuid4())
    memory = "orchid-" + uuid4().hex[:12]
    workspace = "workspace-" + uuid4().hex[:12]
    first = submit(
        session,
        f"Remember our secret phrase {memory} only in this conversation, never in a file. "
        f"Use Write to create /workspace/acceptance.txt containing exactly {workspace}. "
        "Then reply briefly confirming the file was written.",
        A,
    )
    initial_output = completed(session, first)
    initial = wait_for(
        lambda: binding(session),
        lambda row: row["active_run_id"] is None and row["workspace_checkpoint"],
    )
    response = httpx.delete(B + "/sandboxes/" + initial["sandbox_id"], timeout=30)
    response.raise_for_status()
    second = submit(
        session,
        "What secret phrase did I give you? Read /workspace/acceptance.txt. "
        "Reply with the exact secret phrase and the exact file contents.",
        B,
    )
    result = completed(session, second)
    assert memory in result["content"] and workspace in result["content"], result[
        "content"
    ]
    assert binding(session)["generation"] > initial["generation"]
    print(
        "PASS: real Claude conversation and Git workspace survive container destruction"
    )
    print(
        json.dumps(
            {
                "session_id": session,
                "first_run": first,
                "second_run": second,
                "first_metrics": initial_output.get("metrics"),
                "second_metrics": result.get("metrics"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
