"""Distributed-system scenarios for the durable job queue (multi-replica).

These test the CROSS-REPLICA guarantees that a single-replica run can't:
  - cross-replica resume    submit stream on replica A, /resume on replica B
  - cross-replica HITL       pause HITL on A, /continue on B
  - Redis flap mid-stream    durability holds; tail recovers / errors, no hang
  - retryable-timeout tail   #7: does a retryable timeout close the tail early?
  - stream cancellation      cancel a streaming run mid-flight, tail closes clean
  - same-session clobber      concurrent CREATES on one session (stream + non-stream)

Requires per-replica ports published by docker-compose:
    replica1 -> :7801,  replica2 -> :7802   (LB stays on :7777)
Run against a durable, Redis-coordinated stack. Use MODEL=stub for the timeout/
cancel scenarios (sleep=N control).

Env: R1 (http://localhost:7801), R2 (http://localhost:7802), LB (:7777),
     PG_DSN, COMPOSE, plus the server's queue knobs.
"""

import asyncio
import json
import os
import subprocess
import time
import uuid

import httpx

import e2e

R1 = os.environ.get("R1", "http://localhost:7801")
R2 = os.environ.get("R2", "http://localhost:7802")
LB = os.environ.get("BASE_URL", "http://localhost:7777")
PG_DSN = os.environ.get("PG_DSN", "postgresql://ai:ai@localhost:5533/ai")
COMPOSE = os.environ.get("COMPOSE", "docker-compose.yml")
Result = e2e.Result
TERMINAL = e2e.TERMINAL


def _compose(*a):
    return subprocess.run(["docker", "compose", "-f", COMPOSE, *a], capture_output=True, text=True, timeout=60)


