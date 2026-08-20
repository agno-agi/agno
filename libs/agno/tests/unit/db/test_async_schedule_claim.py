"""The async claim must hold the same predicates as the sync one.

A poller SELECTs a due, enabled schedule and then UPDATEs it to take the
lock. The two statements are not one operation, so anything that commits
between them -- a disable, the archive cascade, a reschedule -- has to make
the claim a no-op. The sync adapter repeats every predicate on the UPDATE
for exactly that reason; the async twin drives the same poller and must
not be weaker.
"""

import time

import pytest
from sqlalchemy import event

from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb


def _arm(db, schedule_id="sched-1", enabled=True):
    """An enabled, already-due schedule."""
    db.create_schedule(
        {
            "id": schedule_id,
            "name": schedule_id,
            "user_id": "u1",
            "cron_expr": "* * * * *",
            "endpoint": "/agents/a1/runs",
            "method": "POST",
            "timezone": "UTC",
            "timeout_seconds": 3600,
            "max_retries": 0,
            "retry_delay_seconds": 60,
            "enabled": enabled,
            "next_run_at": int(time.time()) - 60,
            "created_at": int(time.time()),
        }
    )


@pytest.fixture
def paths(tmp_path):
    return str(tmp_path / "claim.db")


class TestTheAsyncClaimMatchesTheSyncOne:
    @pytest.mark.asyncio
    async def test_the_update_repeats_the_select_predicates(self, paths):
        sync_db = SqliteDb(id="claim-sync", db_file=paths)
        _arm(sync_db)
        adb = AsyncSqliteDb(id="claim-async", db_file=paths)

        statements = []

        @event.listens_for(adb.db_engine.sync_engine, "before_cursor_execute")
        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        claimed = await adb.claim_due_schedule(worker_id="poller-1")
        assert claimed is not None

        updates = [s for s in statements if s.strip().upper().startswith("UPDATE")]
        assert updates, statements
        claim_update = updates[0].lower()
        assert "enabled" in claim_update, claim_update
        assert "next_run_at" in claim_update, claim_update

    @pytest.mark.asyncio
    async def test_the_claim_returns_post_claim_state(self, paths):
        """The returned dict must describe the row, not the snapshot.

        Asserting locked_by alone pins nothing: the code this replaced patched
        that field onto the pre-claim snapshot by hand. The test has to name a
        field the snapshot could not have carried, so the row is changed on a
        second connection after it is armed and before it is claimed.
        """
        sync_db = SqliteDb(id="claim-sync-2", db_file=paths)
        _arm(sync_db, "sched-2")
        adb = AsyncSqliteDb(id="claim-async-2", db_file=paths)

        # The select the claim runs sees this; a hand-patched snapshot of an
        # earlier read would not.
        sync_db.update_schedule("sched-2", description="changed after arming")

        claimed = await adb.claim_due_schedule(worker_id="poller-9")
        assert claimed is not None
        assert claimed["locked_by"] == "poller-9"
        assert claimed["description"] == "changed after arming"
        assert sync_db.get_schedule("sched-2")["locked_by"] == "poller-9"

    @pytest.mark.asyncio
    async def test_a_disabled_schedule_is_never_claimed(self, paths):
        sync_db = SqliteDb(id="claim-sync-3", db_file=paths)
        _arm(sync_db, "sched-3", enabled=False)
        adb = AsyncSqliteDb(id="claim-async-3", db_file=paths)

        assert await adb.claim_due_schedule(worker_id="poller-1") is None
