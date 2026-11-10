"""A dead database must be LOUD, not indistinguishable from
an empty queue. The queue sections' catches logged at DEBUG - production logs
showed nothing while every claim, heartbeat, and settlement silently failed.
Claims and fenced/terminal writes now log at ERROR, pure reads at WARNING,
all with job/worker/attempt identifiers. No server needed: _get_table is
mocked to hand back a fake table so the failure lands INSIDE the guarded
section (a dead port short-circuits earlier, in _get_table's own guard).
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("psycopg", reason="postgres extras required for the adapter under test")

from agno.db.postgres import AsyncPostgresDb  # noqa: E402

DEAD_URL = "postgresql+psycopg://ai:ai@localhost:59999/ai"


@pytest.fixture()
def dead_db(monkeypatch) -> AsyncPostgresDb:
    db = AsyncPostgresDb(db_url=DEAD_URL, job_table="never_created")
    monkeypatch.setattr(db, "_get_table", AsyncMock(return_value=MagicMock(name="fake_table")))
    return db


class TestDeadDbIsLoud:
    @pytest.mark.asyncio
    async def test_claim_failure_logs_error_with_identifiers(self, dead_db, caplog):
        with caplog.at_level(logging.ERROR, logger="agno"):
            result = await dead_db.claim_job("w-loud", deployment_id="dep-1")
        assert result is None
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR and "claim failed" in r.message]
        assert errors, f"a dead DB at claim must log ERROR, got: {[r.message for r in caplog.records]}"
        assert "w-loud" in errors[0].message and "dep-1" in errors[0].message

    @pytest.mark.asyncio
    async def test_settlement_failure_logs_error_with_identifiers(self, dead_db, caplog):
        with caplog.at_level(logging.ERROR, logger="agno"):
            applied = await dead_db.complete_job("j-loud", "w-loud", 2, "completed")
        assert applied is False
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR and "settle failed" in r.message]
        assert errors
        msg = errors[0].message
        assert "j-loud" in msg and "w-loud" in msg and "attempt=2" in msg

    @pytest.mark.asyncio
    async def test_pure_read_failure_logs_warning(self, dead_db, caplog):
        with caplog.at_level(logging.WARNING, logger="agno"):
            job = await dead_db.get_job("j-read")
        assert job is None
        warnings = [r for r in caplog.records if "get_job failed" in r.message]
        assert warnings and warnings[0].levelno == logging.WARNING
        assert "j-read" in warnings[0].message
