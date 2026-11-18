"""Load test E2B sandboxes with concurrent sessions. This creates billable compute.

Each session gets its own E2B computer and runs fixture turns (no model) that take
a few seconds. All sessions run at once through each phase, and the script reports
what each phase costs:

- create: boot, setuid hardening and runtime server start, per computer.
- turns, three ways on the same computers:
  - exec, poll loop: an E2B command per request, the host sleeping between requests.
  - exec, long-poll: still a command per request, but each poll waits for news.
  - http, long-poll: requests go to the runtime server over its public E2B URL.
- pause and resume.
- checkpoint capture, then restore onto a fresh generation.

Build the template with e2b_template.py and set E2B_API_KEY:

    AGNO_SANDBOX_LOAD_SESSIONS=8 .venv/bin/python cookbook/frameworks/sandbox/e2b/e2b_load.py

Set the session count past your plan's concurrent sandbox limit to check that the
extra creates fail cleanly. Requests and E2B API calls per turn are what grow with
concurrent users; the idle poll is the cost of one control request with nothing
pending. Latencies depend on your network and E2B region. Every computer is killed
at the end, and the script checks none is left.
"""

import asyncio
import math
import os
import statistics
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.client import RuntimeExecution, SandboxRuntimeClient
from agno.sandbox.e2b import E2BCheckpointTransfer, E2BSandbox

TEMPLATE = os.getenv("E2B_TEMPLATE", "agno-sandbox")
SESSIONS = int(os.getenv("AGNO_SANDBOX_LOAD_SESSIONS", "8"))
TURN_SECONDS = float(os.getenv("AGNO_SANDBOX_LOAD_TURN_SECONDS", "3"))
RUNTIME_PORT = 8765
ENV = {"AGNO_SANDBOX_TEST_RUNTIME": "1"}


class Meter:
    """Times runtime requests and counts the E2B API calls a provider makes."""

    def __init__(self, provider: E2BSandbox) -> None:
        self.requests: list = []
        self.api_calls = 0
        self._wrapped: set = set()
        rpc, aget, connection = provider.arpc, provider.aget, provider._connection

        async def timed(handle, operation, payload):
            started = time.perf_counter()
            try:
                return await rpc(handle, operation, payload)
            finally:
                self.requests.append(time.perf_counter() - started)

        async def counted_get(provider_ref):
            self.api_calls += 1
            return await aget(provider_ref)

        async def counted_connection(handle):
            sandbox = await connection(handle)
            if id(sandbox) not in self._wrapped:
                self._wrapped.add(id(sandbox))
                sandbox.commands.run = self._count(sandbox.commands.run)
                sandbox.files.write = self._count(sandbox.files.write)
            return sandbox

        provider.arpc = timed  # type: ignore[method-assign]
        provider.aget = counted_get  # type: ignore[method-assign]
        provider._connection = counted_connection  # type: ignore[method-assign]

    def _count(self, call):
        async def counted(*args, **kwargs):
            self.api_calls += 1
            return await call(*args, **kwargs)

        return counted

    def reset(self) -> None:
        self.requests.clear()
        self.api_calls = 0


def summary(values: list) -> str:
    if not values:
        return "no samples"
    ordered = sorted(values)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    return f"p50={statistics.median(ordered):6.2f}s  p95={p95:6.2f}s  max={ordered[-1]:6.2f}s"


async def timed(call):
    started = time.perf_counter()
    result = await call
    return result, time.perf_counter() - started


async def run_turn(client, handle, execution_id: str, wait: float) -> float:
    started = time.perf_counter()
    execution = await client.astart(
        handle,
        execution_id=execution_id,
        run_id=execution_id,
        sdk="fixture",
        input="ping",
        config={"delay": TURN_SECONDS},
    )
    result = await client.await_result(execution, timeout=180, wait=wait)
    assert (
        result["type"] == "execution_finished" and result["run"]["content"] == "ping"
    ), result
    return time.perf_counter() - started


