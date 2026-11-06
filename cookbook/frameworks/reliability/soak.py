"""Keep two replicas per provider alive for a paced, bounded eight-hour soak.

Run only after verify.py preflight passes. The default schedule submits 78 SDK
turns across nine waves at 1, 4 and 8 concurrent runs per provider, plus six fault
probes. Existing reservations count toward the same hard 200-turn ceiling.
"""

import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import traceback
from datetime import datetime, timezone

from verify import HERE, STATE, Suite, write_json


def now():
    return datetime.now(timezone.utc).isoformat()


def budget():
    with sqlite3.connect(STATE / "ledger.sqlite") as db:
        return db.execute("SELECT count(*) FROM attempts").fetchone()[0]


def record(suite, name, wave):
    started = time.time()
    suite.active_case = None
    try:
        result = {"status": "PASS", "evidence": getattr(suite, "case_" + name)()}
    except Exception:
        result = {"status": "FAIL", "error": traceback.format_exc()}
    finally:
        if suite.active_case:
            suite.release(suite.active_case)
    result.update(
        provider=suite.provider,
        case=name,
        wave=wave,
        started=started,
        elapsed=time.time() - started,
        concurrency=suite.concurrency,
    )
    write_json(suite.directory / f"{name}-{wave}.json", result)
    with (STATE / "results.jsonl").open("a") as output:
        output.write(json.dumps(result, default=str) + "\n")
    print(now(), suite.provider, name, wave, result["status"], flush=True)
    return result["status"] == "PASS"


def snapshot(suites):
    pids = [r.process.pid for s in suites for r in s.replicas.values() if r.process]
    sample = {"at": now(), "reserved_attempts": budget(), "replicas": {}}
    for suite in suites:
        for name, replica in suite.replicas.items():
            try:
                status = suite.client.get(
                    replica.base + "/health", timeout=5
                ).status_code
            except Exception as exc:
                status = type(exc).__name__
            sample["replicas"][suite.provider + "-" + name] = {
                "pid": replica.process.pid,
                "exit_code": replica.process.poll(),
                "health": status,
            }
    # RSS is for API parent processes; this does not measure the whole SDK tree.
    sample["parent_resources"] = subprocess.run(
        ["ps", "-o", "pid=,ppid=,rss=,etime=", "-p", ",".join(map(str, pids))],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    with (STATE / "soak-resources.jsonl").open("a") as output:
        output.write(json.dumps(sample) + "\n")


def main():
    with (STATE / "runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads((STATE / "state.json").read_text())
        if state.get("soak_started_at"):
            raise RuntimeError(
                "Soak already started; inspect evidence rather than starting it again"
            )
        deadline = datetime.fromisoformat(
            state["deadline_utc"].replace("Z", "+00:00")
        ).timestamp()
        suites = []
        failures = 0
        started = time.time()
        end = min(started + 8 * 3600, deadline - 180)
        if end <= started or budget() + 84 > 200:
            raise RuntimeError(
                "Insufficient remaining time or budget for this schedule"
            )
        state.update(
            stage="soak_running",
            runner_pid=os.getpid(),
            soak_started_at=now(),
            soak_planned_end=datetime.fromtimestamp(end, timezone.utc).isoformat(),
        )
        state["fixture_sha256"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in HERE.glob("*.py")
        }
        write_json(STATE / "state.json", state)
        try:
            for provider in ("claude", "codex"):
                suite = Suite(provider, 1, 8, state["deadline_utc"])
                suites.append(suite)
                for replica in suite.replicas.values():
                    replica.start()
            state["soak_suites"] = [str(s.directory) for s in suites]
            write_json(STATE / "state.json", state)
            for suite in suites:
                for case in ("active_reconnect", "tool_error", "retention"):
                    failures += not record(suite, case, "fault-probe")
            # Nine waves span seven hours; the final hour checks quiet replicas.
            schedule = [1, 4, 8] * 3
            interval = max(0, (end - started - 3600) / (len(schedule) - 1))
            for wave, count in enumerate(schedule):
                target = started + wave * interval
                while time.time() < min(target, end):
                    snapshot(suites)
                    time.sleep(max(0, min(60, target - time.time())))
                if time.time() >= end or budget() + count * 2 > 200:
                    break
                for suite in suites:
                    suite.concurrency = count
                    failures += not record(suite, "concurrency", wave)
                snapshot(suites)
            while time.time() < end:
                snapshot(suites)
                time.sleep(max(0, min(60, end - time.time())))
            state["stage"] = "soak_finished"
        except BaseException:
            state["stage"] = "soak_interrupted"
            state["soak_error"] = traceback.format_exc()
            raise
        finally:
            for suite in suites:
                for replica in suite.replicas.values():
                    replica.stop()
                suite.client.close()
                suite.db.db_engine.dispose()
            state.update(
                runner_pid=None,
                soak_finished_at=now(),
                soak_elapsed_seconds=time.time() - started,
                soak_failed_checks=failures,
            )
            state["live_turn_budget"]["reserved_attempts"] = budget()
            write_json(STATE / "state.json", state)
            print(now(), state["stage"], "failed_checks", failures, flush=True)


if __name__ == "__main__":
    main()
