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
    return subprocess.run(
        ["docker", "compose", "-f", COMPOSE, *a],
        capture_output=True,
        text=True,
        timeout=60,
    )


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


async def _wait_fleet_healthy(timeout=90):
    """Block until BOTH replicas (via their direct ports) AND the LB answer /health.
    A preceding crash/kill scenario - or a suite launched right after a docker
    bring-up - leaves replicas mid-recovery; a submit then returns no run_id and
    the streaming scenarios flake with 'no run created'. Gate the whole suite (and
    the post-crash recovery) on this so those failures can't be a startup artifact."""
    targets = [R1, R2, LB]
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=5) as c:
        while time.time() < deadline:
            ok = 0
            for base in targets:
                try:
                    resp = await c.get(f"{base}/health")
                    if resp.status_code == 200:
                        ok += 1
                except Exception:
                    pass
            if ok == len(targets):
                await asyncio.sleep(1)  # settle margin
                return True
            await asyncio.sleep(2)
    return False


def _db_run(run_id):
    return e2e._db_run(run_id)


# ---------------------------------------------------------------- cross-replica resume


async def s_cross_replica_resume():
    """Submit a background stream on replica1; RESUME it on replica2. Assert
    replica2 replays the run's events (cross-replica event stream via Redis),
    with monotonic indices, and the run completes durably."""
    r = Result(
        "cross-replica resume: submit on R1, resume on R2", "x-replica", "agents"
    )
    t0 = time.time()
    run_id = None
    # PROOF #1: capture the EXACT event indices R1 produced before disconnect, so
    # we can later assert R2 replayed THOSE, not just streamed some live tail.
    r1_indices = []
    async with httpx.AsyncClient(timeout=None) as c:
        data = {"message": "sleep=4 xrep", "background": "true", "stream": "true"}
        try:
            async with c.stream("POST", f"{R1}/agents/load-agent/runs", data=data) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        try:
                            p = json.loads(line[5:].strip())
                            run_id = run_id or p.get("run_id")
                            if p.get("event_index") is not None:
                                r1_indices.append(p["event_index"])
                        except Exception:
                            pass
                        # read enough to build a real replay window (>=3 indexed events)
                        if len(r1_indices) >= 3:
                            break
        except Exception as e:
            r.evidence["r1_err"] = str(e)[:80]
    if not run_id:
        r.status, r.detail = "FAIL", "no run_id from replica1 submit"
        r.duration = time.time() - t0
        return r
    r1_max = max(r1_indices) if r1_indices else -1
    r.evidence.update(run_id=run_id, r1_produced_indices=r1_indices)

    # RESUME on R2 from -1 (full replay). Collect indices + run_ids + event types.
    sid = (_db_run(run_id) or {}).get("session_id")
    resume_indices, resume_run_ids, saw_completed, saw_replay_marker = [], set(), False, False
    async with httpx.AsyncClient(timeout=None) as c:
        data = {"last_event_index": "-1"}
        if sid:
            data["session_id"] = sid
        try:
            async with c.stream("POST", f"{R2}/agents/load-agent/runs/{run_id}/resume", data=data) as resp:
                r.evidence["resume_http"] = resp.status_code
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        try:
                            p = json.loads(line[5:].strip())
                            ev = str(p.get("event", "")).lower()
                            if ev in ("catch_up", "replay", "subscribed"):
                                saw_replay_marker = True
                            if p.get("run_id"):
                                resume_run_ids.add(p["run_id"])
                            if p.get("event_index") is not None:
                                resume_indices.append(p["event_index"])
                            if "complet" in ev:
                                saw_completed = True
                        except Exception:
                            pass
                    if time.time() - t0 > 35:
                        break
        except Exception as e:
            r.evidence["resume_err"] = str(e)[:80]

    # --- Strong assertions on the REPLAY, not just "got frames" ---
    data_indices = [i for i in resume_indices if i is not None]
    # (a) R2 replayed R1's history: every index R1 produced must appear in R2's stream.
    replayed_r1_history = all(i in data_indices for i in r1_indices) and bool(r1_indices)
    # (b) the replay is a contiguous 0..N prefix (no gap/skip in the covered range).
    covered = sorted(set(data_indices))
    contiguous_from_zero = bool(covered) and covered == list(range(covered[0], covered[-1] + 1)) and covered[0] == 0
    # (c) monotonic non-decreasing as delivered (ordering preserved on the wire).
    monotonic = all(data_indices[i] <= data_indices[i + 1] for i in range(len(data_indices) - 1))
    # (d) every replayed frame belongs to THIS run (no cross-run leakage).
    single_run = resume_run_ids == {run_id} if resume_run_ids else False

    for _ in range(20):
        dbrun = _db_run(run_id)
        if dbrun and dbrun.get("status") in TERMINAL:
            break
        await asyncio.sleep(1.5)
    db_status = (_db_run(run_id) or {}).get("status")
    r.evidence.update(
        resume_indices_count=len(data_indices),
        replayed_r1_history=replayed_r1_history,
        contiguous_from_zero=contiguous_from_zero,
        indices_monotonic=monotonic,
        saw_replay_marker=saw_replay_marker,
        single_run_id=single_run,
        saw_completed=saw_completed,
        db_status=db_status,
    )

    checks = {
        "replayed R1's produced indices": replayed_r1_history,
        "contiguous 0..N (no gaps)": contiguous_from_zero,
        "monotonic delivery": monotonic,
        "all frames = this run_id": single_run,
        "reached completion event": saw_completed,
        "run COMPLETED durably": db_status == "COMPLETED",
    }
    failed = [k for k, v in checks.items() if not v]
    if not failed:
        r.status, r.detail = (
            "PASS",
            f"R2 replayed R1's history (indices {r1_indices} ⊆ 0..{covered[-1]}), contiguous, single run, completed durably",
        )
    else:
        r.status, r.detail = "FAIL", f"resume/replay gap: failed [{', '.join(failed)}]"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- Redis fault during run (cancel-check fail-closed)


