"""Unit tests for eval utils (agno.eval.utils)."""

import asyncio
import threading

from agno.db.schemas.evals import EvalType
from agno.eval.utils import async_log_eval, spinner_live


class RecordingSyncDb:
    """Sync-db stand-in: records the eval-run record and the executing thread."""

    def __init__(self):
        self.records = []
        self.threads = []

    def create_eval_run(self, record):
        self.records.append(record)
        self.threads.append(threading.current_thread())


def test_async_log_eval_runs_sync_db_off_loop():
    db = RecordingSyncDb()

    asyncio.run(async_log_eval(db=db, run_id="run-1", run_data={}, eval_type=EvalType.AGENT_AS_JUDGE, eval_input={}))

    assert len(db.records) == 1
    assert db.records[0].run_id == "run-1"
    # A sync driver must not run on the event loop, where it would block the loop
    # and defeat caller-side timeouts.
    assert db.threads[0] is not threading.main_thread()
    # And the worker must be a daemon: a hung db write must not block interpreter
    # exit (asyncio.to_thread's executor threads are joined at shutdown).
    assert db.threads[0].daemon is True


def test_async_log_eval_write_failure_is_swallowed_and_warned(monkeypatch):
    # log_warning wraps the agno logger, which may be built with propagate=False -
    # pytest's caplog can't reliably observe it, so capture the call directly.
    warnings = []
    monkeypatch.setattr("agno.eval.utils.log_warning", warnings.append)

    class FailingSyncDb:
        def create_eval_run(self, record):
            raise RuntimeError("db exploded")

    asyncio.run(
        async_log_eval(
            db=FailingSyncDb(), run_id="run-1", run_data={}, eval_type=EvalType.AGENT_AS_JUDGE, eval_input={}
        )
    )  # must not raise

    assert any("Could not log eval run" in message for message in warnings)


def test_async_log_eval_in_memory_sqlite_stays_on_loop_and_persists():
    # In-memory sqlite is thread-affine (one private database per thread): the
    # write must run on the loop thread so it lands in the caller's database.
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_url="sqlite:///:memory:")

    asyncio.run(async_log_eval(db=db, run_id="run-1", run_data={}, eval_type=EvalType.AGENT_AS_JUDGE, eval_input={}))

    runs = db.get_eval_runs()
    assert [run.run_id for run in runs] == ["run-1"]


def test_async_log_eval_uri_form_in_memory_sqlite_stays_on_loop_and_persists():
    # URI-form in-memory sqlite gets the same thread-affine SingletonThreadPool as
    # ":memory:" but a different url.database - the pool class, not the URL
    # spelling, must decide the routing.
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_url="sqlite:///file:eval_mem?mode=memory&uri=true")

    asyncio.run(async_log_eval(db=db, run_id="run-1", run_data={}, eval_type=EvalType.AGENT_AS_JUDGE, eval_input={}))

    runs = db.get_eval_runs()
    assert [run.run_id for run in runs] == ["run-1"]


def test_abandoned_write_warns_at_cancellation_and_on_late_failure(monkeypatch):
    # A per-case timeout cancels the awaiter mid-write. The CancelledError bypasses
    # async_log_eval's except-Exception warning path, and the daemon thread's late
    # outcome hits the cancelled-future guard - both moments must warn, or eval
    # history stops persisting with zero signal.
    warnings = []
    monkeypatch.setattr("agno.eval.utils.log_warning", warnings.append)
    release = threading.Event()

    class SlowFailingSyncDb:
        def create_eval_run(self, record):
            release.wait(timeout=5)
            raise RuntimeError("db exploded late")

    async def main():
        try:
            await asyncio.wait_for(
                async_log_eval(
                    db=SlowFailingSyncDb(),
                    run_id="run-1",
                    run_data={},
                    eval_type=EvalType.AGENT_AS_JUDGE,
                    eval_input={},
                ),
                timeout=0.05,
            )
        except asyncio.TimeoutError:
            pass
        release.set()
        # Keep the loop alive so the daemon thread's resolve() can land.
        for _ in range(100):
            if len(warnings) >= 2:
                break
            await asyncio.sleep(0.02)

    asyncio.run(main())

    assert any("abandoned by timeout; the row may not be persisted" in str(w) for w in warnings)
    assert any("Could not log eval run (write abandoned by timeout): db exploded late" in str(w) for w in warnings)


def test_spinner_live_disabled_emits_nothing(capsys):
    from rich.console import Console

    with spinner_live(Console(), enabled=False) as live:
        # Bound to a quiet console: renders nothing, not even control sequences
        assert live.console.quiet is True
        # And no auto-refresh: nothing renders, so no render thread either
        assert live.auto_refresh is False
    assert capsys.readouterr().out == ""
