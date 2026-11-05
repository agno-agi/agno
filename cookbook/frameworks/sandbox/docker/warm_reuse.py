"""Pause a session's container between turns and resume it with nothing to restore.

Shows the warm path next to the cold one, without model credentials:

1. Run a turn's worth of work: write a file and leave a background process running.
2. Pause the container. Files, memory and processes freeze in place; commands are refused.
3. The next turn resumes it. ``create`` refuses a paused generation, because only the
   caller that paused it knows its files are whole; ``resume`` brings it back with the
   file there and the background process carrying on from where it stopped.
4. Stop the container. That is the cold path: the files are gone and the generation
   cannot restart, so recovery needs a new generation restored from a checkpoint.
"""

import os
import time
from uuid import uuid4

from agno.sandbox import SandboxError
from agno.sandbox.docker import DockerSandbox

sandbox = DockerSandbox(
    image=os.environ.get("AGNO_SANDBOX_IMAGE", "python:3.12-slim"),
    namespace="warm-reuse-" + uuid4().hex,
    memory_mb=256,
)
identity = {"session_id": "example", "agent_id": "coder"}
handle = sandbox.create(**identity)
try:
    # Turn 1: leave state behind, on disk and as a live process.
    sandbox.exec(handle, ["sh", "-c", "echo 'written in turn 1' > notes.txt"])
    counter = "import time\nfor i in range(10**6):\n    open('ticks', 'w').write(str(i))\n    time.sleep(0.1)\n"
    sandbox.exec(
        handle, ["sh", "-c", 'nohup python -c "$0" >/dev/null 2>&1 &', counter]
    )
    time.sleep(0.5)
    before = int(sandbox.exec(handle, ["cat", "ticks"]).stdout or 0)
    print(f"Turn 1 done: notes.txt written, background counter at {before}")

    # Between turns: pause. Nothing is copied anywhere.
    sandbox.pause(handle)
    print("Paused:", sandbox.get(handle.provider_ref).state)
    try:
        sandbox.exec(handle, ["cat", "notes.txt"])
    except SandboxError as error:
        print("Command while paused refused:", error)
    time.sleep(1.0)

    # Turn 2: create will not guess why the generation is paused; the owner resumes it.
    try:
        sandbox.create(**identity)
    except SandboxError as error:
        print("Create while paused refused:", error)
    resumed = sandbox.resume(handle)
    assert resumed.provider_ref == handle.provider_ref and resumed.state == "running"
    print("Resumed the same container:", resumed.name)
    print("notes.txt:", sandbox.exec(resumed, ["cat", "notes.txt"]).stdout.strip())
    after = int(sandbox.exec(resumed, ["cat", "ticks"]).stdout)
    print(f"Background counter continued: {before} -> {after}")
    assert after >= before, "the frozen process must resume, not restart"

    # The cold path for comparison: stop loses the tmpfs and the generation.
    sandbox.stop(handle)
    print("Stopped:", sandbox.get(handle.provider_ref).state)
    try:
        sandbox.create(**identity)
    except SandboxError as error:
        print("Create after stop refused:", error)
    fresh = sandbox.create(**identity, generation=2)
    missing = sandbox.exec(fresh, ["cat", "notes.txt"])
    print(
        f"Generation 2 starts empty: exit {missing.exit_code}, restore a checkpoint to continue"
    )
    sandbox.destroy(fresh)
finally:
    sandbox.destroy(handle)