async def measure_turns(client, meter, handles, label: str, wait: float) -> None:
    # A handle without a runtime URL takes the exec transport on the same computer.
    if label.startswith("exec"):
        handles = [replace(handle, runtime_url=None) for handle in handles]
    key = label.split(",")[0] + ("-long" if wait else "-loop")
    meter.reset()
    started = time.perf_counter()
    turns = await asyncio.gather(
        *(
            run_turn(client, handle, f"{key}-{i}", wait)
            for i, handle in enumerate(handles)
        )
    )
    wall = time.perf_counter() - started
    requests, api_calls = len(meter.requests), meter.api_calls
    probe = []
    for i, handle in enumerate(handles):
        done = RuntimeExecution(handle, f"{key}-{i}", f"{key}-{i}")
        for _ in range(3):
            began = time.perf_counter()
            await client.apoll(done, wait=0)
            probe.append(time.perf_counter() - began)
    count = len(handles)
    print(
        f"  {label:<16} wall={wall:6.2f}s  turn mean={statistics.mean(turns):6.2f}s  "
        f"requests/turn={requests / count:5.1f}  E2B calls/turn={api_calls / count:5.1f}  "
        f"idle poll p50={statistics.median(probe) * 1000:6.1f}ms  max={max(probe) * 1000:6.1f}ms"
    )


async def create_all(provider, generation: int, sessions: list) -> list:
    results = await asyncio.gather(
        *(
            timed(
                provider.acreate(
                    session, agent_id="coder", env=ENV, generation=generation
                )
            )
            for session in sessions
        ),
        return_exceptions=True,
    )
    created = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    print(
        f"  generation {generation}: {len(created)}/{len(sessions)} created  "
        + summary([seconds for _, seconds in created])
    )
    for error in failures[:3]:
        print(f"    failed: {type(error).__name__}: {str(error)[:200]}")
    return [handle for handle, _ in created]


async def leftovers(namespace: str) -> int:
    from e2b import AsyncSandbox, SandboxQuery, SandboxState

    paginator = AsyncSandbox.list(
        query=SandboxQuery(
            metadata={"namespace": namespace},
            state=[SandboxState.RUNNING, SandboxState.PAUSED],
        )
    )
    found = []
    while paginator.has_next:
        found.extend(await paginator.next_items())
    return len(found)


async def main() -> None:
    namespace = "e2b-load-" + uuid4().hex[:8]
    provider = E2BSandbox(
        TEMPLATE, namespace=namespace, lifetime=1800, runtime_port=RUNTIME_PORT
    )
    client = SandboxRuntimeClient(provider)
    sessions = [f"session-{i}" for i in range(SESSIONS)]
    print(
        f"template={TEMPLATE} sessions={SESSIONS} fixture turn={TURN_SECONDS:.0f}s, no model calls"
    )
    handles: list = []
    try:
        print("create")
        handles = await create_all(provider, 1, sessions)
        if not handles:
            return
        meter = Meter(provider)
        print("turns")
        await measure_turns(client, meter, handles, "exec, poll loop", wait=0)
        await measure_turns(client, meter, handles, "exec, long-poll", wait=10)
        await measure_turns(client, meter, handles, "http, long-poll", wait=10)

        print("pause and resume")
        paused = await asyncio.gather(*(timed(provider.apause(h)) for h in handles))
        print("  pause   " + summary([seconds for _, seconds in paused]))
        resumed = await asyncio.gather(*(timed(provider.aresume(h)) for h in handles))
        print("  resume  " + summary([seconds for _, seconds in resumed]))
        handles = [handle for handle, _ in resumed]

        print("checkpoint")
        with TemporaryDirectory() as directory:
            transfer = E2BCheckpointTransfer(
                provider, FileCheckpointStore(Path(directory) / "objects")
            )
            captured = await asyncio.gather(
                *(
                    timed(transfer.acapture(h, state={"session": h.session_id}))
                    for h in handles
                )
            )
            sizes = [reference.size for reference, _ in captured]
            print(
                "  capture "
                + summary([seconds for _, seconds in captured])
                + f"  mean size={statistics.mean(sizes):,.0f} bytes"
            )
            # Free the first generation before creating the second, to stay within the plan's limit.
            originals = {h.session_id: ref for h, (ref, _) in zip(handles, captured)}
            await asyncio.gather(*(provider.adestroy(h) for h in handles))
            handles = await create_all(provider, 2, list(originals))
            restored = await asyncio.gather(
                *(timed(transfer.arestore(h, originals[h.session_id])) for h in handles)
            )
            assert all(
                state == {"session": h.session_id}
                for h, (state, _) in zip(handles, restored)
            )
            print("  restore " + summary([seconds for _, seconds in restored]))
    finally:
        await asyncio.gather(
            *(provider.adestroy(h) for h in handles), return_exceptions=True
        )
        # Kill anything a failed create left behind, then confirm nothing is left.
        for session in sessions:
            for generation in (1, 2):
                handle = await provider.afind(
                    session, agent_id="coder", generation=generation, env=ENV
                )
                if handle is not None:
                    await provider.adestroy(handle)
        print(f"left running in namespace {namespace}: {await leftovers(namespace)}")


if __name__ == "__main__":
    asyncio.run(main())
