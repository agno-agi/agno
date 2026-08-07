"""Tiny real smoke: submit N background runs through the LB, poll to terminal.

Confirms the full path end to end on this branch: LB -> replica -> durable
queue -> worker (real OpenAI) -> run row terminal. Also hits /queue/stats.
"""

import asyncio
import os
import time

import httpx

BASE = os.environ.get("BASE_URL", "http://localhost:7777")
N = int(os.environ.get("N", "5"))
CID = os.environ.get("COMPONENT_ID", "load-agent")
COMP = os.environ.get("COMPONENT", "agents")


async def main():
    url = f"{BASE}/{COMP}/{CID}/runs"
    async with httpx.AsyncClient(timeout=60) as c:
        # health
        try:
            h = await c.get(f"{BASE}/health")
            print(f"health: {h.status_code}")
        except Exception as e:
            print(f"health check failed: {e}")

        # submit N background runs. Capture session_id (required to poll).
        runs = {}  # run_id -> session_id
        for i in range(N):
            r = await c.post(url, data={"message": f"Reply with the number {i} only.", "background": "true", "stream": "false"})
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            print(f"submit {i}: HTTP {r.status_code} run_id={body.get('run_id')} status={body.get('status')}")
            if body.get("run_id"):
                runs[body["run_id"]] = body.get("session_id")

        # poll each to terminal (GET requires ?session_id=)
        terminal = {"COMPLETED", "ERROR", "CANCELLED", "FAILED"}
        deadline = time.time() + 90
        done = {}
        run_ids = list(runs)
        while run_ids and time.time() < deadline:
            for rid in list(run_ids):
                rr = await c.get(f"{url}/{rid}", params={"session_id": runs[rid]})
                if rr.status_code == 200:
                    st = (rr.json() or {}).get("status")
                    if st in terminal:
                        done[rid] = st
                        run_ids.remove(rid)
            if run_ids:
                await asyncio.sleep(2)

        print("\n=== results ===")
        for rid, st in done.items():
            print(f"  {rid}: {st}")
        if run_ids:
            print(f"  STILL PENDING/RUNNING (timeout): {run_ids}")

        # ops surface
        try:
            s = await c.get(f"{BASE}/queue/stats")
            print(f"\n/queue/stats: {s.status_code} {s.text[:300]}")
        except Exception as e:
            print(f"/queue/stats failed: {e}")

        ok = len(done) == N and all(v == "COMPLETED" for v in done.values())
        print(f"\nSMOKE {'PASS' if ok else 'CHECK'}: {len(done)}/{N} terminal")


if __name__ == "__main__":
    asyncio.run(main())