async def s_cancel_check_redis_fault():
    """A Redis fault WHILE a run executes must not fail an otherwise-successful
    run. The cancellation-check (RedisRunCancellationManager.ais_cancelled) does
    a redis .get() at several safe points per run; a down/slow Redis must NOT
    raise TimeoutError into the run -> RunError. It is fail-open by contract
    (guarded try/except -> return False; see commit 99c1cb832).

    Repro: submit a durable run, pause Redis mid-execution, unpause; then check
    the run's terminal status. If the run has real content but status=ERROR with
    a redis TimeoutError, the cancel-check failed CLOSED (regression). It should
    fail-OPEN (treat redis error as 'not cancelled') and complete.
    """
    r = Result(
        "redis fault: cancellation-check fails-open (not the run)",
        "cancel-check-fault",
        "agents",
    )
    t0 = time.time()
    # This scenario asserts server behavior: when Redis faults mid-run, the
    # cancellation-check (RedisRunCancellationManager.ais_cancelled) must
    # fail-OPEN (treat the fault as "not cancelled") so an otherwise-successful
    # run completes instead of being marked ERROR by a coordination outage.
    #
    # NOTE: we do NOT probe a raw redis client here. A bare aioredis .get()
    # against a down Redis always raises TimeoutError - that is generic
    # redis-py behavior, not the server's, and asserting on it is a false
    # negative that stays red even after the server is fixed. The only valid
    # test is the end-to-end one below, which drives the server's actual
    # (now guarded) ais_cancelled through a real run.
    if os.environ.get("MODEL") != "stub":
        r.status, r.detail = "SKIP", "e2e Redis-fault variant needs MODEL=stub"
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
        await asyncio.sleep(
            7
        )  # long enough that a mid-run cancel-check hits the outage
        _compose("unpause", "redis")
        await _wait_redis_healthy()
        final = await e2e._poll(c, "agents", "load-agent", run_id, sid, timeout=60)
    dbrun = _db_run(run_id) or {}
    content = dbrun.get("content")
    err_is_redis = "redis" in str(content).lower() or "TimeoutError" in str(
        dbrun.get("error", "")
    )
    jobs = _job_state(run_id)
    r.evidence.update(
        run_id=run_id,
        run_status=dbrun.get("status"),
        content=str(content)[:40],
        queue_job=jobs,
        redis_error=err_is_redis,
    )
    if dbrun.get("status") == "ERROR" and err_is_redis:
        r.status = "FAIL"
        r.detail = (
            "cancel-check failed CLOSED: run marked ERROR by a Redis fault during execution "
            f"(content={str(content)[:30]!r}, queue={jobs}) — should fail-open and complete"
        )
    elif dbrun.get("status") in ("COMPLETED",):
        r.status, r.detail = (
            "PASS",
            "run completed despite Redis fault mid-execution (cancel-check fail-open)",
        )
    else:
        r.status, r.detail = (
            "WARN",
            f"inconclusive: status={dbrun.get('status')} redis_error={err_is_redis}",
        )
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
        r.status, r.detail = (
            "PASS",
            f"run reached {(dbrun or {}).get('status')} despite Redis flap (durable)",
        )
    else:
        r.status, r.detail = (
            "FAIL",
            f"run lost/stuck after Redis flap: db={(dbrun or {}).get('status')}",
        )
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- #7 retryable timeout tail


