"""Reproduce PR #9133 finding #7: a retryable STREAMING timeout force-closes the
live tail with a terminal ERROR frame, even though the job will retry.

Setup (env on the server): MODEL=stub, MAX_ATTEMPTS=2, TIMEOUT_SECONDS=3.
A submission with input 'sleep=6' exceeds the 3s timeout on attempt 1, so the
worker's timeout handler runs. On the BUGGY code it calls _terminate_stream_view
(publishes a terminal ERROR sentinel -> closes the SSE tail) and THEN requeues.

Expected on BUGGY code:  the SSE tail receives a terminal 'error' frame while the
                         job still has retry budget (attempt 1 of 2) -> FAIL.
Expected on FIXED code:  no terminal error frame during the retry window; the
                         stream stays open (or ends only when the run truly
                         terminates after retries) -> PASS.

Run: BASE_URL=http://localhost:7777 python test_timeout_tail.py
"""

import asyncio
import json
import os
import time

import httpx

BASE = os.environ.get("BASE_URL", "http://localhost:7777")
COMPONENT = os.environ.get("COMPONENT", "agents")
CID = os.environ.get("COMPONENT_ID", "load-agent")
# input that sleeps longer than TIMEOUT_SECONDS so attempt 1 times out
SLEEP = os.environ.get("SLEEP_INPUT", "sleep=6")


async def main():
    url = f"{BASE}/{COMPONENT}/{CID}/runs"
    data = {"message": SLEEP, "background": "true", "stream": "true"}
    frames = []
    error_frame = None
    completed_frame = None
    run_id = None
    t0 = time.time()

    print(f"submitting streaming run '{SLEEP}' (timeout should fire on attempt 1)...")
    async with httpx.AsyncClient(timeout=None) as c:
        try:
            async with c.stream("POST", url, data=data) as r:
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        ev = line.split(":", 1)[1].strip()
                        frames.append(ev)
                        if ev.lower() == "error":
                            error_frame = time.time() - t0
                        if "completed" in ev.lower():
                            completed_frame = time.time() - t0
                    elif line.startswith("data:"):
                        try:
                            p = json.loads(line[5:].strip())
                            run_id = run_id or p.get("run_id")
                            if p.get("event", "").lower() == "error":
                                error_frame = error_frame or (time.time() - t0)
                        except Exception:
                            pass
                    # stop once the tail closes (terminal) or we've watched long enough
                    if time.time() - t0 > 25:
                        break
        except Exception as e:
            print(f"stream ended: {e}")

    print(f"\nframes received ({len(frames)}): {frames[:20]}")
    print(f"run_id: {run_id}")
    print(f"error frame at: {error_frame}s")
    print(f"completed frame at: {completed_frame}s")

    # The bug: an ERROR terminal frame arrives around the timeout (~3-6s) while the
    # job is being requeued for a retry. On fixed code the tail should NOT be
    # terminated with error during the retry window.
    print("\n=== VERDICT ===")
    if error_frame is not None and completed_frame is None:
        print(f"FAIL (#7 reproduced): tail received a terminal ERROR frame at ~{error_frame:.1f}s "
              f"while the job still had retry budget — viewer told the run failed before the retry ran.")
    elif completed_frame is not None:
        print("PASS: stream reached COMPLETED (retry succeeded and the viewer saw it).")
    else:
        print("INCONCLUSIVE: no terminal error and no completed frame within the watch window. "
              "Check queue stats / run row for the actual outcome.")


if __name__ == "__main__":
    asyncio.run(main())
