"""Show what the runtime server's failure and trust boundaries look like, without model credentials.

Three things happen, each in its own section of the output:

1. A turn runs and reports the environment variables its process can see. The control token the
   host uses to talk to the server is not among them: the server takes it out of its own
   environment and workers are spawned without it.
2. A streaming turn is in flight and the runtime server is killed with SIGKILL partway through.
   The events keep being journaled, because workers are detached from the server; the host's
   polls fail for a moment, the supervisor that is the container's main process restarts the
   server, and the host picks up from its cursor without missing or repeating an event.
3. A control request on the exec transport that cannot be answered in time raises but leaves the
   container running. Control requests never stop compute; only arbitrary exec does.
"""

import os
import time
from uuid import uuid4

import httpx
from agno.sandbox.base import SandboxError
from agno.sandbox.client import SandboxRuntimeClient
from agno.sandbox.docker import DockerSandbox

IMAGE = os.environ.get("AGNO_SANDBOX_IMAGE", "agno-sandbox:local")
FIXTURE_ENV = {"AGNO_SANDBOX_TEST_RUNTIME": "1"}

# Finds the runtime server process inside the container and kills it outright.
KILL_SERVER = """
import os, signal
for pid in os.listdir("/proc"):
    if not pid.isdigit() or int(pid) == os.getpid():
        continue
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\\0", b" ")
    except OSError:
        continue
    if b"agno.sandbox.runtime serve" in cmd:
        os.kill(int(pid), signal.SIGKILL)
        print(pid)
"""

started = time.monotonic()


def say(line: str) -> None:
    print(f"[{time.monotonic() - started:6.2f}s] {line}")


def section(title: str) -> None:
    print()
    print("=== " + title)


def stream(client: SandboxRuntimeClient, execution, *, kill_after=None, sandbox=None):
    """Poll a turn to completion, printing each event as it arrives.

    Polls go straight to the container's server with the current cursor. A poll that fails is
    printed and retried from the same cursor, which is how a host reconnects after any gap.
    """
    cursor, seen, killed = 0, 0, False
    while True:
        try:
            page = client.poll(execution, cursor=cursor, wait=5)
        except SandboxError as error:
            say(
                "poll failed, retrying from cursor "
                + str(cursor)
                + ": "
                + str(error).split("\n")[0][:90]
            )
            time.sleep(0.1)
            continue
        for event in page.events:
            seen += 1
            say(
                "event "
                + str(seen)
                + " at cursor "
                + str(cursor)
                + ": "
                + event["content"]
            )
        cursor = page.cursor
        if page.result is not None:
            say(
                "result: status "
                + page.result["run"]["status"]
                + ", content "
                + repr(page.result["run"]["content"])
            )
            return seen
        if kill_after is not None and seen >= kill_after and not killed:
            killed = True
            pid = sandbox.exec(
                execution.computer, ["python", "-c", KILL_SERVER]
            ).stdout.strip()
            say(
                "killed the runtime server (pid "
                + pid
                + ") with SIGKILL while the turn is running"
            )


served = DockerSandbox(
    image=IMAGE,
    namespace="resilience-" + uuid4().hex,
    network="isolated",
    # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
    subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
    memory_mb=512,
    runtime_port=8765,
)
section("1. The turn never sees the control token")
computer = served.create(session_id="example", agent_id="coder", env=FIXTURE_ENV)
say("created " + computer.provider_ref[:12] + " serving at " + computer.runtime_url)
client = SandboxRuntimeClient(served)
try:
    execution = client.start(
        computer, execution_id="env", run_id="run-env", sdk="fixture", input="hello"
    )
    stream(client, execution)
    # The fixture wrote the names of every AGNO_SANDBOX* variable in the turn's environment.
    seen = served.exec(computer, ["cat", "fixture-env.txt"]).stdout.split()
    assert "AGNO_SANDBOX_TEST_RUNTIME" in seen, (
        "the fixture reports the variables it can see"
    )
    assert "AGNO_SANDBOX_RUNTIME_TOKEN" not in seen, (
        "the control token is not one of them"
    )
    say(
        "the turn's environment had: "
        + ", ".join(seen)
        + " (the fixture switch this example passes in)"
    )
    say("the turn's environment did not have: AGNO_SANDBOX_RUNTIME_TOKEN")
    say(
        "the token lives in the server's memory; the host reads it from Docker and sends it as a bearer header"
    )

    section(
        "2. Server killed mid-turn: events keep flowing, the supervisor heals the server"
    )
    execution = client.start(
        computer,
        execution_id="crash",
        run_id="run-crash",
        sdk="fixture",
        input="still here",
        config={"delay": 4.0, "steps": 8},
    )
    say("started a turn that streams 8 events over 4 s")
    down_at = time.monotonic()
    events = stream(client, execution, kill_after=2, sandbox=served)
    assert events == 8, "every event arrived exactly once across the server restart"
    headers = {"Authorization": "Bearer " + computer.runtime_token}
    assert (
        httpx.get(
            computer.runtime_url + "/health", headers=headers, timeout=2
        ).status_code
        == 200
    )
    effects = served.exec(computer, ["cat", "fixture-effects.txt"]).stdout
    assert effects == "run-env\nrun-crash\n", "each run executed exactly once"
    say("server healthy again; effects file lists each run once, so nothing was re-run")
finally:
    served.destroy(computer)
    say("destroyed the served sandbox")

section("3. Exec transport: a lost control reply leaves the container running")
plain = DockerSandbox(
    image=IMAGE, namespace="resilience-exec-" + uuid4().hex, memory_mb=512
)
computer = plain.create(session_id="example", agent_id="coder", env=FIXTURE_ENV)
say(
    "created "
    + computer.provider_ref[:12]
    + " with no runtime port; rpc goes over docker exec"
)
try:
    client = SandboxRuntimeClient(plain)
    execution = client.start(
        computer,
        execution_id="slow",
        run_id="run-slow",
        sdk="fixture",
        input="done",
        config={"delay": 2.0},
    )
    # The provider gives a control request 15 s plus its wait; shrink that to force a timeout.
    original = plain._aexec

    async def impatient(handle, argv, **kwargs):
        kwargs["timeout"] = 0.01
        return await original(handle, argv, **kwargs)

    plain._aexec = impatient  # type: ignore[method-assign]
    try:
        client.poll(execution, cursor=0, wait=5)
    except SandboxError:
        say("poll timed out on the exec transport, as forced")
    plain._aexec = original  # type: ignore[method-assign]
    state = plain.get(computer.provider_ref).state
    say("container state after the failed control request: " + state)
    assert state == "running", "a lost control reply never stops compute"
    stream(client, execution)
    say(
        "the same turn still finished; an arbitrary exec would have stopped the container instead"
    )
finally:
    plain.destroy(computer)
    say("destroyed the exec sandbox")