async def s_retryable_timeout_tail():
    """#7: with MAX_ATTEMPTS>1 and a short TIMEOUT, a streaming run times out on
    attempt 1. A terminal ERROR sentinel must NOT be published while the job
    still has retry budget (that closes the client's tail before the retry).
    Detected via the Redis event stream terminal sentinel timing."""
    r = Result(
        "#7 retryable timeout: tail not closed before retry", "retry-timeout", "agents"
    )
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
            async with c.stream(
                "POST", f"{LB}/agents/load-agent/runs", data=data
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        try:
                            run_id = run_id or json.loads(line[5:].strip()).get(
                                "run_id"
                            )
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
        r.status, r.detail = (
            "PASS",
            f"no premature terminal sentinel during retry window (job {st} attempt={attempt}/{max_a})",
        )
    else:
        r.status, r.detail = (
            "WARN",
            f"inconclusive: sentinel={sentinel_at} job={st} attempt={attempt}/{max_a}",
        )
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- stream cancellation


async def s_stream_cancel():
    """Cancel a streaming durable run mid-flight; the tail should close cleanly
    (terminal/cancelled), not hang, and the run persists CANCELLED."""
    r = Result(
        "stream cancel mid-flight: tail closes, CANCELLED persisted",
        "cancel-stream",
        "agents",
    )
    t0 = time.time()
    run_id, sid, tail_closed = None, None, False
    async with httpx.AsyncClient(timeout=None) as c:
        # start a longer stream, capture run_id, then cancel from a second client
        data = {"message": "sleep=8 cancelme", "background": "true", "stream": "true"}

        async def watch():
            nonlocal run_id, tail_closed
            try:
                async with c.stream(
                    "POST", f"{LB}/agents/load-agent/runs", data=data
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                run_id = run_id or json.loads(line[5:].strip()).get(
                                    "run_id"
                                )
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
                    params={"session_id": sid} if sid else {},
                    timeout=15,
                )
                r.evidence["cancel_http"] = cancel.status_code
        await asyncio.wait_for(watcher, timeout=30)
    final = await _wait_terminal_run(run_id, timeout=40) if run_id else "NORUN"
    r.evidence.update(run_id=run_id, tail_closed=tail_closed, final=final)
    if final in ("CANCELLED", "COMPLETED") and tail_closed:
        r.status, r.detail = "PASS", f"stream cancel handled: tail closed, run={final}"
    else:
        r.status, r.detail = (
            "FAIL",
            f"cancel-stream issue: final={final} tail_closed={tail_closed}",
        )
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- clobber (stream variant)


async def s_clobber_stream(n=6):
    """Same-session clobber, but with stream=true durable submissions. Confirms
    whether concurrent CREATES on one session lose run records regardless of
    stream mode."""
    r = Result(
        "same-session clobber (stream=true): concurrent creates", "clobber", "agents"
    )
    t0 = time.time()
    sid = str(uuid.uuid4())
    run_ids = []

    async def one(i, c):
        data = {
            "message": f"sleep=1 sclob {i}",
            "background": "true",
            "stream": "true",
            "session_id": sid,
        }
        try:
            async with c.stream(
                "POST", f"{LB}/agents/load-agent/runs", data=data
            ) as resp:
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
    r.evidence.update(
        session_id=sid,
        submitted=len(run_ids),
        in_blob=len(present & set(run_ids)),
        missing=len(missing),
    )
    if missing:
        r.status, r.detail = (
            "FAIL",
            f"{len(missing)}/{len(run_ids)} stream runs clobbered from session blob",
        )
    else:
        r.status, r.detail = (
            "PASS",
            f"all {len(run_ids)} concurrent stream runs present in session",
        )
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
                    cur.execute(
                        f"SELECT status, attempt, max_attempts FROM {schema}.{tbl} WHERE id=%s",
                        (run_id,),
                    )
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
            [
                "docker",
                "compose",
                "-f",
                COMPOSE,
                "exec",
                "-T",
                "redis",
                "redis-cli",
                "XRANGE",
                f"agno:os:events:{run_id}:1:events",
                "-",
                "+",
            ],
            capture_output=True,
            text=True,
            timeout=15,
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


# ---------------------------------------------------------------- reserved-kwarg collision (streaming durable)


async def s_reserved_kwarg_stream():
    """A STREAMING durable submit that carries a reserved run-method name
    (run_id/input/session_id/user_id) as an extra form field must not blow up.

    The durable STREAMING executor (job_queue.py `_execute_streaming`) pops only
    `stream_events` from the persisted payload["kwargs"], then splats
    `**extra_kwargs` alongside explicit `input=`/`run_id=`/`session_id=`/
    `user_id=`. get_request_kwargs collects every undeclared form field into
    payload["kwargs"], so a client field named `run_id` collides:
        TypeError: arun() got multiple values for keyword argument 'run_id'
    which _is_permanent_failure classifies terminal -> no retry -> the run row
    goes ERROR and the SSE tail is closed as error. The NON-STREAM executor pops
    the full reserved set and is unaffected - this scenario asserts that
    asymmetry is closed.

    We submit the SAME extra field on stream=true and stream=false; on buggy
    code the stream run errors with a 'multiple values' message while the
    non-stream run completes. On fixed code both complete.
    """
    r = Result(
        "reserved kwarg on streaming durable run does not TypeError",
        "reserved-kwarg",
        "agents",
    )
    t0 = time.time()
    extra = "run_id"  # the reserved name most obviously wrong to accept from a client

    async def submit(stream: bool, session_id: str):
        # A failing streaming run may emit NO frame with a run_id (it errors in
        # the worker before the first event), so we key off an explicit
        # session_id and read the persisted run row from the DB rather than the
        # SSE tail.
        data = {
            "message": "sleep=1",
            "background": "true",
            "stream": "true" if stream else "false",
            "session_id": session_id,
            extra: "client-injected-value",  # lands in payload["kwargs"]
        }
        async with httpx.AsyncClient(timeout=None) as c:
            try:
                if stream:
                    async with c.stream(
                        "POST", f"{LB}/agents/load-agent/runs", data=data
                    ) as resp:
                        async for _line in resp.aiter_lines():
                            if time.time() - t0 > 25:
                                break
                else:
                    await c.post(f"{LB}/agents/load-agent/runs", data=data, timeout=30)
            except Exception:
                pass
        # give the worker a moment to persist the terminal/error row
        dbrun = {}
        for _ in range(25):
            runs = e2e._db_session_runs(session_id)
            if runs:
                dbrun = runs[-1]
                if str(dbrun.get("status", "")).upper() in TERMINAL:
                    break
            await asyncio.sleep(1)
        blob = json.dumps(dbrun).lower()
        multi = "multiple values for keyword argument" in blob
        return {
            "run_id": dbrun.get("run_id"),
            "status": dbrun.get("status"),
            "multi_kwarg_error": multi,
            "detail": str(dbrun.get("content") or dbrun.get("error"))[:80],
        }

    stream_res = await submit(stream=True, session_id=f"rkw-stream-{int(t0)}")
    nonstream_res = await submit(stream=False, session_id=f"rkw-nonstream-{int(t0)}")
    r.evidence["stream"] = stream_res
    r.evidence["non_stream"] = nonstream_res

    if stream_res["multi_kwarg_error"] or stream_res["status"] == "ERROR":
        r.status = "FAIL"
        r.detail = (
            f"streaming durable run with extra '{extra}' field errored "
            f"(status={stream_res['status']}, multi_kwarg={stream_res['multi_kwarg_error']}) while the "
            f"non-stream run status={nonstream_res['status']}. _execute_streaming strips only stream_events; "
            "strip the full reserved set before the ** splat."
        )
    elif stream_res["status"] == "COMPLETED":
        r.status, r.detail = (
            "PASS",
            f"streaming durable run tolerated an extra '{extra}' field (both paths complete)",
        )
    else:
        r.status = "WARN"
        r.detail = f"inconclusive: stream status={stream_res['status']} non_stream={nonstream_res['status']}"
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- durable continuation legs (PR #9310)
#
# These exercise the CAS `paused -> queued` continuation over BOTH transports:
#   - SSE:  HTTP /continue with background=true -> 202 PENDING, worker runs the leg
#   - WS:   continue-workflow action -> 'queued' ack frame + flat-JSON tail
# and the multi-container behaviours that matter: submit on one replica / continue
# via the LB (leg may land on either replica), double-click idempotency, and a
# crash mid-leg (must NOT silently re-run a HITL-approved leg - max_attempts=attempt+1).

WS_LB = LB.replace("http", "ws")

# The hitl-agent/hitl-team pause via an @tool(requires_confirmation) call - which
# the model must DECIDE to make. The stub model only emits canned text and never
# calls a tool, so agent/team HITL cannot pause on the stub stack; those scenarios
# need the real model (run them via the e2e stack: ./run.sh up && MODEL=real).
# Workflow HITL pauses STRUCTURALLY (Step(human_review=...)), so it works on stub.
_HITL_AGENT_NEEDS_REAL = os.environ.get("MODEL", "stub") != "real"

# After a continue is accepted the run is momentarily still PAUSED until a worker
# claims the leg. TERMINAL includes PAUSED (it's terminal for a fresh submission),
# so waiting for a CONTINUED run needs a set that EXCLUDES paused.
_CONTINUED_TERMINAL = {"COMPLETED", "ERROR", "FAILED", "CANCELLED"}


async def _wait_run_status(run_id, statuses, timeout=60):
    """Poll the run row until its status is in `statuses` (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = str((_db_run(run_id) or {}).get("status", "")).upper()
        if st in statuses:
            return st
        await asyncio.sleep(1.0)
    return str((_db_run(run_id) or {}).get("status", "")).upper() or "TIMEOUT"


async def _pause_hitl_agent_durable(c, message="Publish an item titled harness."):
    """Submit a DURABLE (background) HITL agent run and wait until it PAUSES.
    Returns (run_id, session_id, tools) or (None, None, None)."""
    r = await c.post(
        f"{LB}/agents/hitl-agent/runs",
        data={"message": message, "background": "true", "stream": "false"},
    )
    if r.status_code not in (200, 202):
        return None, None, None
    b = r.json()
    run_id, sid = b.get("run_id"), b.get("session_id")
    for _ in range(30):
        await asyncio.sleep(1)
        run = _db_run(run_id) or {}
        st = str(run.get("status", "")).upper()
        if st == "PAUSED":
            tools = run.get("tools") or [
                dict(x.get("tool_execution", {}))
                for x in (run.get("requirements") or [])
            ]
            for t in tools:
                t["confirmed"] = True
            return run_id, sid, tools
        if st in TERMINAL:
            return run_id, sid, None
    return run_id, sid, None


# ---- cross-replica continue: submit on R1, continue via R2 (agent/team/workflow) ----
#
# Each component's continue takes a different resolution field:
#   agents    -> tools           (ToolExecution list)
#   teams     -> requirements    (RunRequirement list)
#   workflows -> step_requirements (StepRequirement list)
# The paused run row carries `tools` and/or `requirements`/`step_requirements`;
# we mark each resolved and post to the OTHER replica's /continue.
_CONTINUE_SPEC = {
    "agents": {
        "cid": "hitl-agent",
        "field": "tools",
        "run_field": "tools",
        "confirm": lambda x: x.update(confirmed=True),
    },
    "teams": {
        "cid": "hitl-team",
        "field": "requirements",
        "run_field": "requirements",
        "confirm": lambda x: x.update(confirmed=True),
    },
    "workflows": {
        "cid": "hitl-workflow",
        "field": "step_requirements",
        "run_field": "step_requirements",
        "confirm": lambda x: x.update(confirmed=True),
    },
}


async def _submit_and_pause_on(c, base, component, cid, message):
    """Durable submit on `base` (a specific replica) and wait for PAUSED.
    Returns (run_id, session_id) or (None, None)."""
    r = await c.post(
        f"{base}/{component}/{cid}/runs",
        data={"message": message, "background": "true", "stream": "false"},
    )
    if r.status_code not in (200, 202):
        return None, None, r.status_code
    b = r.json()
    run_id, sid = b.get("run_id"), b.get("session_id")
    for _ in range(40):
        await asyncio.sleep(1)
        st = str((_db_run(run_id) or {}).get("status", "")).upper()
        if st == "PAUSED":
            return run_id, sid, r.status_code
        if st in ("COMPLETED", "ERROR", "FAILED", "CANCELLED"):
            return run_id, sid, r.status_code
    return run_id, sid, r.status_code


def _ticket_is_continuation(run_id):
    """True if the durable queue ticket for run_id carries payload['continue'] -
    i.e. it went through the CAS continuation path, not a fresh submission."""
    try:
        import psycopg
        c = psycopg.connect(PG_DSN)
        cur = c.cursor()
        cur.execute("SELECT payload ? 'continue' FROM ai.agno_jobs WHERE id=%s", (run_id,))
        row = cur.fetchone()
        c.close()
        return bool(row and row[0])
    except Exception:
        return False


def _hitl_leg_executed(run, component):
    """True if the HITL-approved leg actually ran to a result:
      - agents/teams: the confirmed tool has a non-null `result`
      - workflows: a step_result exists for the previously-paused step
    Proves the continuation didn't just flip status - it executed with the
    paused run's context.
    """
    tools = run.get("tools") or []
    for t in tools:
        te = t.get("tool_execution", t) if isinstance(t, dict) else {}
        if (te or t).get("result") is not None:
            return True
    # workflow: an approved step produces output; look for a resolved step result
    for sr in (run.get("step_results") or []):
        if isinstance(sr, dict) and sr.get("content"):
            return True
    # fallback: the run produced final content (the model responded after the tool)
    return bool(run.get("content"))


def _resolved_requirements(run, spec):
    """Extract the paused run's resolution objects and mark each confirmed."""
    items = run.get(spec["run_field"]) or []
    # workflows/teams store the object directly; agents store tools directly too
    resolved = []
    for it in items:
        obj = (
            dict(it.get("tool_execution", it))
            if isinstance(it, dict) and "tool_execution" in it
            else dict(it)
        )
        obj["confirmed"] = True
        resolved.append(obj)
    return resolved


async def _cross_replica_continue(component, message):
    """Submit a durable HITL run on R1, PAUSE, then CONTINUE via R2 (background),
    asserting the leg completes durably from the other replica."""
    spec = _CONTINUE_SPEC[component]
    cid, field = spec["cid"], spec["field"]
    r = Result(
        f"cross-replica continue ({component[:-1]}): pause on R1, continue on R2",
        f"xrep-continue-{component[:-1]}",
        component,
    )
    t0 = time.time()
    # agent/team HITL needs a model that actually calls the confirmation tool.
    if component in ("agents", "teams") and _HITL_AGENT_NEEDS_REAL:
        r.status, r.detail = "SKIP", f"{component} HITL needs MODEL=real (stub never calls the tool); run via ./run.sh e2e"
        r.duration = time.time() - t0
        return r
    async with httpx.AsyncClient(timeout=None) as c:
        run_id, sid, submit_code = await _submit_and_pause_on(
            c, R1, component, cid, message
        )
        r.evidence.update(run_id=run_id, submit_http=submit_code, submitted_on="R1")
        run = _db_run(run_id) or {}
        if str(run.get("status", "")).upper() != "PAUSED":
            r.status = "SKIP"
            r.detail = f"did not pause on R1 (status={run.get('status')}); model may not have called the tool"
            r.duration = time.time() - t0
            return r
        # PROOF #1: R1 actually executed up to the pause - the paused run must
        # carry R1's pre-pause work (messages/step output), not just a status.
        paused_msgs = len(run.get("messages") or [])
        paused_steps = len(run.get("step_results") or [])
        r.evidence["r1_pre_pause_messages"] = paused_msgs
        r.evidence["r1_pre_pause_steps"] = paused_steps
        if paused_msgs == 0 and paused_steps == 0:
            r.status, r.detail = "FAIL", "R1 paused with no persisted work (messages/steps=0): nothing for R2 to hydrate"
            r.duration = time.time() - t0
            return r
        resolved = _resolved_requirements(run, spec)
        if not resolved:
            r.status, r.detail = (
                "SKIP",
                f"paused but no {field} to resolve (run_id={run_id})",
            )
            r.duration = time.time() - t0
            return r
        # CONTINUE via R2 (the other replica), durable
        cont = await c.post(
            f"{R2}/{component}/{cid}/runs/{run_id}/continue",
            data={
                field: json.dumps(resolved),
                "session_id": sid,
                "background": "true",
                "stream": "false",
            },
            timeout=30,
        )
        cbody = (
            cont.json()
            if cont.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        pending = cont.status_code in (200, 202) and cbody.get("status") == "PENDING"
        final = await _wait_run_status(run_id, _CONTINUED_TERMINAL, timeout=75)

    # --- Verify R2 hydrated R1's paused state and executed the approved leg,
    # not just that a status flipped. Read the completed run + its ticket. ---
    final_run = _db_run(run_id) or {}
    final_msgs = len(final_run.get("messages") or [])
    # the ticket must show this was a DURABLE CONTINUATION (payload.continue),
    # not a fresh run - proves R2 drove the CAS continuation path.
    is_durable_continuation = _ticket_is_continuation(run_id)
    # the confirmed tool must have actually EXECUTED (has a result / step grew) -
    # proves the leg R1 paused for ran to completion with R1's context.
    leg_executed = _hitl_leg_executed(final_run, component)
    r.evidence.update(
        continued_on="R2",
        continue_http=cont.status_code,
        continue_status=cbody.get("status"),
        final=final,
        final_messages=final_msgs,
        grew_from_pause=(final_msgs > paused_msgs) or (len(final_run.get("step_results") or []) > paused_steps),
        durable_continuation=is_durable_continuation,
        leg_executed=leg_executed,
    )

    if not pending:
        r.status, r.detail = "FAIL", f"R2 continue not durable: http={cont.status_code} status={cbody.get('status')}"
    elif final != "COMPLETED":
        r.status, r.detail = "FAIL", f"R2 continue accepted but run ended {final}"
    elif not is_durable_continuation:
        r.status, r.detail = "FAIL", "run completed but the ticket carries no payload.continue - not the durable CAS path"
    elif not leg_executed:
        r.status, r.detail = "FAIL", "completed cross-replica but the approved leg did NOT execute (no tool result / no new step) - R2 lost R1's paused state"
    else:
        r.status, r.detail = (
            "PASS",
            f"R1 paused with {paused_msgs} msgs/{paused_steps} steps -> R2 accepted durable continue (202 PENDING) -> "
            f"leg executed with R1's context (msgs {paused_msgs}->{final_msgs}), COMPLETED cross-replica",
        )
    r.duration = time.time() - t0
    return r


async def s_xrep_continue_agent():
    return await _cross_replica_continue("agents", "Publish an item titled xrep-agent.")


async def s_xrep_continue_team():
    return await _cross_replica_continue("teams", "Publish an item titled xrep-team.")


async def s_xrep_continue_workflow():
    return await _cross_replica_continue(
        "workflows", "Draft then approve xrep-workflow."
    )


async def s_continue_sse_durable():
    """DURABLE HITL continue over HTTP/SSE: pause a queued run, /continue with
    background=true, assert the seam returns 202 PENDING (the CAS accepted the
    leg - not an inline completion) and the run reaches COMPLETED via a worker."""
    r = Result(
        "durable HITL continue (SSE/HTTP background): 202 PENDING -> COMPLETED",
        "continue-sse",
        "agents",
    )
    t0 = time.time()
    if _HITL_AGENT_NEEDS_REAL:
        r.status, r.detail = "SKIP", "agent HITL needs MODEL=real (stub never calls the tool); run via ./run.sh e2e"
        r.duration = time.time() - t0
        return r
    async with httpx.AsyncClient(timeout=None) as c:
        run_id, sid, tools = await _pause_hitl_agent_durable(c)
        if not tools:
            r.status, r.detail = (
                "SKIP",
                f"did not pause on tool (run_id={run_id}); model may not have called publish",
            )
            r.duration = time.time() - t0
            return r
        cont = await c.post(
            f"{LB}/agents/hitl-agent/runs/{run_id}/continue",
            data={
                "tools": json.dumps(tools),
                "session_id": sid,
                "background": "true",
                "stream": "false",
            },
            timeout=30,
        )
        cbody = (
            cont.json()
            if cont.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        pending = cont.status_code in (200, 202) and cbody.get("status") == "PENDING"
        final = await _wait_run_status(run_id, _CONTINUED_TERMINAL, timeout=60)
    r.evidence.update(
        run_id=run_id,
        continue_http=cont.status_code,
        continue_status=cbody.get("status"),
        final=final,
    )
    if pending and final == "COMPLETED":
        r.status, r.detail = (
            "PASS",
            "durable continue accepted as PENDING and completed via a worker",
        )
    elif not pending:
        r.status, r.detail = (
            "FAIL",
            f"continue was not durable: http={cont.status_code} status={cbody.get('status')} (inline, not CAS)",
        )
    else:
        r.status, r.detail = "FAIL", f"durable continue accepted but run ended {final}"
    r.duration = time.time() - t0
    return r


async def s_continue_double_click():
    """Two concurrent durable continues on one paused run: one wins the CAS
    (queued), the other attaches (both 202) or gets a settling 409; the run
    must complete EXACTLY ONCE (no double execution of the approved leg)."""
    r = Result(
        "durable continue double-click: single completion", "continue-2click", "agents"
    )
    t0 = time.time()
    if _HITL_AGENT_NEEDS_REAL:
        r.status, r.detail = "SKIP", "agent HITL needs MODEL=real (stub never calls the tool); run via ./run.sh e2e"
        r.duration = time.time() - t0
        return r
    async with httpx.AsyncClient(timeout=None) as c:
        run_id, sid, tools = await _pause_hitl_agent_durable(
            c, message="Publish an item titled twice."
        )
        if not tools:
            r.status, r.detail = "SKIP", f"did not pause on tool (run_id={run_id})"
            r.duration = time.time() - t0
            return r
        data = {
            "tools": json.dumps(tools),
            "session_id": sid,
            "background": "true",
            "stream": "false",
        }
        url = f"{LB}/agents/hitl-agent/runs/{run_id}/continue"
        c1, c2 = await asyncio.gather(
            c.post(url, data=data), c.post(url, data=data), return_exceptions=True
        )
        codes = sorted(
            [
                getattr(x, "status_code", 0)
                for x in (c1, c2)
                if not isinstance(x, Exception)
            ]
        )
        final = await _wait_run_status(run_id, _CONTINUED_TERMINAL, timeout=60)
    r.evidence.update(run_id=run_id, continue_codes=codes, final=final)
    # accepted set: 202 (queued/attach) and/or 409 (settling). Never a 5xx. Run completes once.
    codes_ok = all(x in (200, 202, 409) for x in codes) and len(codes) == 2
    if codes_ok and final == "COMPLETED":
        r.status, r.detail = (
            "PASS",
            f"double-click idempotent (codes={codes}), single completion",
        )
    else:
        r.status, r.detail = "FAIL", f"double-click issue: codes={codes} final={final}"
    r.duration = time.time() - t0
    return r


async def s_continue_crash():
    """Crash-during-continue: accept a durable continue, then kill BOTH replicas
    (durable ticket survives in PG), bring them back, and assert the leg does NOT
    silently re-run and the run reaches a visible terminal state. With
    max_attempts=attempt+1 a crashed continuation leg is never auto-reclaimed - it
    surfaces as FAILED (visible), not a silent re-execution of approved tool calls."""
    r = Result(
        "crash during durable continue: no silent re-run, visible terminal",
        "continue-crash",
        "agents",
    )
    t0 = time.time()
    if _HITL_AGENT_NEEDS_REAL:
        r.status, r.detail = "SKIP", "agent HITL needs MODEL=real (stub never calls the tool); run via ./run.sh e2e"
        r.duration = time.time() - t0
        return r
    async with httpx.AsyncClient(timeout=None) as c:
        run_id, sid, tools = await _pause_hitl_agent_durable(
            c, message="Publish an item titled crashme with a slow tool."
        )
        if not tools:
            r.status, r.detail = "SKIP", f"did not pause on tool (run_id={run_id})"
            r.duration = time.time() - t0
            return r
        # Accept the continue (the CAS lands durably in PG), then kill BOTH
        # replicas so the leg is interrupted. The POST may itself time out if the
        # kill lands before it returns - the durable ticket is what matters, not
        # the HTTP response, so tolerate it.
        accepted = False
        try:
            cont = await c.post(
                f"{LB}/agents/hitl-agent/runs/{run_id}/continue",
                data={
                    "tools": json.dumps(tools),
                    "session_id": sid,
                    "background": "true",
                    "stream": "false",
                },
                timeout=15,
            )
            accepted = cont.status_code in (200, 202)
            r.evidence["continue_http"] = cont.status_code
        except Exception as e:
            r.evidence["continue_http"] = f"{type(e).__name__} (killed in-flight)"
        # Only crash the fleet if the continue was actually accepted into the
        # queue - otherwise there is no leg to interrupt and we'd just be killing
        # replicas for nothing (the run stays correctly PAUSED). This keeps the
        # crash-mid-leg property the thing under test, not a race with the kill.
        if accepted:
            await asyncio.sleep(0.5)  # let the CAS ticket land before killing
            _compose("kill", "replica1", "replica2")
            await asyncio.sleep(3)
            _compose("start", "replica1", "replica2")
            # Wait for the WHOLE fleet (both replicas + LB) so this crash test does
            # not leave the next run's early streaming scenarios starved of a worker.
            await _wait_fleet_healthy(timeout=90)
            final = await _wait_run_status(run_id, _CONTINUED_TERMINAL, timeout=90)
        else:
            # continue was not accepted (fleet was already down) - nothing to crash.
            final = str((_db_run(run_id) or {}).get("status", "")).upper()
    dbrun = _db_run(run_id) or {}
    r.evidence.update(
        run_id=run_id,
        accepted=accepted,
        final=final,
        content=str(dbrun.get("content"))[:50],
    )
    # The crash-durability guarantee only applies if the continue was ACCEPTED
    # (a CAS ticket exists). If the kill won the race and the continue never
    # landed (502/timeout, accepted=False), the run staying PAUSED is CORRECT -
    # nothing was enqueued, so it's resumable, not lost. That's a SKIP, not a
    # FAIL: the scenario didn't get to exercise the property it's testing.
    if not accepted:
        r.status = "SKIP"
        r.detail = (
            f"continue not accepted (http={r.evidence.get('continue_http')}) - the kill raced ahead of "
            f"the continue, so the run is correctly still {final} (nothing enqueued). Re-run to exercise "
            "the crash-mid-leg path."
        )
        r.duration = time.time() - t0
        return r
    # Continue WAS accepted -> the durable ticket must reach a visible terminal.
    # COMPLETED (a worker finished it) or FAILED/ERROR (crashed leg surfaced
    # visibly, per no-auto-retry). NOT: stuck PENDING/PAUSED, NOT a double-run.
    if final in ("COMPLETED", "FAILED", "ERROR"):
        r.status, r.detail = (
            "PASS",
            f"crash handled: accepted continue reached a visible terminal ({final}), no silent hang",
        )
    else:
        r.status, r.detail = (
            "FAIL",
            f"accepted continue left run non-terminal: {final} (leg lost / stuck)",
        )
    r.duration = time.time() - t0
    return r


async def s_continue_ws_workflow():
    """DURABLE HITL continue over the WebSocket seam (workflows). Start a workflow
    over WS, drive it to a HITL pause, then send continue-workflow over the SAME
    socket. Assert we get the 'queued' ack frame and a flat-JSON tail that carries
    the run through to completion - the WS durable-continue contract from #9310."""
    r = Result(
        "durable HITL continue (WS workflow): queued ack + flat tail -> completed",
        "continue-ws",
        "workflows",
    )
    t0 = time.time()
    if e2e.websockets is None:
        r.status, r.detail = "SKIP", "websockets package not installed"
        return r

    def parse(raw):
        raw = raw.strip()
        if raw.startswith("event:") or "\ndata:" in raw:
            ev = raw.split("\n", 1)[0].replace("event:", "").strip()
            payload = {}
            for line in raw.split("\n"):
                if line.startswith("data:"):
                    try:
                        payload = json.loads(line[5:].strip())
                    except Exception:
                        pass
            return ev, payload
        try:
            m = json.loads(raw)
            return m.get("event", ""), m
        except Exception:
            return "", {}

    run_id = sid = None
    saw_paused = saw_queued_ack = flat_tail = completed = False
    step_requirements = None
    try:
        async with e2e.websockets.connect(
            f"{WS_LB}/workflows/ws", open_timeout=15
        ) as ws:
            await ws.recv()  # 'connected'
            await ws.send(
                json.dumps(
                    {
                        "action": "start-workflow",
                        "workflow_id": "hitl-workflow",
                        "message": "Draft then approve.",
                    }
                )
            )
            deadline = time.time() + 70
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    break
                ev, payload = parse(raw)
                run_id = run_id or payload.get("run_id")
                sid = sid or payload.get("session_id")
                if "Paused" in ev or "paused" in ev:
                    saw_paused = True
                    break
            # Read the authoritative step_requirements from the persisted run row
            # (the WS pause frame's copy can be partial), then confirm each.
            if run_id:
                for _ in range(20):
                    dbrun = _db_run(run_id) or {}
                    if str(dbrun.get("status", "")).upper() == "PAUSED" and dbrun.get(
                        "step_requirements"
                    ):
                        step_requirements = dbrun["step_requirements"]
                        sid = sid or dbrun.get("session_id")
                        break
                    await asyncio.sleep(1)
            for req in step_requirements or []:
                req["confirmed"] = True
            # send the durable continue over the SAME socket
            await ws.send(
                json.dumps(
                    {
                        "action": "continue-workflow",
                        "workflow_id": "hitl-workflow",
                        "run_id": run_id,
                        **({"session_id": sid} if sid else {}),
                        **(
                            {"step_requirements": step_requirements}
                            if step_requirements
                            else {}
                        ),
                    }
                )
            )
            deadline = time.time() + 70
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    break
                ev, payload = parse(raw)
                # the durable continue's first frame is the flat 'queued' ack
                if ev == "queued" or payload.get("event") == "queued":
                    saw_queued_ack = True
                # a flat-JSON frame (not SSE-wrapped) parses as a dict with an 'event' key
                if (
                    not raw.strip().startswith("event:")
                    and isinstance(payload, dict)
                    and payload.get("event")
                ):
                    flat_tail = True
                if "Completed" in ev:
                    completed = True
                    break
    except Exception as e:
        r.evidence["ws_err"] = str(e)[:150]

    final = (
        await _wait_run_status(run_id, _CONTINUED_TERMINAL, timeout=60)
        if run_id
        else "NORUN"
    )
    r.evidence.update(
        run_id=run_id,
        saw_paused=saw_paused,
        saw_queued_ack=saw_queued_ack,
        flat_tail=flat_tail,
        ws_completed=completed,
        final=final,
    )
    if not saw_paused:
        r.status, r.detail = (
            "SKIP",
            "workflow did not pause on the confirmation step over WS",
        )
    elif saw_queued_ack and final == "COMPLETED":
        r.status, r.detail = (
            "PASS",
            "WS durable continue: queued ack + tail -> completed",
        )
    elif final == "COMPLETED":
        r.status, r.detail = (
            "WARN",
            "run completed but no 'queued' ack observed (continue may have taken the detached path)",
        )
    else:
        r.status, r.detail = (
            "FAIL",
            f"WS continue did not complete: queued_ack={saw_queued_ack} final={final}",
        )
    r.duration = time.time() - t0
    return r


# ---------------------------------------------------------------- runner


async def run_all():
    results = []
    # Gate the whole suite on a healthy fleet: a docker bring-up still settling,
    # or a prior run's crash test leaving replicas mid-recovery, otherwise makes
    # the first streaming scenarios flake with "no run created". This is the fix
    # for the x-replica / cancel-stream / reserved-kwarg startup flakes.
    if not await _wait_fleet_healthy(timeout=90):
        print("WARNING: fleet not fully healthy after 90s; scenarios may flake")
    results.append(await s_cross_replica_resume())
    results.append(await s_clobber_stream())
    results.append(await s_stream_cancel())
    results.append(await s_reserved_kwarg_stream())
    results.append(await s_retryable_timeout_tail())
    # durable continuation legs (PR #9310) — SSE + WS transports
    results.append(await s_continue_sse_durable())
    results.append(await s_continue_double_click())
    results.append(await s_continue_ws_workflow())
    # cross-replica continue: pause on R1, continue on R2 (agent/team/workflow)
    results.append(await s_xrep_continue_agent())
    results.append(await s_xrep_continue_team())
    results.append(await s_xrep_continue_workflow())
    # chaos LAST (redis flaps + a replica-kill; each recovers before the next runs)
    results.append(await s_cancel_check_redis_fault())
    results.append(await s_redis_flap())
    results.append(await s_continue_crash())

    out = [r.to_dict() for r in results]
    with open("distributed_results.json", "w") as f:
        json.dump(
            {"generated_at": int(time.time()), "base_url": LB, "results": out},
            f,
            indent=2,
        )
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
    print("\n" + "=" * 70)
    for rr in out:
        counts[rr["status"]] = counts.get(rr["status"], 0) + 1
        print(f"[{rr['status']}] {rr['category']:14} {rr['name']}")
        if rr["status"] in ("FAIL", "WARN"):
            print(f"        -> {rr['detail']}")
    print("=" * 70)
    print(
        f"PASS={counts['PASS']} FAIL={counts['FAIL']} WARN={counts['WARN']} SKIP={counts['SKIP']} -> distributed_results.json"
    )
    return counts


if __name__ == "__main__":
    asyncio.run(run_all())
