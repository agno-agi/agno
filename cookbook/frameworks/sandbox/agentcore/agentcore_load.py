"""Many concurrent AgentCore sessions. This creates billable compute.

Each session is created, runs one fixture turn, runs one command and is
destroyed. The fixture makes no model calls. Set AGENTCORE_RUNTIME_ARN to a
runtime deployed by agentcore_setup.py.

  .venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_load.py --sessions 100

AgentCore's default quota is 25 new sessions per second per account, so large
bursts are throttled; the provider retries those rejections with jitter.
--create-rate paces creates below the quota, and a long --turn-seconds keeps
the sessions alive at the same time.
"""

import argparse
import asyncio
import os
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from agno.sandbox.agentcore import AgentCoreSandbox
from agno.sandbox.client import SandboxRuntimeClient


def classify(error: BaseException) -> str:
    response = getattr(error, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    return code or f"{type(error).__name__}: {str(error)[:160]}"


# The first full example of each failure, to tell an AgentCore error from one
# raised in front of it (an edge or auth layer answers with a non-JSON body).
examples = {}


def detail(error: BaseException) -> dict:
    response = getattr(error, "response", None) or {}
    metadata = (
        response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
    )
    headers = metadata.get("HTTPHeaders", {})
    return {
        "at": time.strftime("%H:%M:%S", time.gmtime()),
        "type": type(error).__name__,
        "status": metadata.get("HTTPStatusCode"),
        "request_id": metadata.get("RequestId") or headers.get("x-amzn-requestid"),
        "error": response.get("Error") if isinstance(response, dict) else None,
        "headers": {
            key: value
            for key, value in headers.items()
            if key in ("x-amzn-errortype", "server", "via", "x-cache", "content-type")
        },
        "text": str(error)[:400],
    }


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
        examples.setdefault(key, detail(error))
    finally:
        if handle is not None:
            started = time.monotonic()
            try:
                await sandbox.adestroy(handle)
                phases["destroy"] = time.monotonic() - started
            except Exception as error:
                key = ("destroy", classify(error))
                errors[key] += 1
                examples.setdefault(key, detail(error))
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

    # boto3 calls run on worker threads; leave room for every session at once.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=args.sessions * 2 + 16)
    )
    sandbox = AgentCoreSandbox(
        os.environ["AGENTCORE_RUNTIME_ARN"],
        namespace="load-" + uuid4().hex[:8],
        lifetime=900,
        max_connections=args.sessions * 2 + 16,
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
        print(f"  {phase} failed {count} times: {kind}")
        print(f"    first: {examples[(phase, kind)]}")


if __name__ == "__main__":
    asyncio.run(main())
