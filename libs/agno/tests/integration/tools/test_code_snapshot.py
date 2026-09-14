"""Snapshot round-trip tests against SQLite and PostgreSQL.

Postgres runs against the pgvector container from cookbook/scripts/run_pgvector.sh
(host port 5532, db/user/pass all `ai`) with a per-process schema.
"""

import asyncio
import json
import os
import threading
import time
import uuid
from typing import Optional

import pytest

pytest.importorskip("ipykernel")
pytest.importorskip("jupyter_client")
pytest.importorskip("dill")

from sqlalchemy import create_engine, text  # noqa: E402

from agno.fs import FileSystem  # noqa: E402
from agno.fs.db import DbFileSystem  # noqa: E402
from agno.run import RunContext  # noqa: E402
from agno.tools.code import CodeMode  # noqa: E402
from agno.tools.code.bridge import ToolBridge  # noqa: E402
from agno.tools.code.code_mode import OWNER_REFUSAL  # noqa: E402
from agno.tools.code.kernel import KernelSession  # noqa: E402
from agno.tools.code.snapshot import SnapshotManager  # noqa: E402
from agno.tools.toolkit import Toolkit  # noqa: E402

pytestmark = pytest.mark.integration

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
PG_SCHEMA = f"codemode_test_{os.getpid()}"
DIALECTS = ["sqlite", "postgresql"]


def _sid(prefix: str) -> str:
    return f"snap-{prefix}-{uuid.uuid4().hex[:8]}"


def _ctx(session_id: str, user_id: Optional[str] = None) -> RunContext:
    return RunContext(run_id="snap-run", session_id=session_id, user_id=user_id)


async def _hold_lock(session, release: threading.Event, limit: float = 6.0) -> None:
    """Hold a session's lock, as a long cell does, until released or ``limit``."""
    async with session.lock:
        deadline = time.monotonic() + limit
        while not release.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)


def _wait_for_lock(session, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not session.lock.locked() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert session.lock.locked(), "the holder never took the session lock"


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
    assert "Not restored:" in revived.content
    assert "- sock: " in revived.content
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
    assert "too large to store" in skipped["big"]
    assert "over the 10000-byte limit" in skipped["big"]
    cm.shutdown(sid)
    revived = cm.execute(_ctx(sid), "small")
    assert "big: too large to store" in revived.content
    assert "unpicklable" not in revived.content
    assert "tiny" in revived.content


def _small_store(snapshot_fs):
    """A store with the FileSystem defaults, well under CodeMode's own caps."""
    return FileSystem(
        backend=snapshot_fs.backend,
        namespace="code-mode-caps",
        max_file_bytes=1_000_000,
        max_namespace_bytes=20_000_000,
    )


def test_variable_under_the_cap_round_trips_and_the_manifest_counts_stored_bytes(snapshot_fs, make_code_mode):
    # 740,000 characters pickle to ~740,030 bytes and store as 986,708 bytes of
    # base64, just under the store's 1,000,000-byte file limit.
    store = _small_store(snapshot_fs)
    cm = make_code_mode(fs=store, snapshot_debounce=0.05)
    sid = _sid("under-cap")
    cm.execute(_ctx(sid), "blob = 'y' * 740_000")
    cm.close()
    manifest = json.loads(store.read(f"kernel/{sid}/manifest.json"))
    entry = next(v for v in manifest["variables"] if v["name"] == "blob")
    assert entry["bytes"] == len(store.read(f"kernel/{sid}/vars/blob.b64"))
    assert entry["bytes"] <= 1_000_000
    cm.shutdown(sid)
    revived = cm.execute(_ctx(sid), "len(blob)")
    assert "740000" in revived.content
    assert "Not restored" not in revived.content


def test_variable_over_the_store_limit_is_reported_by_size_not_as_unpicklable(snapshot_fs, make_code_mode):
    # 800,000 characters pickle to ~800,009 bytes, under CodeMode's 2,000,000-byte
    # cap, and store as 1,066,680 bytes of base64, over the store's file limit.
    store = _small_store(snapshot_fs)
    cm = make_code_mode(fs=store, snapshot_debounce=0.05)
    sid = _sid("b64-inflation")
    cm.execute(_ctx(sid), "small = 'tiny'\nbig = 'x' * 800_000")
    cm.close()
    manifest = json.loads(store.read(f"kernel/{sid}/manifest.json"))
    skipped = {s["name"]: s["reason"] for s in manifest["skipped"]}
    assert "big" in skipped
    assert "too large to store: 1066680 bytes, over the 1000000-byte limit" == skipped["big"]
    assert "small" in [v["name"] for v in manifest["variables"]]
    cm.shutdown(sid)
    revived = cm.execute(_ctx(sid), "small")
    assert "- big: too large to store: 1066680 bytes, over the 1000000-byte limit" in revived.content
    assert "unpicklable" not in revived.content
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


# ------------------------------------------------------------------
# Reviewer regressions
# ------------------------------------------------------------------


def test_two_cells_then_restart_leaves_no_manifest(snapshot_fs, make_code_mode):
    # Two cells inside the debounce window orphaned the first timer's
    # bookkeeping; its flush then fired after restart's clear and resurrected
    # the manifest. Deterministic under this cadence before the fix.
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.4)
    sid = _sid("timer-orphan")
    cm.execute(_ctx(sid), "a = 1")
    cm.execute(_ctx(sid), "b = 2")
    cm.restart(_ctx(sid))
    time.sleep(1.5)  # long enough for any straggler debounced flush to land
    assert snapshot_fs.read(f"kernel/{sid}/manifest.json") is None