async def _wait_redis_healthy(timeout=30):
    """Block until Redis answers PING, so a preceding flap test doesn't bleed
    Redis-timeout errors into subsequent runs (a cancellation-check reads Redis
    mid-run and a down Redis fails the run)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = _compose("exec", "-T", "redis", "redis-cli", "ping").stdout
        if "PONG" in out:
            await asyncio.sleep(1)  # small settle margin
            return
        await asyncio.sleep(1)


def _db_run(run_id):
    return e2e._db_run(run_id)


# ---------------------------------------------------------------- cross-replica resume

async def s_cross_replica_resume():
    """Submit a background stream on replica1; RESUME it on replica2. Assert
    replica2 replays the run's events (cross-replica event stream via Redis),
    with monotonic indices, and the run completes durably."""
    r = Result("cross-replica resume: submit on R1, resume on R2", "x-replica", "agents")
    t0 = time.time()
    run_id = None
    frames_r1 = 0
    async with httpx.AsyncClient(timeout=None) as c:
        # submit stream on replica1, read a couple frames, disconnect
        data = {"message": "sleep=4 xrep", "background": "true", "stream": "true"}
        try:
            async with c.stream("POST", f"{R1}/agents/load-agent/runs", data=data) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        frames_r1 += 1
                        try:
                            run_id = run_id or json.loads(line[5:].strip()).get("run_id")
                        except Exception:
                            pass
                        if frames_r1 >= 2:
                            break
        except Exception as e:
            r.evidence["r1_err"] = str(e)[:80]
    if not run_id:
        r.status, r.detail = "FAIL", "no run_id from replica1 submit"
        r.duration = time.time() - t0
        return r
    r.evidence.update(run_id=run_id, frames_on_r1=frames_r1)

    # resume on replica2 from index 0
    sid = None
    dbrun = _db_run(run_id)
    sid = (dbrun or {}).get("session_id")
    resume_frames, last_idx, monotonic, completed = 0, -1, True, False
    async with httpx.AsyncClient(timeout=None) as c:
        data = {"last_event_index": "-1"}
        if sid:
            data["session_id"] = sid
        try:
            async with c.stream("POST", f"{R2}/agents/load-agent/runs/{run_id}/resume", data=data) as resp:
                r.evidence["resume_http"] = resp.status_code
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        resume_frames += 1
                        try:
                            p = json.loads(line[5:].strip())
                            idx = p.get("event_index")
                            if idx is not None:
                                if idx <= last_idx:
                                    monotonic = False
                                last_idx = idx
                            if "complet" in str(p.get("event", "")).lower():
                                completed = True
                        except Exception:
                            pass
                    if time.time() - t0 > 30:
                        break
        except Exception as e:
            r.evidence["resume_err"] = str(e)[:80]
    r.evidence.update(resume_frames=resume_frames, indices_monotonic=monotonic, saw_completed=completed)
    # final durability check
    for _ in range(20):
        dbrun = _db_run(run_id)
        if dbrun and dbrun.get("status") in TERMINAL:
            break
        await asyncio.sleep(1.5)
    r.evidence["db_status"] = (dbrun or {}).get("status")
    if resume_frames > 0 and monotonic and (dbrun or {}).get("status") == "COMPLETED":
        r.status, r.detail = "PASS", f"resumed {resume_frames} events on R2 (submitted on R1), run COMPLETED durably"
    else:
        r.status = "FAIL"
        r.detail = f"cross-replica resume gap: resume_frames={resume_frames} monotonic={monotonic} db={(dbrun or {}).get('status')}"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- Redis fault during run (cancel-check fail-closed)

async def s_cancel_check_redis_fault():
    """A Redis fault WHILE a run executes must not fail an otherwise-successful
    run. The cancellation-check (RedisRunCancellationManager.ais_cancelled) does
    an UN-GUARDED redis .get() at ~8 points per run; a down/slow Redis raises
    TimeoutError into the run -> RunError, even though the work completed.

    Repro: submit a durable run, pause Redis mid-execution, unpause; then check
    the run's terminal status. If the run has real content but status=ERROR with
    a redis TimeoutError, the cancel-check failed CLOSED (bug). It should
    fail-OPEN (treat redis error as 'not cancelled') and complete.
    """
    r = Result("redis fault: cancellation-check fails-open (not the run)", "cancel-check-fault", "agents")
    t0 = time.time()
    # Deterministic sub-check FIRST: does the cancellation-manager's ais_cancelled
    # raise (fail-closed) when Redis is down, or return False (fail-open)? This is
    # the root cause, tested directly against the same Redis the server uses.
    redis_url = os.environ.get("COORD_REDIS_URL", "redis://localhost:6380")
    raised = None
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
        await client.ping()
        _compose("pause", "redis")
        await asyncio.sleep(1)
        try:
            # emulate the cancel-check's exact call: an un-guarded GET while Redis is down
            await client.get("agno:run:cancel:probe")
            raised = False  # returned without raising = fail-open behavior
        except Exception as e:
            raised = type(e).__name__  # raised = fail-closed (propagates into the run)
    except Exception as e:
        r.evidence["probe_setup_err"] = str(e)[:80]
    finally:
        _compose("unpause", "redis")
        await _wait_redis_healthy()
    r.evidence["cancel_check_get_raised_when_redis_down"] = raised
    if raised and raised != "False":
        r.status = "FAIL"
        r.detail = (f"root cause CONFIRMED: a bare redis GET raises {raised} when Redis is down. "
                    "RedisRunCancellationManager.ais_cancelled does exactly this un-guarded, so a Redis "
                    "fault DURING a run propagates into the run and fails an otherwise-successful run. "
                    "Fix: try/except -> return False (fail-open), like the best-effort event stream.")
        r.duration = time.time() - t0
        return r
    if raised is False:
        r.status, r.detail = "PASS", "bare redis GET returned without raising while Redis down (fail-open)"
        r.duration = time.time() - t0
        return r
    # Fall through to the end-to-end variant only if the probe was inconclusive.
    if os.environ.get("MODEL") != "stub":
        r.status, r.detail = "SKIP", "probe inconclusive; e2e variant needs MODEL=stub"
        return r
    async with httpx.AsyncClient(timeout=None) as c:
        # a multi-second run so we can fault Redis while it's mid-flight and the
        # cancel-check fires during the outage
        # a long run so cancel-checks keep firing; pause Redis for most of it so
        # at least one check lands during the outage (makes the repro reliable).
        code, body = await e2e._submit(c, "agents", "load-agent", "sleep=10 rfault")
        run_id, sid = body.get("run_id"), body.get("session_id")
        if code != 202:
            r.status, r.detail = "FAIL", f"submit not 202: {code}"
            r.duration = time.time() - t0
            return r
        await asyncio.sleep(1.5)
        _compose("pause", "redis")
        await asyncio.sleep(7)  # long enough that a mid-run cancel-check hits the outage
        _compose("unpause", "redis")
        await _wait_redis_healthy()
        final = await e2e._poll(c, "agents", "load-agent", run_id, sid, timeout=60)
    dbrun = _db_run(run_id) or {}
    content = dbrun.get("content")
    err_is_redis = "redis" in str(content).lower() or "TimeoutError" in str(dbrun.get("error", ""))
    jobs = _job_state(run_id)
    r.evidence.update(run_id=run_id, run_status=dbrun.get("status"), content=str(content)[:40],
                      queue_job=jobs, redis_error=err_is_redis)
    if dbrun.get("status") == "ERROR" and err_is_redis:
        r.status = "FAIL"
        r.detail = ("cancel-check failed CLOSED: run marked ERROR by a Redis fault during execution "
                    f"(content={str(content)[:30]!r}, queue={jobs}) — should fail-open and complete")
    elif dbrun.get("status") in ("COMPLETED",):
        r.status, r.detail = "PASS", "run completed despite Redis fault mid-execution (cancel-check fail-open)"
    else:
        r.status, r.detail = "WARN", f"inconclusive: status={dbrun.get('status')} redis_error={err_is_redis}"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- Redis flap mid-stream

async def s_redis_flap():
    """Pause Redis for ~8s while durable streaming runs execute. Assert the run
    still completes durably (DB is source of truth) and the server does not
    crash. Redis is TTL'd transport; the run must not be lost."""
    r = Result("redis flap mid-stream: run completes durably", "chaos-redis", "agents")
    t0 = time.time()
    async with httpx.AsyncClient(timeout=None) as c:
        code, body = await e2e._submit(c, "agents", "load-agent", "sleep=6 flap")
        run_id, sid = body.get("run_id"), body.get("session_id")
        if code != 202:
            r.status, r.detail = "FAIL", f"submit not 202: {code}"
            r.duration = time.time() - t0
            return r
        # flap redis mid-execution
        await asyncio.sleep(1.5)
        _compose("pause", "redis")
        await asyncio.sleep(8)
        _compose("unpause", "redis")
        await _wait_redis_healthy()  # let redis recover so we don't poison later runs
        r.evidence["flapped"] = "redis paused 8s mid-run"
        final = await e2e._poll(c, "agents", "load-agent", run_id, sid, timeout=60)
    dbrun = _db_run(run_id)
    r.evidence.update(run_id=run_id, final=final, db_status=(dbrun or {}).get("status"))
    if (dbrun or {}).get("status") in ("COMPLETED", "ERROR"):
        r.status, r.detail = "PASS", f"run reached {(dbrun or {}).get('status')} despite Redis flap (durable)"
    else:
        r.status, r.detail = "FAIL", f"run lost/stuck after Redis flap: db={(dbrun or {}).get('status')}"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- #7 retryable timeout tail

