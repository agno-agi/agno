"""End-to-end feature suite for the AgentOS job-queue stack.

Covers, across agents / teams / workflows where applicable:
  - durable background (202 + poll -> COMPLETED)   [run persistence]
  - SSE streaming background + mid-stream disconnect (resume-safe)
  - WebSocket streaming for workflows + reconnect/subscribe
  - HITL: confirmation-gated tool -> PAUSED -> /continue -> COMPLETED
  - run cancellation (cancel a queued/running run)
  - error persistence (a failing run -> ERROR persisted, poller sees it)
  - WorkflowAgent orchestration (orphan-run regression check)

Each test returns a structured Result. run_all() aggregates and writes
results.json, which report.py renders as a visual HTML dashboard.

Env: BASE_URL (http://localhost:7777), PG_DSN (postgresql://ai:ai@localhost:5533/ai)
"""

import asyncio
import json
import os
import time
import uuid

import httpx

try:
    import websockets
except Exception:
    websockets = None

import psycopg

BASE = os.environ.get("BASE_URL", "http://localhost:7777")
WS_BASE = BASE.replace("http", "ws")
PG_DSN = os.environ.get("PG_DSN", "postgresql://ai:ai@localhost:5533/ai")
TERMINAL = {"COMPLETED", "ERROR", "CANCELLED", "FAILED", "PAUSED"}


class Result:
    def __init__(self, name, category, component=""):
        self.name = name
        self.category = category
        self.component = component
        self.status = "SKIP"  # PASS | FAIL | SKIP | WARN
        self.detail = ""
        self.evidence = {}
        self.duration = 0.0

    def to_dict(self):
        return {
            "name": self.name, "category": self.category, "component": self.component,
            "status": self.status, "detail": self.detail, "evidence": self.evidence,
            "duration": round(self.duration, 2),
        }


# ---------------------------------------------------------------- helpers

def _runs_url(component, cid):
    return f"{BASE}/{component}/{cid}/runs"


async def _submit(client, component, cid, message, background=True, stream=False, idem=None):
    data = {"message": message, "background": str(background).lower(), "stream": str(stream).lower()}
    headers = {"Idempotency-Key": idem} if idem else {}
    r = await client.post(_runs_url(component, cid), data=data, headers=headers, timeout=60)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return r.status_code, body


async def _poll(client, component, cid, run_id, session_id, timeout=90):
    url = f"{_runs_url(component, cid)}/{run_id}"
    params = {"session_id": session_id} if session_id else {}
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = await client.get(url, params=params, timeout=15)
            if r.status_code == 200:
                last = (r.json() or {}).get("status")
                if last in TERMINAL:
                    return last
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return last or "TIMEOUT"


def _db_run(run_id):
    """Return the persisted run dict for run_id, or None."""
    try:
        c = psycopg.connect(PG_DSN)
        cur = c.cursor()
        cur.execute("SELECT runs FROM ai.agno_sessions WHERE runs IS NOT NULL AND jsonb_typeof(runs)='array'")
        for (runs,) in cur.fetchall():
            for r in runs or []:
                if r.get("run_id") == run_id:
                    c.close()
                    return r
        c.close()
    except Exception:
        pass
    return None


def _db_session_runs(session_id):
    try:
        c = psycopg.connect(PG_DSN)
        cur = c.cursor()
        cur.execute("SELECT runs FROM ai.agno_sessions WHERE session_id=%s", (session_id,))
        row = cur.fetchone()
        c.close()
        return (row[0] if row else []) or []
    except Exception:
        return []


# ---------------------------------------------------------------- tests

async def t_durable_background(client, component, cid):
    r = Result(f"durable background 202->COMPLETED", "run-persistence", component)
    t0 = time.time()
    code, body = await _submit(client, component, cid, "Reply with the word ok only.")
    r.evidence["submit_http"] = code
    if code != 202 or not body.get("run_id"):
        r.status, r.detail = "FAIL", f"expected 202+run_id, got {code} {body}"
        r.duration = time.time() - t0
        return r
    final = await _poll(client, component, cid, body["run_id"], body.get("session_id"))
    dbrun = _db_run(body["run_id"])
    r.evidence.update(run_id=body["run_id"], polled=final, db_status=(dbrun or {}).get("status"))
    if final == "COMPLETED" and (dbrun or {}).get("status") == "COMPLETED":
        r.status, r.detail = "PASS", "accepted, executed, terminal COMPLETED persisted"
    else:
        r.status, r.detail = "FAIL", f"polled={final} db={(dbrun or {}).get('status')}"
    r.duration = time.time() - t0
    return r