def test_refused_variable_keeps_previous_good_copy(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05, max_variable_bytes=50_000)
    sid = _sid("keep-copy")
    cm.execute(_ctx(sid), "grows = 'small'")
    cm.close()
    var_path = f"kernel/{sid}/vars/grows.b64"
    assert snapshot_fs.read(var_path) is not None
    previous = snapshot_fs.read(var_path)
    cm.execute(_ctx(sid), "grows = 'x' * 200_000")
    cm.close()
    manifest = json.loads(snapshot_fs.read(f"kernel/{sid}/manifest.json"))
    assert "grows" in {s["name"] for s in manifest["skipped"]}
    assert "grows" not in {v["name"] for v in manifest["variables"]}
    # The last good copy survives; it is simply not restored (manifest governs).
    assert snapshot_fs.read(var_path) == previous


def test_another_user_cannot_resume_a_session_from_its_snapshot(snapshot_fs, make_code_mode):
    owner = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("owner-restore")
    owner.execute(_ctx(sid, user_id="user-a"), "token = 'secret-a'")
    owner.close()
    owner.shutdown(sid)
    assert json.loads(snapshot_fs.read(f"kernel/{sid}/manifest.json"))["owner_user_id"] == "user-a"

    # A second instance stands in for a process with no live kernel: the
    # snapshot is the only record of who the state belongs to.
    intruder = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    refused = intruder.execute(_ctx(sid, user_id="user-b"), "token")
    assert refused.content == OWNER_REFUSAL
    assert "secret-a" not in refused.content
    assert intruder._sessions.get(sid) is None, "the refused run must not start a kernel"
    resumed = intruder.execute(_ctx(sid, user_id="user-a"), "token")
    assert "secret-a" in resumed.content


