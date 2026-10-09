"""Bounded real-SDK reliability checks against two local isolated replicas.

Run from the repository root with .venvs/claude-dx-validation/bin/python.
The shared ledger reserves every native SDK submission before execution. This
controller never retries a failed test silently; each attempt writes evidence.
Authentication must already be provisioned in the private HARNESS_AUTH_ROOT.
"""

import argparse
import concurrent.futures
import fcntl
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from agno.db.postgres import PostgresDb

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STATE = ROOT / ".context/harness-reliability"
DATABASE_URL = "postgresql+psycopg://harness:harness-local-test@localhost:5543/harness"
REDIS_URL = "redis://localhost:6387"
TERMINAL = {"COMPLETED", "ERROR", "CANCELLED"}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Replica:
    def __init__(self, suite, name):
        self.suite, self.name = suite, name
        self.port = port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.process = None
        self.log = None

    def start(self):
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        auth = (
            Path(env.get("HARNESS_AUTH_ROOT", str(STATE / "auth")))
            / self.suite.provider
            / self.name
        )
        env.update(
            HARNESS_PROVIDER=self.suite.provider,
            HARNESS_REPLICA=self.name,
            HARNESS_WORKSPACE=str(self.suite.directory / self.name / "workspace"),
            HARNESS_DATABASE_URL=DATABASE_URL,
            HARNESS_SCHEMA=self.suite.schema,
            HARNESS_REDIS_URL=REDIS_URL
            + "/"
            + ("1" if self.suite.provider == "claude" else "2"),
            HARNESS_LEDGER=str(STATE / "ledger.sqlite"),
            HARNESS_MAX_ATTEMPTS=str(self.suite.attempts),
            HARNESS_CONCURRENCY=str(self.suite.concurrency),
            HARNESS_DEADLINE_UTC=self.suite.deadline,
            PORT=str(self.port),
        )
        env[
            "CLAUDE_CONFIG_DIR" if self.suite.provider == "claude" else "CODEX_HOME"
        ] = str(auth)
        self.log = (self.suite.directory / f"replica-{self.name}.log").open("a")
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(HERE / "serve.py")],
            cwd=ROOT,
            env=env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        until = time.monotonic() + 40
        while time.monotonic() < until:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Replica {self.name} exited; inspect {self.log.name}"
                )
            try:
                if httpx.get(
                    self.base + "/health", timeout=1, trust_env=False
                ).is_success:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise TimeoutError(f"Replica {self.name} did not become healthy")

    def stop(self, crash=False):
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL if crash else signal.SIGTERM)
            try:
                self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()