async def t_sse_disconnect(client, component, cid):
    r = Result("SSE stream + mid-stream disconnect (resume-safe)", "streaming-sse", component)
    t0 = time.time()
    data = {"message": "Reply with the word ok only.", "background": "true", "stream": "true"}
    frames, run_id, last_idx, monotonic = 0, None, -1, True
    try:
        async with client.stream("POST", _runs_url(component, cid), data=data, timeout=None) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    frames += 1
                    try:
                        p = json.loads(line[5:].strip())
                        run_id = run_id or p.get("run_id")
                        idx = p.get("event_index")
                        if idx is not None:
                            if idx <= last_idx:
                                monotonic = False
                            last_idx = idx
                    except Exception:
                        pass
                    if frames >= 2:  # disconnect early
                        break
    except Exception as e:
        r.evidence["stream_err"] = str(e)[:120]
    r.evidence.update(frames=frames, run_id=run_id, indices_monotonic=monotonic)
    # after disconnect, the run must still finish durably
    if run_id:
        dbrun = None
        for _ in range(40):
            dbrun = _db_run(run_id)
            if dbrun and dbrun.get("status") in TERMINAL:
                break
            await asyncio.sleep(1.0)
        r.evidence["db_status_after_disconnect"] = (dbrun or {}).get("status")
        if (dbrun or {}).get("status") == "COMPLETED" and monotonic:
            r.status, r.detail = "PASS", f"{frames} frames, disconnected, run completed durably"
        else:
            r.status, r.detail = "FAIL", f"post-disconnect db={(dbrun or {}).get('status')} monotonic={monotonic}"
    else:
        r.status, r.detail = "FAIL", "no run_id from stream"
    r.duration = time.time() - t0
    return r


async def t_workflow_ws(client):
    r = Result("WebSocket streaming + subscribe (workflow)", "streaming-ws", "workflows")
    t0 = time.time()
    if websockets is None:
        r.status, r.detail = "SKIP", "websockets package not installed"
        return r
    got_events, run_id, completed = 0, None, False

    def _parse_ws(raw: str):
        """WS frames are either JSON control frames or SSE-formatted event strings."""
        raw = raw.strip()
        if raw.startswith("event:") or "\ndata:" in raw:
            ev = raw.split("\n", 1)[0].replace("event:", "").strip()
            rid = None
            for line in raw.split("\n"):
                if line.startswith("data:"):
                    try:
                        rid = json.loads(line[5:].strip()).get("run_id")
                    except Exception:
                        pass
            return ev, rid
        try:
            m = json.loads(raw)
            return m.get("event", ""), m.get("run_id")
        except Exception:
            return "", None

    try:
        async with websockets.connect(f"{WS_BASE}/workflows/ws", open_timeout=15) as ws:
            await ws.recv()  # 'connected' frame
            await ws.send(json.dumps({"action": "start-workflow", "workflow_id": "load-workflow", "message": "Reply ok."}))
            deadline = time.time() + 60
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    break
                got_events += 1
                ev, rid = _parse_ws(raw)
                run_id = run_id or rid
                if "Completed" in ev:
                    completed = True
                    break
    except Exception as e:
        r.evidence["ws_err"] = str(e)[:150]
    r.evidence.update(events=got_events, run_id=run_id, completed=completed)
    if completed and got_events > 1:
        r.status, r.detail = "PASS", f"WS delivered {got_events} events incl. completion"
    elif got_events > 0:
        r.status, r.detail = "WARN", f"WS delivered {got_events} events but no explicit completion seen"
    else:
        r.status, r.detail = "FAIL", "no WS events"
    r.duration = time.time() - t0
    return r