async def test_restore_refuses_a_snapshot_owned_by_another_user(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("restore-guard")
    cm.execute(_ctx(sid, user_id="user-a"), "token = 'secret-a'")
    cm.close()
    cm.shutdown(sid)
    # Straight at the restore path: it refuses before any payload is read, so
    # the kernel of another user is never handed the variables.
    manager = SnapshotManager(snapshot_fs, debounce=0.05)
    assert await manager.restore(KernelSession(sid, owner_user_id="user-b")) is None


def test_a_run_without_an_identity_keeps_the_recorded_owner(snapshot_fs, make_code_mode):
    owner = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("owner-adopt")
    owner.execute(_ctx(sid, user_id="user-a"), "token = 'secret-a'")
    owner.close()
    owner.shutdown(sid)

    # An in-process call or an unowned schedule reaches the session with no
    # user_id at all. It reads the state, and it leaves the record intact.
    anonymous = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    read = anonymous.execute(_ctx(sid), "token")
    assert "secret-a" in read.content
    assert anonymous._sessions[sid].owner_user_id == "user-a"
    anonymous.close()
    anonymous.shutdown(sid)
    assert json.loads(snapshot_fs.read(f"kernel/{sid}/manifest.json"))["owner_user_id"] == "user-a"

    intruder = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    refused = intruder.execute(_ctx(sid, user_id="user-b"), "token")
    assert refused.content == OWNER_REFUSAL
    assert "secret-a" not in refused.content

    back = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    assert "secret-a" in back.execute(_ctx(sid, user_id="user-a"), "token").content


def test_a_user_id_that_is_not_a_str_resumes_its_own_session(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("int-user")
    cm.execute(_ctx(sid, user_id=42), "token = 'secret-42'")
    cm.close()
    cm.shutdown(sid)
    assert json.loads(snapshot_fs.read(f"kernel/{sid}/manifest.json"))["owner_user_id"] == "42"

    resumed = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    assert "secret-42" in resumed.execute(_ctx(sid, user_id=42), "token").content
    # The same id read back from a database as text is the same user.
    assert "secret-42" in resumed.execute(_ctx(sid, user_id="42"), "token").content
    resumed.close()
    resumed.shutdown(sid)

    other = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    assert other.execute(_ctx(sid, user_id=43), "token").content == OWNER_REFUSAL
    assert snapshot_fs.read(f"kernel/{sid}/vars/token.b64") is not None

    # A manifest written before identity was normalized holds the raw id, and
    # the user it belongs to still gets in.
    manifest_path = f"kernel/{sid}/manifest.json"
    stored = json.loads(snapshot_fs.read(manifest_path))
    stored["owner_user_id"] = 42
    snapshot_fs.write(manifest_path, json.dumps(stored))
    legacy = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    assert "secret-42" in legacy.execute(_ctx(sid, user_id=42), "token").content


async def test_a_kernel_refused_the_snapshot_does_not_overwrite_it(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("refused-write")
    cm.execute(_ctx(sid, user_id="user-a"), "token = 'secret-a'")
    cm.close()
    cm.shutdown(sid)
    manifest_before = snapshot_fs.read(f"kernel/{sid}/manifest.json")
    payload_before = snapshot_fs.read(f"kernel/{sid}/vars/token.b64")

    # A kernel of another user, reached past the CodeMode guard: restore
    # refuses it the variables, so its own namespace must not be written over
    # them either.
    manager = SnapshotManager(snapshot_fs, debounce=0.05)
    session = KernelSession(sid, owner_user_id="user-b", idle_ttl=0, setup_hook=manager.restore)
    try:
        await session.execute_cell("mine = 'secret-b'", timeout=120)
        async with session.lock:
            await manager.flush_locked(session)
    finally:
        await session.shutdown()

    assert snapshot_fs.read(f"kernel/{sid}/manifest.json") == manifest_before
    assert snapshot_fs.read(f"kernel/{sid}/vars/token.b64") == payload_before
    assert snapshot_fs.read(f"kernel/{sid}/vars/mine.b64") is None


def test_eviction_drops_the_session_and_the_next_execute_restores_it(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05, idle_ttl=1)
    sid = _sid("evict-restore")
    cm.execute(_ctx(sid), "kept = 'from-before-eviction'")
    session = cm._sessions[sid]
    deadline = time.monotonic() + 15
    while cm._sessions.get(sid) is not None and time.monotonic() < deadline:
        time.sleep(0.2)
    assert cm._sessions.get(sid) is None, "eviction must not keep the session entry"
    assert not session.running
    assert session.run_context is None
    revived = cm.execute(_ctx(sid), "kept")
    assert "<code_mode_restored>" in revived.content
    assert "from-before-eviction" in revived.content


def test_close_does_not_wait_for_another_sessions_lock(snapshot_fs, make_code_mode):
    # A run ends while another session is mid-cell. The debounce is long
    # enough that both sessions still have unsaved cells at close time.
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=5.0)
    busy, quiet = _sid("close-busy"), _sid("close-quiet")
    cm.execute(_ctx(busy), "busy_var = 1")
    cm.execute(_ctx(quiet), "quiet_var = 2")
    release = threading.Event()
    holder = cm._runner.submit(_hold_lock(cm._sessions[busy], release))
    try:
        _wait_for_lock(cm._sessions[busy])
        started = time.monotonic()
        cm.close()
        elapsed = time.monotonic() - started
    finally:
        release.set()
        holder.result(timeout=15)
    assert elapsed < 3, f"close waited {elapsed:.1f}s on another session's lock"
    assert snapshot_fs.read(f"kernel/{quiet}/manifest.json") is not None


async def test_close_on_an_event_loop_does_not_block_it(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=5.0)
    busy, quiet = _sid("aclose-busy"), _sid("aclose-quiet")
    await cm.aexecute(_ctx(busy), "busy_var = 1")
    await cm.aexecute(_ctx(quiet), "quiet_var = 2")
    release = threading.Event()
    holder = cm._runner.submit(_hold_lock(cm._sessions[busy], release))
    try:
        _wait_for_lock(cm._sessions[busy])
        started = time.monotonic()
        # The agent calls close() from the async run's cleanup, on this loop.
        cm.close()
        elapsed = time.monotonic() - started
    finally:
        release.set()
        holder.result(timeout=15)
    assert elapsed < 1, f"close blocked the event loop for {elapsed:.1f}s"
    # The flush it handed off still lands.
    cm._background_flush.result(timeout=15)
    assert snapshot_fs.read(f"kernel/{quiet}/manifest.json") is not None


async def test_aclose_flushes_the_pending_session(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=5.0)
    sid = _sid("aclose-flush")
    await cm.aexecute(_ctx(sid), "saved = 'via-aclose'")
    await cm.aclose()
    manifest = snapshot_fs.read(f"kernel/{sid}/manifest.json")
    assert manifest is not None
    assert "saved" in [v["name"] for v in json.loads(manifest)["variables"]]


def test_close_writes_nothing_for_a_session_with_no_new_cell(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=30.0)
    sid = _sid("close-idempotent")
    cm.execute(_ctx(sid), "first = 1")
    cm.close()
    manifest_path = f"kernel/{sid}/manifest.json"
    saved_at = json.loads(snapshot_fs.read(manifest_path))["saved_at"]
    # Every later run ends with another close(); none of them may snapshot a
    # namespace that has not changed.
    time.sleep(1.1)
    cm.close()
    cm.close()
    assert json.loads(snapshot_fs.read(manifest_path))["saved_at"] == saved_at


def test_hostile_session_id_round_trips_and_does_not_nest(snapshot_fs, make_code_mode):
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    parent = "u1"
    nested = "u1/vars"
    cm.execute(_ctx(parent), "mine = 'parent'")
    cm.execute(_ctx(nested), "theirs = 'nested'")
    cm.close()
    cm.shutdown()
    revived_parent = cm.execute(_ctx(parent), "mine")
    revived_nested = cm.execute(_ctx(nested), "theirs")
    assert "parent" in revived_parent.content
    assert "nested" in revived_nested.content


async def test_a_failed_manifest_read_tells_the_model_nothing_will_persist():
    # A transient store failure holds snapshots back; the model must be told
    # its new work will not outlive this kernel, not left to assume it saves.
    class BrokenFs:
        async def aread(self, path):
            raise RuntimeError("store is down")

    manager = SnapshotManager(BrokenFs())  # type: ignore[arg-type]
    session = KernelSession(_sid("no-persist"))
    notice = await manager.restore(session)
    assert notice is not None
    assert "code_mode_not_persisted" in notice
    assert session.snapshot_writable is False


def test_a_user_variable_named_results_survives_a_restart(snapshot_fs, make_code_mode):
    # The built-in handle is result_store, not results, so a user variable
    # named results is ordinary state: listed, snapshotted, restored.
    cm = make_code_mode(fs=snapshot_fs, snapshot_debounce=0.05)
    sid = _sid("user-results")
    cm.execute(_ctx(sid), "results = [1, 2, 3]")
    variables = cm.variables(sid)
    assert "results" in variables
    assert "result_store" not in variables
    assert "ResultTooLarge" not in variables
    cm.close()
    cm.shutdown(sid)
    revived = cm.execute(_ctx(sid), "print(results)")
    assert "[1, 2, 3]" in revived.content
