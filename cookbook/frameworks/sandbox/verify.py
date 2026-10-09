"""Exercise the real two-replica Docker topology without model credentials.

Start compose.yaml first. This script restarts its API container and removes
only containers belonging to the sessions created by this test.
"""

import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

COMPOSE = Path(__file__).with_name("compose.yaml")
A = "http://127.0.0.1:18781"
B = "http://127.0.0.1:18782"


def wait_for(read, condition, timeout=120):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            last = read()
            if condition(last):
                return last
        except (httpx.HTTPError, KeyError):
            pass
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for expected state: " + str(last))


def get(path, base=B):
    response = httpx.get(base + path, timeout=5)
    response.raise_for_status()
    return response.json()


def submit(session, command, base=A):
    response = httpx.post(
        base + "/agents/coder/runs",
        data={
            "message": json.dumps(command),
            "session_id": session,
            "user_id": "sandbox-review",
            "background": "true",
            "stream": "false",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["run_id"]


def output(session, run_id):
    return get(f"/agents/coder/runs/{run_id}?session_id={session}")


def completed(session, run_id, expected="COMPLETED"):
    run = wait_for(
        lambda: output(session, run_id),
        lambda r: r["status"] in ("COMPLETED", "ERROR", "CANCELLED"),
    )
    assert run["status"] == expected, run
    return run


def binding(session):
    return get(f"/sessions/{session}/sandbox")


def remove_runtime(session):
    row = binding(session)
    name = (
        "agno-sandbox-"
        + row["sandbox_id"].replace("-", "")
        + "-"
        + str(row["generation"])
    )
    subprocess.run(
        ["docker", "rm", "--force", name], check=True, capture_output=True, timeout=30
    )
    return row


def main():
    wait_for(lambda: get("/health", A), lambda _: True)
    wait_for(lambda: get("/health", B), lambda _: True)
    session = str(uuid4())
    first = submit(session, {"write": "checkpoint-survives"})
    completed(session, first)
    initial = wait_for(
        lambda: binding(session),
        lambda row: row["active_run_id"] is None and row["workspace_checkpoint"],
    )
    print("PASS: first turn and pushed workspace checkpoint")

    # Disconnect the original streaming client, then restart its API replica
    # while the sandbox is actively executing the second turn.
    with httpx.stream(
        "POST",
        A + "/agents/coder/runs",
        data={
            "message": json.dumps({"delay": 8}),
            "session_id": session,
            "user_id": "sandbox-review",
            "stream": "true",
            "background": "true",
        },
        timeout=30,
    ) as response:
        response.raise_for_status()
        second = None
        for line in response.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event.get("event") == "RunStarted":
                    second = event["run_id"]
                    break
    assert second
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "restart", "api-a"],
        check=True,
        timeout=45,
    )
    result = completed(session, second)
    assert "checkpoint-survives" in result["content"]
    assert binding(session)["generation"] == initial["generation"]
    print("PASS: client disconnect and API restart during a live run")

    replay = httpx.post(
        B + f"/agents/coder/runs/{second}/resume",
        data={"session_id": session, "last_event_index": -1},
        timeout=20,
    )
    replay.raise_for_status()
    assert "checkpoint-survives" in replay.text
    print("PASS: event replay through the other replica")

    for streaming in (False, True):
        response = httpx.post(
            B + "/agents/coder/runs",
            data={
                "message": "{}",
                "session_id": session,
                "user_id": "sandbox-review",
                "background": "false",
                "stream": str(streaming).lower(),
            },
            timeout=60,
        )
        response.raise_for_status()
        assert "checkpoint-survives" in response.text
        if streaming:
            assert "RunCompleted" in response.text
        else:
            assert response.json()["status"] == "COMPLETED"
    print("PASS: foreground responses and streams execute through the sandbox")

    third = submit(session, {}, base=B)
    result = json.loads(completed(session, third)["content"])
    assert result["file"] == "checkpoint-survives" and result["history_count"] > 0
    print("PASS: third turn retains run history and workspace")

    busy = submit(session, {"delay": 8}, base=B)
    wait_for(lambda: output(session, busy), lambda row: row["status"] == "RUNNING")
    waiting = submit(session, {}, base=A)
    time.sleep(1)  # allow a dispatcher to claim the queued turn
    response = httpx.post(
        B + f"/agents/coder/runs/{waiting}/cancel",
        params={"session_id": session},
        timeout=10,
    )
    response.raise_for_status()
    completed(session, waiting, "CANCELLED")
    assert output(session, busy)["status"] == "RUNNING"
    completed(session, busy)
    print(
        "PASS: a claimed turn waiting for its busy session cancels without affecting the active turn"
    )

    cancel = submit(session, {"delay": 30}, base=B)
    wait_for(lambda: output(session, cancel), lambda row: row["status"] == "RUNNING")
    wait_for(lambda: get("/health", A), lambda _: True)
    response = httpx.post(
        A + f"/agents/coder/runs/{cancel}/cancel",
        params={"session_id": session},
        timeout=10,
    )
    response.raise_for_status()
    completed(session, cancel, "CANCELLED")
    print("PASS: cancellation from another replica")

    retry = submit(session, {"delay": 5}, base=B)
    wait_for(lambda: output(session, retry), lambda row: row["status"] == "RUNNING")
    old = remove_runtime(session)
    wait_for(
        lambda: binding(session),
        lambda row: row["generation"] > old["generation"] and row["status"] == "ready",
    )
    wait_for(lambda: output(session, retry), lambda row: row["status"] == "RUNNING")
    result = completed(session, retry)
    assert "checkpoint-survives" in result["content"]
    assert binding(session)["generation"] > old["generation"]
    print(
        "PASS: killed container is replaced and the second attempt restores the checkpoint"
    )

    # Kill both allowed attempts and demand an explicit terminal error.
    failed = submit(session, {"delay": 30}, base=B)
    wait_for(lambda: output(session, failed), lambda row: row["status"] == "RUNNING")
    old = remove_runtime(session)
    wait_for(
        lambda: binding(session),
        lambda row: row["generation"] > old["generation"] and row["status"] == "ready",
    )
    wait_for(lambda: output(session, failed), lambda row: row["status"] == "RUNNING")
    remove_runtime(session)
    error = completed(session, failed, "ERROR")
    assert "Sandbox" in str(error.get("content")) or "container" in str(
        error.get("content")
    )
    print("PASS: exhausted attempts end ERROR with a sandbox failure reason")

    idle_session = str(uuid4())
    run = submit(idle_session, {"write": "idle-checkpoint"}, base=B)
    completed(idle_session, run)
    wait_for(
        lambda: binding(idle_session),
        lambda row: row["status"] == "destroyed",
        timeout=90,
    )
    run = submit(idle_session, {}, base=B)
    assert "idle-checkpoint" in completed(idle_session, run)["content"]
    print("PASS: idle destruction and workspace restoration")
    wait_for(lambda: binding(idle_session), lambda row: row["active_run_id"] is None)
    response = httpx.delete(B + f"/sessions/{idle_session}", timeout=30)
    response.raise_for_status()
    assert binding(idle_session)["status"] == "destroyed"
    print("PASS: session deletion destroys its sandbox")


if __name__ == "__main__":
    main()