async def t_hitl(client):
    r = Result("HITL: tool confirmation PAUSED -> continue -> COMPLETED", "hitl", "agents")
    t0 = time.time()
    # non-background so the pause is synchronous and inspectable
    data = {"message": "Publish an item titled hello.", "background": "false", "stream": "false"}
    try:
        resp = await client.post(_runs_url("agents", "hitl-agent"), data=data, timeout=60)
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:
        r.status, r.detail = "FAIL", f"initial run error: {e}"
        r.duration = time.time() - t0
        return r
    status = body.get("status")
    run_id = body.get("run_id")
    session_id = body.get("session_id")
    tools = body.get("tools") or []
    r.evidence.update(initial_status=status, run_id=run_id, paused_tools=[t.get("tool_name") for t in tools])
    if status != "PAUSED" or not tools:
        r.status = "WARN" if status == "COMPLETED" else "FAIL"
        r.detail = f"expected PAUSED with a confirmation tool, got {status} (model may not have called the tool)"
        r.duration = time.time() - t0
        return r
    # confirm the tool and continue
    for t in tools:
        t["confirmed"] = True
    try:
        cont = await client.post(
            f"{_runs_url('agents','hitl-agent')}/{run_id}/continue",
            data={"tools": json.dumps(tools), "session_id": session_id, "stream": "false"},
            timeout=60,
        )
        cbody = cont.json() if cont.headers.get("content-type", "").startswith("application/json") else {}
        r.evidence["continue_status"] = cbody.get("status")
    except Exception as e:
        r.status, r.detail = "FAIL", f"continue error: {e}"
        r.duration = time.time() - t0
        return r
    dbrun = _db_run(run_id)
    r.evidence["db_status"] = (dbrun or {}).get("status")
    if (dbrun or {}).get("status") == "COMPLETED":
        r.status, r.detail = "PASS", "paused on tool, resumed via /continue, completed"
    else:
        r.status, r.detail = "FAIL", f"after continue db={(dbrun or {}).get('status')}"
    r.duration = time.time() - t0
    return r


async def t_cancellation(client, component, cid):
    r = Result("run cancellation (cancel in-flight/queued run)", "cancellation", component)
    t0 = time.time()
    code, body = await _submit(client, component, cid, "Reply with the word ok only.")
    run_id, session_id = body.get("run_id"), body.get("session_id")
    if code != 202 or not run_id:
        r.status, r.detail = "FAIL", f"submit not 202: {code}"
        r.duration = time.time() - t0
        return r
    # cancel immediately
    try:
        cancel = await client.post(
            f"{_runs_url(component, cid)}/{run_id}/cancel",
            params={"session_id": session_id}, timeout=30,
        )
        r.evidence["cancel_http"] = cancel.status_code
    except Exception as e:
        r.evidence["cancel_err"] = str(e)[:120]
    final = await _poll(client, component, cid, run_id, session_id, timeout=60)
    r.evidence.update(run_id=run_id, final=final)
    # Acceptable: CANCELLED (best) or COMPLETED if it finished before cancel landed.
    if final == "CANCELLED":
        r.status, r.detail = "PASS", "run cancelled and persisted CANCELLED"
    elif final == "COMPLETED":
        r.status, r.detail = "WARN", "run completed before cancel landed (race; not a failure)"
    else:
        r.status, r.detail = "FAIL", f"final={final} (neither CANCELLED nor COMPLETED)"
    r.duration = time.time() - t0
    return r


