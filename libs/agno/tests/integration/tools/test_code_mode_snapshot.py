"""Snapshot round-trip tests against SQLite and PostgreSQL.

Postgres runs against the pgvector container from cookbook/scripts/run_pgvector.sh
(host port 5532, db/user/pass all `ai`) with a per-process schema.
"""

import json
import os
import time
import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.fs import FileSystem
from agno.fs.db import DbFileSystem
from agno.run import RunContext
from agno.tools.code_mode import CodeMode
from agno.tools.code_mode.bridge import ToolBridge
from agno.tools.toolkit import Toolkit

pytestmark = pytest.mark.integration

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
PG_SCHEMA = f"codemode_test_{os.getpid()}"
DIALECTS = ["sqlite", "postgresql"]


def _sid(prefix: str) -> str:
    return f"snap-{prefix}-{uuid.uuid4().hex[:8]}"


def _ctx(session_id: str) -> RunContext:
    return RunContext(run_id="snap-run", session_id=session_id)


class EchoTools(Toolkit):
    def __init__(self, **kwargs):
        super().__init__(name="echo_tools", tools=[self.echo], **kwargs)

    def echo(self, text: str) -> str:
        """Echo the text back.

        Args:
            text: The text to echo.
        """
        return "echo:" + text


@pytest.fixture(scope="session")
def pg_engine():
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{PG_SCHEMA}"'))
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{PG_SCHEMA}" CASCADE'))
    engine.dispose()


@pytest.fixture(params=DIALECTS)
def snapshot_fs(request, tmp_path):
    """A FileSystem for snapshots, per dialect."""
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path}/code_mode.db", connect_args={"timeout": 30})
        backend = DbFileSystem(db_engine=engine)
        yield FileSystem(
            backend=backend, namespace="code-mode", max_file_bytes=4_000_000, max_namespace_bytes=128_000_000
        )
        engine.dispose()
    else:
        engine = request.getfixturevalue("pg_engine")
        backend = DbFileSystem(db_engine=engine, db_schema=PG_SCHEMA)
        yield FileSystem(
            backend=backend, namespace="code-mode", max_file_bytes=4_000_000, max_namespace_bytes=128_000_000
        )
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{PG_SCHEMA}".{backend.table_name}'))


@pytest.fixture
def make_code_mode():
    instances = []

    def factory(**kwargs):
        cm = CodeMode(**kwargs)
        instances.append(cm)
        return cm

    yield factory
    for cm in instances:
        try:
            cm.shutdown()
        except Exception:
            pass


# ------------------------------------------------------------------
# The round trip
# ------------------------------------------------------------------


