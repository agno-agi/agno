"""Independent executors share Product review admission on every Company database."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from agno.company.review_lock import _claim_review, _review_filesystem
from agno.db.base import AsyncBaseDb
from agno.fs import FileSystem
from tests.integration.db.test_company_playbook_parity import db as company_db

db = company_db


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [False, True])
async def test_review_claim_is_atomic_across_database_connections(db, monkeypatch, completed):
    if hasattr(db, "db_schema"):
        peer = type(db)(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=db.db_schema)
    else:
        peer = type(db)(db_file=db.db_file)
    schedule = SimpleNamespace(id="review-one", endpoint="/agents/reviewer/runs", user_id="alice")
    other = SimpleNamespace(id="review-two", endpoint="/agents/reviewer/runs", user_id="bob")
    client = SimpleNamespace(request=AsyncMock(return_value=httpx.Response(200, json={"status": "COMPLETED"})))
    executors = [
        SimpleNamespace(
            company_db=adapter,
            base_url="http://test",
            internal_service_token="test",
            _get_client=AsyncMock(return_value=client),
        )
        for adapter in (db, peer)
    ]
    # Initialize filesystem tables outside the race; then force both contenders to read the same version.
    await _review_filesystem(db, "initialize").awrite("review.md", "{}", expected_version=0)
    original_read = FileSystem.aread_with_meta
    readers = 0
    both_read = asyncio.Event()

    async def read_together(self, *args, **kwargs):
        nonlocal readers
        result = await original_read(self, *args, **kwargs)
        readers += 1
        if readers % 2 == 0:
            both_read.set()
        await asyncio.wait_for(both_read.wait(), 10)
        return result

    monkeypatch.setattr(FileSystem, "aread_with_meta", read_together)
    try:
        for index in range(10):
            both_read.clear()
            if completed:
                await _review_filesystem(db, "product-" + str(index)).awrite(
                    "review.md",
                    json.dumps({"run_id": "old", "session_id": "old-session", "endpoint": schedule.endpoint}),
                    expected_version=0,
                )
            claims = await asyncio.gather(
                _claim_review(executors[0], schedule, "product-" + str(index)),
                _claim_review(executors[1], other, "product-" + str(index)),
                return_exceptions=True,
            )
            assert sum(isinstance(result, tuple) for result in claims) == 1, claims
            assert (
                sum(isinstance(result, ValueError) and "Another Routine review" in str(result) for result in claims)
                == 1
            ), claims
    finally:
        if isinstance(peer, AsyncBaseDb):
            await peer.close()
        else:
            peer.close()
