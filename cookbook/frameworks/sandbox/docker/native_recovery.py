"""Cold replacement, a restore that does not land, and the recovery loop, with a real Claude session.

A Claude turn continues its own native session from files under /runtime/native: the transcript
and the local history database that maps the Agno session to it. When a container is replaced,
those files come back from a checkpoint. This example walks the whole path on one session:

1. Turn 1 runs on generation 1. The session is checkpointed and the container destroyed.
2. Generation 2 is restored from the checkpoint. Turn 2 passes the committed native id as its
   expectation and Claude recalls the conversation: the cold path working.
3. Generation 3 is created but the restore is skipped, standing in for a restore that did not
   land. Turn 3 runs without an expectation: the runtime sees a new session, Claude starts a
   fresh conversation with no memory, and the turn reports COMPLETED. That is the old outcome,
   and the one a coordinator must never checkpoint.
4. Generation 4, restore skipped again. Turn 4 passes the committed id and is refused before the
   model runs, with reason native_state_missing. That is the new outcome.
5. The coordinator's reaction: destroy that generation, restore the same checkpoint into
   generation 5, start again with the same expectation. Claude recalls the conversation.

Build the image first, then export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN:

    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    .venv/bin/python cookbook/frameworks/sandbox/docker/native_recovery.py
"""

import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.client import SandboxRuntimeClient
from agno.sandbox.docker import DockerCheckpointTransfer, DockerSandbox

credentials = {
    key: os.environ[key]
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
    if key in os.environ
}
if not credentials:
    raise SystemExit(
        "Export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN for the container"
    )

started = time.monotonic()
outcomes = []


def say(line: str) -> None:
    print(f"[{time.monotonic() - started:5.1f}s] {line}")


def section(title: str) -> None:
    print()
    print("=== " + title)


config = {
    "model": "claude-sonnet-4-6",
    "permission_mode": "bypassPermissions",
    "allowed_tools": [],
    "max_turns": 2,
}
sandbox = DockerSandbox(
    image=os.environ.get("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
    namespace="native-recovery-" + uuid4().hex,
    network="isolated",
    # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
    subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
    memory_mb=1024,
)
client = SandboxRuntimeClient(sandbox)
identity = {"session_id": "example", "agent_id": "coder", "env": credentials}
RECALL = "What word did I ask you to remember? Reply with that word only, or NONE if you do not know."


def turn(computer, number: int, prompt: str, native_session_id=None, label: str = ""):
    execution = client.start(
        computer,
        execution_id=f"turn-{number}",
        run_id=f"run-{number}",
        sdk="claude",
        input=prompt,
        config=config,
        native_session_id=native_session_id,
    )
    result = client.wait_result(execution, timeout=240)
    if result["type"] == "execution_finished":
        native = (result["session"].get("session_data") or {}).get(
            "claude_sdk_session_id"
        )
        outcome = f"{result['run']['status']}, answer {result['run'].get('content')!r}, native {str(native)[:8]}"
        say(f"turn {number}: {outcome}")
        outcomes.append((label, outcome))
        return native
    outcome = f"{result['type']}, reason {result.get('reason')}"
    say(f"turn {number}: {outcome}: {result['error'][:100]}")
    outcomes.append((label, outcome))
    return None


handles = []
try:
    with TemporaryDirectory(prefix="agno-native-recovery-") as directory:
        transfer = DockerCheckpointTransfer(
            sandbox, FileCheckpointStore(Path(directory) / "objects")
        )

        section("1. Turn 1 on generation 1, then checkpoint and destroy")
        handles.append(sandbox.create(**identity, generation=1))
        committed = turn(
            handles[0],
            1,
            "Remember the word pineapple. Reply with exactly OK.",
            label="turn 1",
        )
        reference = transfer.capture(
            handles[0], state={"claude_sdk_session_id": committed}
        )
        say(
            f"checkpoint {reference.sha256[:12]}, {reference.size} bytes; native id {committed[:8]} is what the caller commits"
        )
        sandbox.destroy(handles[0])
        say("generation 1 destroyed; the checkpoint is the only copy")

        section("2. Generation 2 restored from the checkpoint: the cold path")
        handles.append(sandbox.create(**identity, generation=2))
        state = transfer.restore(handles[1], reference)
        say(
            "restored, manifest carries native id " + state["claude_sdk_session_id"][:8]
        )
        turn(
            handles[1],
            2,
            RECALL,
            native_session_id=committed,
            label="restore landed, expectation set",
        )
        sandbox.destroy(handles[1])

        section("3. Generation 3, restore skipped, no expectation: the old outcome")
        handles.append(sandbox.create(**identity, generation=3))
        say("standing in for a restore that did not land: the roots are empty")
        turn(handles[2], 3, RECALL, label="restore missing, no expectation")
        say(
            "a new native session with no memory, reported COMPLETED: a fork the coordinator cannot detect"
        )
        sandbox.destroy(handles[2])

        section("4. Generation 4, restore skipped, expectation set: the new outcome")
        handles.append(sandbox.create(**identity, generation=4))
        turn(
            handles[3],
            4,
            RECALL,
            native_session_id=committed,
            label="restore missing, expectation set",
        )
        say("refused before the model ran; the caller treats this as a failed restore")

        section(
            "5. The coordinator's reaction: replace the generation and restore again"
        )
        sandbox.destroy(handles[3])
        handles.append(sandbox.create(**identity, generation=5))
        transfer.restore(handles[4], reference)
        turn(
            handles[4],
            5,
            RECALL,
            native_session_id=committed,
            label="restore retried, expectation set",
        )
        say("the session is whole again and nothing forked was ever committed")
finally:
    for handle in handles:
        sandbox.destroy(handle)

print()
print("Summary")
for label, outcome in outcomes:
    print(f"  {label:40s} {outcome}")