def test_snapshot_round_trip_restores_picklable_and_names_unpicklable(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("roundtrip")
    cm.execute(
        _ctx(sid),
        "import socket\nframes = [1, 2, 3]\nworld_model = {'level': 4}\nsock = socket.socket()\n",
    )
    cm.close()  # flush a final snapshot without killing the kernel
    cm.shutdown(sid)  # now kill it

    revived = cm.execute(_ctx(sid), "frames + [4]")
    assert "<code_mode_restored>" in revived.content
    assert "frames" in revived.content
    assert "world_model" in revived.content
    assert "Not restored (unpicklable): sock." in revived.content
    assert "[1, 2, 3, 4]" in revived.content
    follow_up = cm.execute(_ctx(sid), "world_model['level']")
    assert "4" in follow_up.content


def test_debounced_snapshot_lands_without_explicit_close(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("debounce")
    cm.execute(_ctx(sid), "auto_saved = 'yes'")
    deadline = time.monotonic() + 10
    manifest = None
    while manifest is None and time.monotonic() < deadline:
        time.sleep(0.2)
        manifest = snapshot_fs.read(f"kernel/{sid}/manifest.json")
    assert manifest is not None, "debounced snapshot never landed"
    names = [v["name"] for v in json.loads(manifest)["variables"]]
    assert "auto_saved" in names


def test_deleted_variable_does_not_resurrect(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("deleted")
    cm.execute(_ctx(sid), "keep = 1\ndrop = 2")
    cm.close()
    cm.execute(_ctx(sid), "del drop")
    cm.close()
    cm.shutdown(sid)
    revived = cm.execute(_ctx(sid), "'drop' in dir()")
    assert "keep" in revived.content
    assert "drop" not in revived.content.split("<code_mode_restored>")[1].split("</code_mode_restored>")[0]


def test_corrupt_manifest_yields_empty_restore_and_no_notice(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("corrupt")
    snapshot_fs.write(f"kernel/{sid}/manifest.json", "this is not json {")
    result = cm.execute(_ctx(sid), "'alive'")
    assert "<code_mode_restored>" not in result.content
    assert "alive" in result.content


def test_restart_clears_the_snapshot(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("restart-clear")
    cm.execute(_ctx(sid), "zombie = 'brains'")
    cm.close()
    assert snapshot_fs.read(f"kernel/{sid}/manifest.json") is not None
    cm.restart(_ctx(sid))
    assert snapshot_fs.read(f"kernel/{sid}/manifest.json") is None
    cm.shutdown(sid)
    revived = cm.execute(_ctx(sid), "'fresh'")
    assert "<code_mode_restored>" not in revived.content


# ------------------------------------------------------------------
# Caps and budget
# ------------------------------------------------------------------


def test_oversized_variable_is_skipped_and_small_ones_kept(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05, max_variable_bytes=10_000)
    sid = _sid("cap")
    cm.execute(_ctx(sid), "small = 'tiny'\nbig = 'x' * 100_000")
    cm.close()
    manifest = json.loads(snapshot_fs.read(f"kernel/{sid}/manifest.json"))
    kept = [v["name"] for v in manifest["variables"]]
    skipped = {s["name"]: s["reason"] for s in manifest["skipped"]}
    assert "small" in kept
    assert "big" not in kept
    assert "big" in skipped
    assert "over the 10000-byte cap" in skipped["big"]
    cm.shutdown(sid)
    revived = cm.execute(_ctx(sid), "small")
    assert "Not restored (unpicklable): big." in revived.content
    assert "tiny" in revived.content


def test_snapshot_budget_cuts_largest_last(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05, max_variable_bytes=2_000_000, max_snapshot_bytes=50_000)
    sid = _sid("budget")
    cm.execute(_ctx(sid), "tiny_a = 'a'\ntiny_b = 'b'\nhuge = 'x' * 200_000")
    cm.close()
    manifest = json.loads(snapshot_fs.read(f"kernel/{sid}/manifest.json"))
    kept = [v["name"] for v in manifest["variables"]]
    skipped = {s["name"]: s["reason"] for s in manifest["skipped"]}
    assert "tiny_a" in kept and "tiny_b" in kept
    assert "huge" in skipped
    assert "snapshot budget" in skipped["huge"]


# ------------------------------------------------------------------
# Restore ordering and live handles
# ------------------------------------------------------------------


def test_stale_pickled_handle_loses_to_live_binding(snapshot_fs, make_code_mode):
    # Last week's session pickled a plain variable under the handle's name.
    plain = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("ordering")
    plain.execute(_ctx(sid), "echo = 'stale-string-from-last-week'")
    plain.close()
    plain.shutdown(sid)

    # This run wires a live EchoTools under the same handle name.
    live = make_code_mode(tools=[EchoTools()], fs=snapshot_fs, snapshot_debounce=0.05)
    result = live.execute(_ctx(sid), "await echo.echo(text='live')")
    assert "echo:live" in result.content, f"live handle lost to the stale pickle: {result.content}"


def test_live_handles_are_new_instances_not_restored_copies(snapshot_fs, make_code_mode):
    cm = make_code_mode(tools=[EchoTools()], fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("fresh-handles")
    cm.execute(_ctx(sid), "echo._agno_marker = 'stale'\nkept_var = 1")
    cm.close()
    cm.shutdown(sid)
    revived = cm.execute(_ctx(sid), "hasattr(echo, '_agno_marker')")
    assert "False" in revived.content
    # The handle is excluded from the snapshot by name, not restored and overwritten.
    assert "echo" not in [
        v.strip() for v in revived.content.split("Restored")[-1].split(":")[-1].split(".")[0].split(",")
    ]
    works = cm.execute(_ctx(sid), "await echo.echo(text='after-restore')")
    assert "echo:after-restore" in works.content


def test_notice_absent_when_bootstrap_fails(snapshot_fs, make_code_mode, monkeypatch):
    cm = make_code_mode(tools=[EchoTools()], fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("bootstrap-fail")
    cm.execute(_ctx(sid), "precious = 'state'")
    cm.close()
    cm.shutdown(sid)

    # Break the bootstrap cell: the restored notice must not outlive it.
    monkeypatch.setattr(ToolBridge, "bootstrap_code", lambda self: "raise RuntimeError('forced bootstrap failure')")
    revived = cm.execute(_ctx(sid), "'ran-anyway'")
    assert "<code_mode_restored>" not in revived.content
    assert "ran-anyway" in revived.content