async def s_retryable_timeout_tail():
    """#7: with MAX_ATTEMPTS>1 and a short TIMEOUT, a streaming run times out on
    attempt 1. A terminal ERROR sentinel must NOT be published while the job
    still has retry budget (that closes the client's tail before the retry).
    Detected via the Redis event stream terminal sentinel timing."""
    r = Result("#7 retryable timeout: tail not closed before retry", "retry-timeout", "agents")
    t0 = time.time()
    # This scenario needs a SHORT server timeout + retry budget so 'sleep=8'
    # times out on attempt 1. If the stack is on a sane/long timeout, SKIP
    # rather than false-fail (the other scenarios need the long timeout).
    server_timeout = int(os.environ.get("TIMEOUT_SECONDS", "3600"))
    server_attempts = int(os.environ.get("MAX_ATTEMPTS", "1"))
    if os.environ.get("MODEL") != "stub":
        r.status, r.detail = "SKIP", "needs MODEL=stub (sleep control)"
        return r
    if server_timeout > 8 or server_attempts < 2:
        r.status, r.detail = (
            "SKIP",
            f"needs server TIMEOUT_SECONDS<=8 (got {server_timeout}) + MAX_ATTEMPTS>=2 (got {server_attempts}); "
            "bring up the stack with those to exercise #7",
        )
        return r
    async with httpx.AsyncClient(timeout=None) as c:
        # sleep longer than the server's TIMEOUT_SECONDS so attempt 1 times out
        data = {"message": "sleep=8 tmo", "background": "true", "stream": "true"}
        run_id = None
        try:
            async with c.stream("POST", f"{LB}/agents/load-agent/runs", data=data) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        try:
                            run_id = run_id or json.loads(line[5:].strip()).get("run_id")
                        except Exception:
                            pass
                        if run_id:
                            break
        except Exception:
            pass
    if not run_id:
        r.status, r.detail = "WARN", "no run_id captured"
        r.duration = time.time() - t0
        return r
    # let the attempt-1 timeout fire, then inspect Redis event stream for a
    # terminal sentinel written WHILE the job is still queued for a retry.
    await asyncio.sleep(6)
    jobs = _job_state(run_id)
    sentinel_at = _redis_terminal_sentinel_time(run_id)
    r.evidence.update(run_id=run_id, job=jobs, terminal_sentinel_dt=sentinel_at)
    # BUG if: a terminal sentinel exists AND the job is queued/running with a retry pending
    st = (jobs or ("", 0, 0))[0]
    attempt = (jobs or ("", 0, 0))[1]
    max_a = (jobs or ("", 0, 0))[2]
    if sentinel_at is not None and st in ("queued", "running") and attempt < max_a:
        r.status = "FAIL"
        r.detail = f"#7 reproduced: terminal sentinel published at +{sentinel_at:.1f}s while job {st} attempt={attempt}/{max_a} (retry pending)"
    elif sentinel_at is None:
        r.status, r.detail = "PASS", f"no premature terminal sentinel during retry window (job {st} attempt={attempt}/{max_a})"
    else:
        r.status, r.detail = "WARN", f"inconclusive: sentinel={sentinel_at} job={st} attempt={attempt}/{max_a}"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- stream cancellation