class Suite:
    def __init__(self, provider, attempts, concurrency, deadline):
        self.provider, self.attempts, self.concurrency, self.deadline = (
            provider,
            attempts,
            concurrency,
            deadline,
        )
        self.schema = "readiness_" + uuid4().hex[:16]
        self.directory = STATE / f"{provider}-{self.schema}"
        self.directory.mkdir(parents=True)
        self.agent_id = f"readiness-{provider}"
        self.db = PostgresDb(db_url=DATABASE_URL, db_schema=self.schema)
        self.replicas = {name: Replica(self, name) for name in ("a", "b")}
        self.client = httpx.Client(timeout=180, trust_env=False)
        self.active_case = None
        write_json(
            self.directory / "manifest.json",
            {
                "provider": provider,
                "schema": self.schema,
                "attempts": attempts,
                "concurrency": concurrency,
                "source_sha": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "ports": {k: v.port for k, v in self.replicas.items()},
            },
        )

    def request(self, replica, method, path, **kwargs):
        response = self.client.request(
            method, self.replicas[replica].base + path, **kwargs
        )
        response.raise_for_status()
        return response

    @property
    def runs(self):
        return f"/agents/{self.agent_id}/runs"

    def submit(self, prompt, replica="a", session=None, background=True, key=None):
        session = session or str(uuid4())
        start = time.monotonic()
        response = self.request(
            replica,
            "POST",
            self.runs,
            data={
                "message": prompt,
                "session_id": session,
                "background": str(background).lower(),
                "stream": "false",
            },
            headers={"Idempotency-Key": key} if key else {},
        )
        result = response.json()
        assert result.get("run_id"), result
        if background:
            assert response.status_code == 202, (response.status_code, result)
        return result, session, time.monotonic() - start

    def poll(self, run, session, replica="b", timeout=180):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            result = self.request(
                replica, "GET", self.runs + "/" + run, params={"session_id": session}
            ).json()
            if result.get("status") in TERMINAL:
                return result
            time.sleep(0.3)
        raise TimeoutError(f"Run {run} did not settle within {timeout}s")

    def ledger(self, query, params=()):
        with sqlite3.connect(STATE / "ledger.sqlite", timeout=30) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def receipts(self, case):
        return self.ledger(
            "SELECT * FROM receipts WHERE case_id=? ORDER BY id", (case,)
        )

    def wait_receipt(self, case):
        until = time.monotonic() + 60
        while time.monotonic() < until:
            rows = self.receipts(case)
            if rows:
                return rows[0]
            time.sleep(0.2)
        raise TimeoutError(
            "No real MCP receipt arrived; inspect native run and replica logs"
        )

    def release(self, case):
        with sqlite3.connect(STATE / "ledger.sqlite", timeout=30) as db:
            db.execute("INSERT OR REPLACE INTO gates VALUES (?,1)", (case,))

    def tool_prompt(self, case, wait=False):
        return (
            f'Call the fixture checkpoint tool exactly once with case_id="{case}", step="one", '
            f"wait={str(wait).lower()}, fail=false. Do not use other tools. "
            "After it returns, reply with the exact RECEIPT string from its result."
        )

    def assert_tool(self, result, case):
        write_json(self.directory / f"run-{result.get('run_id', case)}.json", result)
        assert result["status"] == "COMPLETED", result
        results = [
            str(t.get("result", ""))
            for t in result.get("tools", [])
            if not t.get("tool_call_error")
        ]
        assert any(f"RECEIPT:{case}:one" in x for x in results), results
        assert self.receipts(case), "Model claimed success without an actual receipt"

    def native_id(self, session):
        stored = self.db.get_session(session_id=session)
        assert stored, session
        key = (
            "claude_sdk_session_id" if self.provider == "claude" else "codex_thread_id"
        )
        return (stored.session_data or {}).get(key)

    def events(self, response):
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line[6:])

    def case_smoke(self):
        case = str(uuid4())
        self.active_case = case
        run, session, latency = self.submit(self.tool_prompt(case), background=False)
        self.assert_tool(run, case)
        return {
            "run": run,
            "session": session,
            "latency": latency,
            "receipts": self.receipts(case),
        }

    def case_background(self):
        case = str(uuid4())
        self.active_case = case
        run, session, latency = self.submit(self.tool_prompt(case, True))
        self.wait_receipt(case)
        assert latency < 5, f"Background acknowledgement took {latency:.2f}s"
        self.release(case)
        final = self.poll(run["run_id"], session)
        self.assert_tool(final, case)
        return {
            "accepted": run,
            "ack_seconds": latency,
            "run": final,
            "receipts": self.receipts(case),
        }

    def case_disconnect(self, reconnect_while_running=False):
        case, session = str(uuid4()), str(uuid4())
        self.active_case = case
        received = []
        with self.client.stream(
            "POST",
            self.replicas["a"].base + self.runs,
            data={
                "message": self.tool_prompt(case, True),
                "session_id": session,
                "background": "true",
                "stream": "true",
            },
        ) as response:
            response.raise_for_status()
            for event in self.events(response):
                received.append(event)
                if event.get("event") == "ToolCallStarted":
                    break
        assert received and received[0].get("run_id"), received
        run = received[0]["run_id"]
        self.wait_receipt(case)
        if not reconnect_while_running:
            self.release(case)
            self.poll(run, session)
        replay = []
        last = max(e.get("event_index", -1) for e in received)
        assert last >= 0, received
        with self.client.stream(
            "POST",
            self.replicas["b"].base + self.runs + f"/{run}/resume",
            data={
                "session_id": session,
                "last_event_index": str(last),
            },
        ) as response:
            response.raise_for_status()
            for event in self.events(response):
                replay.append(event)
                if reconnect_while_running:
                    self.release(case)
        indexed = [e["event_index"] for e in replay if "event_index" in e]
        assert indexed and all(i > last for i in indexed), replay
        assert indexed == sorted(set(indexed)), replay
        assert any(e.get("event") == "RunCompleted" for e in replay), replay
        final = self.poll(run, session)
        self.assert_tool(final, case)
        return {"received": received, "replayed": replay, "run": final}

    def case_live_reconnect(self):
        return self.case_disconnect(reconnect_while_running=True)

    def case_cancel(self):
        case = str(uuid4())
        self.active_case = case
        run, session, _ = self.submit(self.tool_prompt(case, True))
        receipt = self.wait_receipt(case)
        other = "b" if receipt["replica"] == "a" else "a"
        start = time.monotonic()
        self.request(
            other,
            "POST",
            self.runs + f"/{run['run_id']}/cancel",
            params={"session_id": session},
        )
        final = self.poll(run["run_id"], session, replica=other, timeout=25)
        assert final["status"] == "CANCELLED", final
        self.release(case)
        time.sleep(1)
        assert len(self.receipts(case)) == 1, self.receipts(case)
        return {
            "run": final,
            "cancel_seconds": time.monotonic() - start,
            "execution_replica": receipt["replica"],
        }

    def case_active_reconnect(self):
        case = str(uuid4())
        self.active_case = case
        run, session, _ = self.submit(self.tool_prompt(case, True))
        self.wait_receipt(case)
        received = []
        with self.client.stream(
            "POST",
            self.replicas["b"].base + self.runs + f"/{run['run_id']}/resume",
            data={"session_id": session, "last_event_index": "-1"},
        ) as response:
            response.raise_for_status()
            for event in self.events(response):
                received.append(event)
                if event.get("event") == "ToolCallStarted":
                    self.release(case)
        write_json(self.directory / "active-reconnect-events.json", received)
        assert any(e.get("event") == "RunCompleted" for e in received), received
        final = self.poll(run["run_id"], session)
        self.assert_tool(final, case)
        return {"events": received, "run": final}

    def case_tool_error(self):
        case = str(uuid4())
        self.active_case = case
        prompt = self.tool_prompt(case).replace("fail=false", "fail=true")
        prompt += " If it fails, report that failure without retrying."
        result, _, _ = self.submit(prompt, background=False)
        write_json(self.directory / "failed-tool-run.json", result)
        assert self.receipts(case), "Failure must come from the real tool"
        assert any(t.get("tool_call_error") for t in result.get("tools", [])), result
        return {"run": result, "receipts": self.receipts(case)}

    def case_retention(self):
        from redis import Redis

        # Streaming must be requested at submission to create transport events.
        evidence = self.case_disconnect()
        final = run = evidence["run"]
        session = run["session_id"]
        # Expire only this completed run's transport keys; never flush the service.
        redis = Redis.from_url(
            REDIS_URL + ("/1" if self.provider == "claude" else "/2")
        )
        keys = list(redis.scan_iter(f"agno:os:events:{run['run_id']}:*"))
        assert keys, "Expected transport keys before controlled expiration"
        for key in keys:
            redis.expire(key, 1)
        time.sleep(2)
        assert not any(redis.exists(key) for key in keys)
        redis.close()
        with self.client.stream(
            "POST",
            self.replicas["b"].base + self.runs + f"/{run['run_id']}/resume",
            data={"session_id": session, "last_event_index": "-1"},
        ) as response:
            response.raise_for_status()
            events = list(self.events(response))
        write_json(self.directory / "expired-transport-replay.json", events)
        assert any(e.get("event") == "ToolCallCompleted" for e in events), events
        assert any(e.get("event") == "RunCompleted" for e in events), events
        return {"events": events, "run": final}

    def case_session(self):
        fact = "beacon-" + uuid4().hex
        first, session, _ = self.submit(
            f"Remember this test beacon: {fact}. Reply OK. Do not use tools.",
            background=False,
        )
        assert first["status"] == "COMPLETED", first
        before = self.native_id(session)
        second, _, _ = self.submit(
            "What is the test beacon I told you? Reply with just that value. Do not use tools.",
            replica="b",
            session=session,
            background=False,
        )
        assert second["status"] == "COMPLETED" and fact in second["content"], second
        after = self.native_id(session)
        if self.provider == "claude":
            assert before and before == after, (before, after)
        return {
            "first": first,
            "second": second,
            "native_id_before": before,
            "native_id_after": after,
            "native_continuity": before == after,
            "history_recall": True,
        }

    def case_idempotency(self):
        case, key = str(uuid4()), str(uuid4())
        self.active_case = case
        first, session, _ = self.submit(self.tool_prompt(case, True), key=key)
        second, _, _ = self.submit(
            self.tool_prompt(case, True), replica="b", session=session, key=key
        )
        assert first["run_id"] == second["run_id"], (first, second)
        self.wait_receipt(case)
        self.release(case)
        final = self.poll(first["run_id"], session)
        self.assert_tool(final, case)
        assert len(self.receipts(case)) == 1, self.receipts(case)
        return {
            "first": first,
            "duplicate": second,
            "run": final,
            "receipts": self.receipts(case),
        }

    def case_crash(self):
        case = str(uuid4())
        self.active_case = case
        run, session, _ = self.submit(self.tool_prompt(case, True))
        receipt = self.wait_receipt(case)
        dead = self.replicas[receipt["replica"]]
        other = "b" if dead.name == "a" else "a"
        start = time.monotonic()
        dead.stop(crash=True)
        try:
            self.release(case)
            final = self.poll(run["run_id"], session, replica=other, timeout=90)
            expected = "ERROR" if self.attempts == 1 else "COMPLETED"
            assert final["status"] == expected, final
            if self.attempts == 1:
                assert len(self.receipts(case)) == 1, self.receipts(case)
            else:
                self.assert_tool(final, case)
            return {
                "run": final,
                "max_attempts": self.attempts,
                "recovery_seconds": time.monotonic() - start,
                "receipts": self.receipts(case),
            }
        finally:
            dead.start()

    def case_concurrency(self):
        count = self.concurrency
        cases = [str(uuid4()) for _ in range(count)]

        def submit_one(index):
            run, session, latency = self.submit(
                self.tool_prompt(cases[index], True),
                replica="a" if index % 2 == 0 else "b",
            )
            return run, session, latency

        start = time.monotonic()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                submitted = list(pool.map(submit_one, range(count)))
                receipts = list(pool.map(self.wait_receipt, cases))
                # All tools must reach their blocked checkpoint before any are released.
                for case in cases:
                    self.release(case)
                results = list(
                    pool.map(
                        lambda pair: self.poll(pair[0]["run_id"], pair[1]), submitted
                    )
                )
            for result, case in zip(results, cases):
                self.assert_tool(result, case)
            assert len({r["run_id"] for r in results}) == count
            return {
                "simultaneously_held_tools": count,
                "elapsed_seconds": time.monotonic() - start,
                "receipts": receipts,
                "ack_seconds": [s[2] for s in submitted],
                "runs": results,
            }
        finally:
            for case in cases:
                self.release(case)

    def run(self, cases):
        failures = 0
        try:
            for replica in self.replicas.values():
                replica.start()
            for case in cases:
                if datetime.now(timezone.utc) >= datetime.fromisoformat(
                    self.deadline.replace("Z", "+00:00")
                ):
                    break
                self.active_case = None
                started = time.time()
                try:
                    evidence = getattr(self, "case_" + case)()
                    result = {"status": "PASS", "evidence": evidence}
                except Exception:
                    failures += 1
                    result = {"status": "FAIL", "error": traceback.format_exc()}
                finally:
                    if self.active_case:
                        self.release(self.active_case)
                result.update(
                    provider=self.provider,
                    case=case,
                    started=started,
                    elapsed=time.time() - started,
                )
                write_json(self.directory / f"{case}.json", result)
                with (STATE / "results.jsonl").open("a") as output:
                    output.write(json.dumps(result, default=str) + "\n")
                print(
                    self.provider,
                    case,
                    result["status"],
                    round(result["elapsed"], 2),
                    flush=True,
                )
                if result["status"] == "FAIL" and case == "smoke":
                    print(
                        "Stopping provider after failed preflight; inspect evidence before retrying.",
                        flush=True,
                    )
                    break
        finally:
            for replica in self.replicas.values():
                replica.stop()
            self.client.close()
            self.db.db_engine.dispose()
        return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=["claude", "codex", "both"], default="both"
    )
    parser.add_argument(
        "--cases",
        default="smoke,background,disconnect,cancel,session,idempotency,crash,concurrency",
    )
    parser.add_argument("--attempts", type=int, choices=[1, 2], default=1)
    parser.add_argument("--concurrency", type=int, choices=[1, 4, 8], default=4)
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads((STATE / "state.json").read_text())
        state["notes"] = [
            note
            for note in state.get("notes", [])
            if not note.startswith("No overnight model calls")
        ]
        state["next_steps_file"] = str(STATE / "NEXT_STEPS.json")
        state["stage"] = "live_verification"
        state["runner_pid"] = os.getpid()
        write_json(STATE / "state.json", state)
        failures = 0
        for provider in (
            ["claude", "codex"] if args.provider == "both" else [args.provider]
        ):
            failures += Suite(
                provider, args.attempts, args.concurrency, state["deadline_utc"]
            ).run(args.cases.split(","))
        with sqlite3.connect(STATE / "ledger.sqlite") as db:
            count = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
        state["live_turn_budget"]["reserved_attempts"] = count
        state["stage"] = "verification_batch_finished"
        state["runner_pid"] = None
        write_json(STATE / "state.json", state)
        raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