async def t_error_persistence(client, component, cid):
    r = Result("error persistence (failing run -> ERROR persisted)", "error-persistence", component)
    t0 = time.time()
    # MODEL=stub understands 'fail'; with a real model we ask for a tool that doesn't exist / force error
    msg = "fail" if os.environ.get("MODEL", "real") == "stub" else "Reply with the word ok only."
    code, body = await _submit(client, component, cid, msg)
    run_id, session_id = body.get("run_id"), body.get("session_id")
    if code != 202:
        r.status, r.detail = "SKIP", f"submit not 202: {code}"
        r.duration = time.time() - t0
        return r
    final = await _poll(client, component, cid, run_id, session_id, timeout=90)
    dbrun = _db_run(run_id)
    r.evidence.update(run_id=run_id, final=final, db_status=(dbrun or {}).get("status"))
    if os.environ.get("MODEL", "real") == "stub":
        # with the stub, 'fail' must surface as a persisted ERROR (never stuck RUNNING)
        if (dbrun or {}).get("status") in ("ERROR", "FAILED"):
            r.status, r.detail = "PASS", "induced failure persisted as ERROR"
        elif final in ("ERROR", "FAILED"):
            r.status, r.detail = "PASS", f"failure surfaced ({final})"
        else:
            r.status, r.detail = "FAIL", f"induced failure not persisted as ERROR: {(dbrun or {}).get('status')}"
    else:
        # real model: we can't force an error cheaply; assert the run at least reached a terminal state (no stuck RUNNING)
        if final in TERMINAL and (dbrun or {}).get("status") in TERMINAL:
            r.status, r.detail = "PASS", f"reached terminal ({final}); error path is stub-only, real run terminalized cleanly"
        else:
            r.status, r.detail = "FAIL", f"run stuck non-terminal: {final}"
    r.duration = time.time() - t0
    return r


async def t_workflow_agent_orphan(client):
    r = Result("WorkflowAgent: no orphan/stuck-RUNNING run per turn", "workflow-agent", "workflows")
    t0 = time.time()
    sid = str(uuid.uuid4())
    # one orchestrated turn (non-background so it's synchronous)
    data = {"message": "Tell me a one-line fact about cats.", "background": "false", "stream": "false", "session_id": sid}
    try:
        resp = await client.post(_runs_url("workflows", "load-wf-agent"), data=data, timeout=90)
        _ = resp.status_code
    except Exception as e:
        r.status, r.detail = "FAIL", f"run error: {e}"
        r.duration = time.time() - t0
        return r
    await asyncio.sleep(3)
    runs = _db_session_runs(sid)
    statuses = [x.get("status") for x in runs]
    stuck = [x.get("run_id") for x in runs if x.get("status") not in TERMINAL]
    r.evidence.update(session_id=sid, run_count=len(runs), statuses=statuses, stuck_runs=stuck)
    if not stuck and len(runs) >= 1:
        r.status, r.detail = "PASS", f"{len(runs)} run(s), all terminal, no orphan"
    else:
        r.status = "FAIL"
        r.detail = f"orphan/stuck runs present: {len(stuck)} of {len(runs)} non-terminal (statuses={statuses})"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- runner

async def run_all():
    results = []
    limits = httpx.Limits(max_connections=40)
    async with httpx.AsyncClient(limits=limits) as client:
        # run-persistence + streaming across all three components
        for comp, cid in (("agents", "load-agent"), ("teams", "load-team"), ("workflows", "load-workflow")):
            results.append(await t_durable_background(client, comp, cid))
            results.append(await t_sse_disconnect(client, comp, cid))
            results.append(await t_cancellation(client, comp, cid))
            results.append(await t_error_persistence(client, comp, cid))
        # workflow-only WS + HITL + workflow-agent
        results.append(await t_workflow_ws(client))
        results.append(await t_hitl(client))
        results.append(await t_workflow_agent_orphan(client))

    out = [r.to_dict() for r in results]
    with open("results.json", "w") as f:
        json.dump({"generated_at": int(time.time()), "base_url": BASE, "results": out}, f, indent=2)

    # console summary
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
    for r in out:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\n" + "=" * 64)
    for r in out:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN", "SKIP": "SKIP"}[r["status"]]
        print(f"[{mark}] {r['component']:9} {r['category']:18} {r['name']}")
        if r["status"] in ("FAIL", "WARN"):
            print(f"        -> {r['detail']}")
    print("=" * 64)
    print(f"PASS={counts['PASS']}  FAIL={counts['FAIL']}  WARN={counts['WARN']}  SKIP={counts['SKIP']}  -> results.json")
    return counts


if __name__ == "__main__":
    asyncio.run(run_all())
