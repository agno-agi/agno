"""Async load driver for the AgentOS job queue. No k6 - pure asyncio + httpx.

Writes a client ledger (JSONL) that the reconciler diffs against the DB.

Usage:
  python driver.py --phase bounded   --n 500  --concurrency 200
  python driver.py --phase idempotency --n 200            # all same key
  python driver.py --phase stream     --n 100             # SSE, random disconnect
  python driver.py --phase depth      --n 3000            # expect 429s

Env: BASE_URL (default http://localhost:7777), COMPONENT (agents|teams|workflows)
"""

import argparse
import asyncio
import json
import os
import time
import uuid

import httpx

BASE = os.environ.get("BASE_URL", "http://localhost:7777")
COMPONENT = os.environ.get("COMPONENT", "agents")
COMPONENT_ID = {"agents": "load-agent", "teams": "load-team", "workflows": "load-workflow"}[COMPONENT]
LEDGER = os.environ.get("LEDGER", "client_ledger.jsonl")

_lock = asyncio.Lock()


async def _record(row: dict):
    async with _lock:
        with open(LEDGER, "a") as f:
            f.write(json.dumps(row) + "\n")


def _url() -> str:
    return f"{BASE}/{COMPONENT}/{COMPONENT_ID}/runs"


async def submit_background(client: httpx.AsyncClient, message: str, idem: str | None = None) -> dict:
    """POST background=true, non-stream. Returns {run_id, session_id, status, http}."""
    headers = {"Idempotency-Key": idem} if idem else {}
    # stream defaults to True on the endpoint; force False for the durable 202+poll path.
    data = {"message": message, "background": "true", "stream": "false"}
    t0 = time.time()
    try:
        r = await client.post(_url(), data=data, headers=headers, timeout=30)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        row = {
            "kind": "submit", "http": r.status_code, "run_id": body.get("run_id"),
            "session_id": body.get("session_id"), "status": body.get("status"), "idem": idem, "t": t0,
        }
    except Exception as e:
        row = {"kind": "submit", "http": -1, "error": str(e), "idem": idem, "t": t0}
    await _record(row)
    return row


async def poll_until_terminal(client: httpx.AsyncClient, run_id: str, session_id: str | None = None, timeout: float = 120) -> str:
    """Poll GET run until terminal or timeout. Records the final status."""
    url = f"{BASE}/{COMPONENT}/{COMPONENT_ID}/runs/{run_id}"
    params = {"session_id": session_id} if session_id else {}
    terminal = {"COMPLETED", "ERROR", "CANCELLED", "FAILED"}
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = await client.get(url, params=params, timeout=15)
            if r.status_code == 200:
                last = (r.json() or {}).get("status")
                if last in terminal:
                    break
        except Exception:
            pass
        await asyncio.sleep(1.0)
    await _record({"kind": "poll", "run_id": run_id, "final": last})
    return last or "TIMEOUT"


async def stream_run(client: httpx.AsyncClient, message: str, disconnect_after: int | None) -> dict:
    """POST background+stream, count SSE frames, optionally disconnect early."""
    data = {"message": message, "background": "true", "stream": "true"}
    frames, run_id, last_index, err = 0, None, -1, None
    try:
        async with client.stream("POST", _url(), data=data, timeout=None) as r:
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    frames += 1
                    try:
                        payload = json.loads(line[5:].strip())
                        run_id = run_id or payload.get("run_id")
                        idx = payload.get("event_index")
                        if idx is not None:
                            if idx <= last_index:
                                err = f"non-monotonic index {idx}<={last_index}"
                            last_index = idx
                    except Exception:
                        pass
                    if disconnect_after and frames >= disconnect_after:
                        break
    except Exception as e:
        err = str(e)
    await _record({"kind": "stream", "run_id": run_id, "frames": frames, "last_index": last_index, "err": err})
    return {"run_id": run_id, "frames": frames}


# Short real-model prompts: cheap, fast, deterministic-enough to reconcile.
def _prompt(i: int) -> str:
    return f"Reply with the number {i} and nothing else."


async def _bounded_worker(client, sem, i):
    async with sem:
        row = await submit_background(client, _prompt(i))
        if row.get("run_id"):
            await poll_until_terminal(client, row["run_id"], row.get("session_id"))


async def run_phase(phase: str, n: int, concurrency: int):
    open(LEDGER, "w").close()  # reset ledger
    limits = httpx.Limits(max_connections=concurrency + 20, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits) as client:
        sem = asyncio.Semaphore(concurrency)

        if phase == "bounded":
            await asyncio.gather(*[_bounded_worker(client, sem, i) for i in range(n)])

        elif phase == "idempotency":
            key = f"idem-{uuid.uuid4()}"

            async def one(i):
                async with sem:
                    await submit_background(client, "Reply with the word dedup only.", idem=key)

            await asyncio.gather(*[one(i) for i in range(n)])

        elif phase == "depth":
            # fire fast, don't poll -> fill the queue, expect 429 beyond depth
            async def one(i):
                async with sem:
                    await submit_background(client, "Reply with the word fill only.")

            await asyncio.gather(*[one(i) for i in range(n)])

        elif phase == "stream":
            import random

            async def one(i):
                async with sem:
                    res = await stream_run(client, _prompt(i), disconnect_after=random.choice([None, 2, 3]))
                    if res.get("run_id"):
                        await poll_until_terminal(client, res["run_id"])

            await asyncio.gather(*[one(i) for i in range(n)])

        else:
            raise SystemExit(f"unknown phase {phase}")

    print(f"[driver] phase={phase} n={n} done -> {LEDGER}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=200)
    args = ap.parse_args()
    asyncio.run(run_phase(args.phase, args.n, args.concurrency))