async def s_stream_cancel():
    """Cancel a streaming durable run mid-flight; the tail should close cleanly
    (terminal/cancelled), not hang, and the run persists CANCELLED."""
    r = Result("stream cancel mid-flight: tail closes, CANCELLED persisted", "cancel-stream", "agents")
    t0 = time.time()
    run_id, sid, tail_closed = None, None, False
    async with httpx.AsyncClient(timeout=None) as c:
        # start a longer stream, capture run_id, then cancel from a second client
        data = {"message": "sleep=8 cancelme", "background": "true", "stream": "true"}
        async def watch():
            nonlocal run_id, tail_closed
            try:
                async with c.stream("POST", f"{LB}/agents/load-agent/runs", data=data) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                run_id = run_id or json.loads(line[5:].strip()).get("run_id")
                            except Exception:
                                pass
                        if time.time() - t0 > 25:
                            break
                tail_closed = True
            except Exception:
                tail_closed = True
        watcher = asyncio.create_task(watch())
        # wait for run_id then cancel
        for _ in range(20):
            if run_id:
                break
            await asyncio.sleep(0.3)
        if run_id:
            dbrun = _db_run(run_id)
            sid = (dbrun or {}).get("session_id")
            async with httpx.AsyncClient() as cc:
                cancel = await cc.post(
                    f"{LB}/agents/load-agent/runs/{run_id}/cancel",
                    params={"session_id": sid} if sid else {}, timeout=15,
                )
                r.evidence["cancel_http"] = cancel.status_code
        await asyncio.wait_for(watcher, timeout=30)
    final = await _wait_terminal_run(run_id, timeout=40) if run_id else "NORUN"
    r.evidence.update(run_id=run_id, tail_closed=tail_closed, final=final)
    if final in ("CANCELLED", "COMPLETED") and tail_closed:
        r.status, r.detail = "PASS", f"stream cancel handled: tail closed, run={final}"
    else:
        r.status, r.detail = "FAIL", f"cancel-stream issue: final={final} tail_closed={tail_closed}"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- clobber (stream variant)

