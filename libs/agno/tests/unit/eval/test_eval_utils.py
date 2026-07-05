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


def test_spinner_live_disabled_is_a_noop():
    from rich.console import Console

    with spinner_live(Console(), enabled=False) as live:
        assert live is None
