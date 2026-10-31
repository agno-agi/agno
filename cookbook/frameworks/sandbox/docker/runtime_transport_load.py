"""Measure the runtime transports side by side under concurrent turns.

Each session's container runs one fixture turn (no model) that takes a few
seconds. The host streams every turn to completion three ways and reports what
each costs:

- exec, poll loop: the runtime spawned over docker exec for every request, the
  host sleeping between requests. The behaviour before long-poll existed.
- exec, long-poll: still a docker exec per request, but the container holds each
  poll until there is news, so far fewer requests.
- http, long-poll: the container serves the runtime over HTTP on a port published
  on the host's loopback; requests are pooled connections and the Docker daemon
  is only used for lifecycle.

    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    AGNO_SANDBOX_LOAD_SESSIONS=8 .venv/bin/python cookbook/frameworks/sandbox/docker/runtime_transport_load.py

Requests per turn and daemon calls per turn are what grow with concurrent users;
the idle poll latency is the cost of one control request when nothing is pending.
"""

import asyncio
import os
import statistics
import time
from uuid import uuid4

from agno.sandbox.client import RuntimeExecution, SandboxRuntimeClient
from agno.sandbox.docker import DockerSandbox

IMAGE = os.environ.get("AGNO_SANDBOX_IMAGE", "agno-sandbox:local")
SESSIONS = int(os.environ.get("AGNO_SANDBOX_LOAD_SESSIONS", "8"))
TURN_SECONDS = float(os.environ.get("AGNO_SANDBOX_LOAD_TURN_SECONDS", "3"))


class Meter:
    """Counts runtime requests and Docker daemon calls a provider makes, and times the requests."""

    def __init__(self, provider: DockerSandbox) -> None:
        self.requests: list = []
        self.daemon_calls = 0
        rpc, docker = provider.arpc, provider._docker

        async def timed(handle, operation, payload):
            started = time.perf_counter()
            try:
                return await rpc(handle, operation, payload)
            finally:
                self.requests.append(time.perf_counter() - started)

        async def counted(*args, **kwargs):
            self.daemon_calls += 1
            return await docker(*args, **kwargs)

        provider.arpc = timed  # type: ignore[method-assign]
        provider._docker = counted  # type: ignore[method-assign]


async def run_turn(
    client: SandboxRuntimeClient, handle, index: int, wait: float
) -> float:
    started = time.perf_counter()
    execution = await client.astart(
        handle,
        execution_id=f"load-{index}",
        run_id=f"run-{index}",
        sdk="fixture",
        input="ping",
        config={"delay": TURN_SECONDS},
    )
    result = await client.await_result(execution, timeout=120, wait=wait)
    assert (
        result["type"] == "execution_finished" and result["run"]["content"] == "ping"
    ), result
    return time.perf_counter() - started


async def measure(label: str, runtime_port, wait: float) -> None:
    provider = DockerSandbox(
        IMAGE,
        namespace="load-" + uuid4().hex[:8],
        network="isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        memory_mb=256,
        runtime_port=runtime_port,
    )
    client = SandboxRuntimeClient(provider)
    env = {"AGNO_SANDBOX_TEST_RUNTIME": "1"}
    handles = await asyncio.gather(
        *(
            provider.acreate(f"session-{i}", agent_id="coder", env=env)
            for i in range(SESSIONS)
        )
    )
    meter = Meter(provider)
    try:
        started = time.perf_counter()
        turns = await asyncio.gather(
            *(run_turn(client, handle, i, wait) for i, handle in enumerate(handles))
        )
        wall = time.perf_counter() - started
        requests, daemon_calls = len(meter.requests), meter.daemon_calls
        # One control request with nothing pending: the per-request overhead of the transport.
        probe = []
        for index, handle in enumerate(handles):
            done = RuntimeExecution(handle, f"load-{index}", f"run-{index}")
            for _ in range(5):
                began = time.perf_counter()
                await client.apoll(done, wait=0)
                probe.append(time.perf_counter() - began)
    finally:
        await asyncio.gather(*(provider.adestroy(handle) for handle in handles))
    print(
        f"{label:<16} wall={wall:5.2f}s  turn mean={statistics.mean(turns):5.2f}s  "
        f"requests/turn={requests / SESSIONS:5.1f}  daemon calls/turn={daemon_calls / SESSIONS:5.1f}  "
        f"idle poll p50={statistics.median(probe) * 1000:6.1f}ms  max={max(probe) * 1000:6.1f}ms"
    )


async def main() -> None:
    print(
        f"image={IMAGE} sessions={SESSIONS} fixture turn={TURN_SECONDS:.0f}s, no model calls"
    )
    await measure("exec, poll loop", None, wait=0)
    await measure("exec, long-poll", None, wait=10)
    await measure("http, long-poll", 8765, wait=10)


if __name__ == "__main__":
    asyncio.run(main())