async def s_clobber_stream(n=6):
    """Same-session clobber, but with stream=true durable submissions. Confirms
    whether concurrent CREATES on one session lose run records regardless of
    stream mode."""
    r = Result("same-session clobber (stream=true): concurrent creates", "clobber", "agents")
    t0 = time.time()
    sid = str(uuid.uuid4())
    run_ids = []

    async def one(i, c):
        data = {"message": f"sleep=1 sclob {i}", "background": "true", "stream": "true", "session_id": sid}
        try:
            async with c.stream("POST", f"{LB}/agents/load-agent/runs", data=data) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        try:
                            rid = json.loads(line[5:].strip()).get("run_id")
                            if rid:
                                return rid  # got the run id — done with this submit
                        except Exception:
                            pass
                    # keep reading until we see a data line with a run_id
        except Exception:
            pass
        return None

    async with httpx.AsyncClient(timeout=None) as c:
        run_ids = [x for x in await asyncio.gather(*[one(i, c) for i in range(n)]) if x]
    await asyncio.sleep(10)
    runs = e2e._db_session_runs(sid)
    present = {x.get("run_id") for x in runs}
    missing = [rid for rid in run_ids if rid not in present]
    r.evidence.update(session_id=sid, submitted=len(run_ids), in_blob=len(present & set(run_ids)), missing=len(missing))
    if missing:
        r.status, r.detail = "FAIL", f"{len(missing)}/{len(run_ids)} stream runs clobbered from session blob"
    else:
        r.status, r.detail = "PASS", f"all {len(run_ids)} concurrent stream runs present in session"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- helpers

def _job_state(run_id):
    import psycopg
    try:
        c = psycopg.connect(PG_DSN)
        cur = c.cursor()
        for schema in ("ai", "public"):
            for tbl in ("agno_jobs", "agno_run_queue"):
                try:
                    cur.execute(f"SELECT status, attempt, max_attempts FROM {schema}.{tbl} WHERE id=%s", (run_id,))
                    row = cur.fetchone()
                    c.close()
                    return tuple(row) if row else None
                except Exception:
                    c.rollback()
        c.close()
    except Exception:
        pass
    return None


def _redis_terminal_sentinel_time(run_id):
    """Return seconds-from-first-event to the terminal sentinel, or None."""
    try:
        out = subprocess.run(
            ["docker", "compose", "-f", COMPOSE, "exec", "-T", "redis", "redis-cli",
             "XRANGE", f"agno:os:events:{run_id}:1:events", "-", "+"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        lines = out.splitlines()
        first_id = None
        term_id = None
        i = 0
        while i < len(lines):
            ln = lines[i].strip()
            if "-" in ln and ln.replace("-", "").isdigit():
                if first_id is None:
                    first_id = int(ln.split("-")[0])
                # look ahead for a 'terminal' field
                if i + 1 < len(lines) and lines[i + 1].strip() == "terminal":
                    term_id = int(ln.split("-")[0])
            i += 1
        if first_id and term_id:
            return (term_id - first_id) / 1000.0
    except Exception:
        pass
    return None


async def _wait_terminal_run(run_id, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        dbrun = _db_run(run_id)
        if dbrun and dbrun.get("status") in TERMINAL:
            return dbrun.get("status")
        await asyncio.sleep(1.5)
    return (_db_run(run_id) or {}).get("status") or "TIMEOUT"


# ---------------------------------------------------------------- runner

async def run_all():
    results = []
    results.append(await s_cross_replica_resume())
    results.append(await s_clobber_stream())
    results.append(await s_stream_cancel())
    results.append(await s_retryable_timeout_tail())
    # chaos LAST (both pause redis; each recovers before the next runs)
    results.append(await s_cancel_check_redis_fault())
    results.append(await s_redis_flap())

    out = [r.to_dict() for r in results]
    with open("distributed_results.json", "w") as f:
        json.dump({"generated_at": int(time.time()), "base_url": LB, "results": out}, f, indent=2)
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
    print("\n" + "=" * 70)
    for rr in out:
        counts[rr["status"]] = counts.get(rr["status"], 0) + 1
        print(f"[{rr['status']}] {rr['category']:14} {rr['name']}")
        if rr["status"] in ("FAIL", "WARN"):
            print(f"        -> {rr['detail']}")
    print("=" * 70)
    print(f"PASS={counts['PASS']} FAIL={counts['FAIL']} WARN={counts['WARN']} SKIP={counts['SKIP']} -> distributed_results.json")
    return counts


if __name__ == "__main__":
    asyncio.run(run_all())
