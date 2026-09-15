"""Real Agno SQLite persistence and Pushary SDK; only Pushary HTTP is simulated."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import run
from pushary.errors import PusharyError


def _db():
    return sqlite3.connect(os.environ["CHECK_DB"], timeout=10)


def _http(self, method, path, *, body=None, **kwargs):
    with _db() as db:
        if path == "/decisions":
            key = body["idempotencyKey"]
            db.execute(
                "insert or ignore into decisions values (?,?,'pending')",
                (key, json.dumps(body)),
            )
            original, status = db.execute(
                "select body,status from decisions where id=?", (key,)
            ).fetchone()
            assert json.loads(original) == body
            return {
                "decisionId": key,
                "status": "answered" if status in ("yes", "no") else status,
                "answered": status in ("yes", "no"),
                "type": "confirm",
                "value": status,
            }
        if path == "/authorizations/consume":
            original, status = db.execute(
                "select body,status from decisions where id=?",
                (body["authorizationId"],),
            ).fetchone()
            assert status == "yes"
            for key in ("externalId", "toolName", "toolTarget", "actor", "parameters"):
                assert json.loads(original)[key] == body[key]
            try:
                db.execute("insert into permits values (?)", (body["authorizationId"],))
            except sqlite3.IntegrityError:
                raise PusharyError("Replay", 409, {"refusal": "already_consumed"})
            db.commit()
            if os.environ.get("CHECK_LOST"):
                raise TimeoutError("Permit response lost")
            if os.environ.get("CHECK_EXPIRE"):
                patch("run.time.time", return_value=time.time() + 7200).start()
            return {"permitId": body["authorizationId"]}
        if path.endswith("/receipt"):
            if os.environ.get("CHECK_CRASH"):
                os._exit(23)
            return {}
        raise AssertionError(path)


def main():
    os.environ["PUSHARY_API_KEY"] = "pk_offline.sk_offline"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        os.environ["CHECK_DB"] = str(root / "service.db")
        with _db() as db:
            db.executescript(
                "create table decisions(id primary key,body,status);create table permits(id primary key);"
            )

        def sql(query):
            with _db() as db:
                return db.execute(query).fetchall()

        def worker(mode, folder, tenant="tenant-1", customer="customer-1", **env):
            return subprocess.Popen(
                [sys.executable, __file__, mode, str(folder), tenant, customer],
                env={**os.environ, **env},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        def finish(process, success=True):
            output, error = process.communicate(timeout=40)
            assert (process.returncode == 0) == success, error.decode()
            return json.loads(output) if success else None

        def effects(folder):
            if not (folder / "orders.db").exists():
                return 0
            with sqlite3.connect(folder / "orders.db") as db:
                return db.execute("select count(*) from released").fetchone()[0]

        counter = 0

        def new():
            nonlocal counter
            counter += 1
            sql("delete from decisions")
            sql("delete from permits")
            folder = root / str(counter)
            assert "blocked" in finish(worker("start", folder))
            assert effects(folder) == 0
            return folder

        folder = new()
        finish(worker("start", folder), False)
        assert "blocked" in finish(worker("resume", folder))
        assert len(sql("select * from decisions")) == 1
        sql("update decisions set status='yes'")
        assert finish(worker("resume", folder))["result"]["status"] == "released"
        finish(worker("resume", folder), False)
        assert effects(folder) == 1
        for answer in ("no", "expired", "cancelled"):
            folder = new()
            sql(f"update decisions set status='{answer}'")
            assert "blocked" in finish(worker("resume", folder))
            assert effects(folder) == 0
        for identity in ({"tenant": "other"}, {"customer": "other"}):
            folder = new()
            sql("update decisions set status='yes'")
            finish(worker("resume", folder, **identity), False)
            assert not sql("select * from permits")
        folder = new()
        op = json.loads((folder / "operation.json").read_text())
        op["order"]["amount_cents"] = 9999
        (folder / "operation.json").write_text(json.dumps(op))
        finish(worker("resume", folder), False)
        assert not sql("select * from permits")
        for flag in ("CHECK_LOST", "CHECK_EXPIRE"):
            folder = new()
            sql("update decisions set status='yes'")
            process = worker("resume", folder, **{flag: "1"})
            process.communicate(timeout=40)
            process = worker("resume", folder)
            process.communicate(timeout=40)
            assert effects(folder) == 0 and len(sql("select * from permits")) == 1
        folder = new()
        sql("update decisions set status='yes'")
        crashed = worker("resume", folder, CHECK_CRASH="1")
        crashed.communicate(timeout=40)
        assert crashed.returncode == 23 and effects(folder) == 1
        finish(worker("resume", folder), False)
        assert effects(folder) == 1
        folder = new()
        sql("update decisions set status='yes'")
        processes = [worker("resume", folder) for _ in range(2)]
        for process in processes:
            process.communicate(timeout=40)
        assert effects(folder) == 1 and len(sql("select * from permits")) == 1
        folder = new()
        op = json.loads((folder / "operation.json").read_text())
        pending = json.loads((folder / "pending.json").read_text())
        workflow = run._workflow(folder, op, {"active": False})
        native = workflow.get_run_output(
            pending["run_id"], session_id=op["session_id"], user_id=op["user_id"]
        )
        native.steps_requiring_confirmation[0].confirm()
        try:
            workflow.continue_run(native)
        except PermissionError:
            assert effects(folder) == 0
        assert effects(folder) == 0
        finish(worker("resume", folder), False)
    print(
        "PASS: native pause/restart, pending/refusal, binding changes, duplicate workers, lost permit, expiry, native bypass"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with patch("pushary.client.PusharyServer._request", _http):
            print(json.dumps(run._run(*sys.argv[1:])))
    else:
        main()
