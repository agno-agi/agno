"""Many concurrent Modal sandboxes. This creates billable compute.

Each session is created, runs one fixture turn, runs one command and is
destroyed. The fixture makes no model calls. Sign in to Modal first
(modal token new).

  .venvs/demo/bin/python cookbook/frameworks/sandbox/modal/modal_load.py --sessions 50

Modal limits how many sandboxes a workspace runs at once, so a burst larger than
that limit queues or fails at create. --create-rate paces creates, and a long
--turn-seconds keeps the sandboxes alive at the same time.
"""

import argparse
import asyncio
import statistics
import time
from collections import Counter
from uuid import uuid4

from agno.sandbox.client import SandboxRuntimeClient
from agno.sandbox.modal import ModalSandbox
from modal_image import runtime_image


def classify(error: BaseException) -> str:
    cause = error.__cause__ or error
    return f"{type(error).__name__}/{type(cause).__name__}: {str(cause)[:160]}"


# The first full example of each failure, with when it happened.
examples = {}


async def one_session(
    sandbox, client, index, start_at, turn_seconds, timings, errors, alive
):
    await asyncio.sleep(max(0.0, start_at - time.monotonic()))
    phases = {}
    handle = None
    phase = "create"
    try:
        started = time.monotonic()
        handle = await sandbox.acreate(
            f"load-{index}", agent_id="coder", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"}
        )
        phases["create"] = time.monotonic() - started
        alive["now"] += 1
        alive["peak"] = max(alive["peak"], alive["now"])

        phase = "turn"
        started = time.monotonic()
        execution = await client.astart(
            handle,
            execution_id="turn-1",
            run_id="turn-1",
            sdk="fixture",
            input=f"session {index}",
            config={"delay": turn_seconds},
            execution_timeout=300,
        )
        result = await client.await_result(execution, timeout=300)
        if result["type"] != "execution_finished":
            raise RuntimeError("Turn ended with " + result["type"])
        phases["turn"] = time.monotonic() - started

        phase = "exec"
        started = time.monotonic()
        output = await sandbox.aexec(handle, ["cat", "fixture-effects.txt"], timeout=30)
        if output.exit_code or "turn-1" not in output.stdout:
            raise RuntimeError(f"Command exited {output.exit_code}")
        phases["exec"] = time.monotonic() - started
    except Exception as error:
        key = (phase, classify(error))
        errors[key] += 1
        examples.setdefault(key, time.strftime("%H:%M:%S", time.gmtime()))
    finally:
        if handle is not None:
            started = time.monotonic()
            try:
                await sandbox.adestroy(handle)
                phases["destroy"] = time.monotonic() - started
            except Exception as error:
                key = ("destroy", classify(error))
                errors[key] += 1
                examples.setdefault(key, time.strftime("%H:%M:%S", time.gmtime()))
            alive["now"] -= 1
        for name, value in phases.items():
            timings.setdefault(name, []).append(value)


def describe(values):
    values = sorted(values)
    p90 = values[min(len(values) - 1, int(0.9 * len(values)))]
    return f"n={len(values)} p50={statistics.median(values):.2f}s p90={p90:.2f}s max={values[-1]:.2f}s"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=20)
    parser.add_argument("--turn-seconds", type=float, default=5.0)
    parser.add_argument(
        "--create-rate",
        type=float,
        default=0,
        help="New sessions per second; 0 starts them all at once",
    )
    args = parser.parse_args()

    sandbox = ModalSandbox(
        runtime_image(),
        namespace="load-" + uuid4().hex[:8],
        cpu=0.25,
        memory_mb=512,
        lifetime=900,
    )
    client = SandboxRuntimeClient(sandbox)
    timings, errors, alive = {}, Counter(), {"now": 0, "peak": 0}
    started = time.monotonic()
    spacing = 1 / args.create_rate if args.create_rate > 0 else 0.0
    await asyncio.gather(
        *(
            one_session(
                sandbox,
                client,
                index,
                started + index * spacing,
                args.turn_seconds,
                timings,
                errors,
                alive,
            )
            for index in range(args.sessions)
        )
    )
    completed = len(timings.get("exec", []))
    print(
        f"{completed} of {args.sessions} sessions completed in {time.monotonic() - started:.1f}s"
    )
    print(f"  peak sessions alive at once: {alive['peak']}")
    for name in ("create", "turn", "exec", "destroy"):
        if timings.get(name):
            print(f"  {name}: {describe(timings[name])}")
    for (phase, kind), count in errors.most_common():
        print(
            f"  {phase} failed {count} times: {kind} (first at {examples[(phase, kind)]})"
        )


if __name__ == "__main__":
    asyncio.run(main())
