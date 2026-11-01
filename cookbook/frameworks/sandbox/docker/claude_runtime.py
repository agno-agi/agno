"""Run two Claude turns on one session inside a sandbox container, with a pause in between.

The whole path on this branch, with a live model:

1. Create the session's container from the runtime image with only the model
   credential in its environment. No database or queue credentials enter compute.
2. Start turn 1 through the runtime journal, stream its events from the poll cursor,
   and read the execution result. Claude Code runs inside the container, edits the
   workspace there, and keeps its native session under /runtime/native.
3. Pause the container between turns. Nothing is copied anywhere.
4. Resume it and run turn 2 on the same session. Claude remembers turn 1 because
   its transcript and the local history database are still on the container's disk.

Build the image first, then export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN:

    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    .venv/bin/python cookbook/frameworks/sandbox/docker/claude_runtime.py

A runtime result is execution output, not durable completion: the coordinator
layer that checkpoints and commits it to the service database is a later PR.
"""

import os
from uuid import uuid4

from agno.sandbox.client import SandboxRuntimeClient
from agno.sandbox.docker import DockerSandbox

credentials = {
    key: os.environ[key]
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
    if key in os.environ
}
if not credentials:
    raise SystemExit(
        "Export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN for the container"
    )

sandbox = DockerSandbox(
    image=os.environ.get("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
    namespace="claude-runtime-" + uuid4().hex,
    network="isolated",
    # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
    subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
    memory_mb=1024,
    # The container serves the runtime over HTTP on a loopback-published port, so start and
    # poll are pooled requests instead of a docker exec each.
    runtime_port=8765,
)
identity = {"session_id": "example", "agent_id": "coder", "env": credentials}
runtime_config = {
    "model": "claude-sonnet-4-6",
    "permission_mode": "bypassPermissions",
    "allowed_tools": ["Read", "Write", "Bash"],
    "setting_sources": [],
    "max_turns": 12,
}
client = SandboxRuntimeClient(sandbox)


def run_turn(computer, number: int, prompt: str) -> dict:
    execution = client.start(
        computer,
        execution_id=f"turn-{number}",
        run_id=f"run-{number}",
        sdk="claude",
        input=prompt,
        config=runtime_config,
        execution_timeout=600,
    )
    result = None
    for page in client.pages(execution, timeout=600, poll_interval=0.5):
        for event in page.events:
            if event.get("event") == "ToolCallStarted":
                print(f"  tool: {event.get('tool', {}).get('tool_name')}")
            elif event.get("event") == "RunContent" and event.get("content"):
                print("  content:", str(event["content"]).strip()[:120])
        result = page.result
    assert result is not None and result["type"] == "execution_finished", result
    run = result["run"]
    print(
        f"Turn {number} finished: status={run['status']} content={str(run.get('content')).strip()[:200]!r}"
    )
    return result


computer = sandbox.create(**identity)
try:
    print("Container:", computer.name)
    first = run_turn(
        computer,
        1,
        "Create hello.py in the workspace that prints the word hello, run it with python, "
        "and reply with only the program's output.",
    )
    assert first["run"]["status"] == "COMPLETED"
    print(
        "Workspace after turn 1:",
        sandbox.exec(computer, ["ls", "/workspace"]).stdout.split(),
    )
    print(
        "Native state kept in the container:",
        sandbox.exec(computer, ["ls", "-a", "/runtime/native"]).stdout.split(),
    )
    native_session = first["session"]["session_data"].get("claude_sdk_session_id")
    print("Claude session id recorded locally:", native_session)

    # Between turns: pause, then resume explicitly. Create refuses a paused generation.
    sandbox.pause(computer)
    print("Paused:", sandbox.get(computer.provider_ref).state)
    resumed = sandbox.resume(computer)
    assert resumed.provider_ref == computer.provider_ref
    print(
        "Resumed the same container: files and native session still in place, no checkpoint restore needed"
    )

    second = run_turn(
        resumed,
        2,
        "Without using any tools: which file did you create in the previous turn, and what did it print? "
        "Answer in one short sentence.",
    )
    assert second["run"]["status"] == "COMPLETED"
    assert (
        second["session"]["session_data"].get("claude_sdk_session_id") == native_session
    ), "turn 2 must resume the same native Claude session"
    print("Turn 2 resumed native session", native_session)
finally:
    sandbox.destroy(computer)
