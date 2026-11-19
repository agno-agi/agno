import asyncio
from unittest.mock import AsyncMock

import pytest

from agno.exceptions import EmbeddingError
from agno.knowledge.embedder.base import Embedder, aembed_texts_individually


@pytest.mark.asyncio
@pytest.mark.parametrize("setting,limit", [(None, 5), ("3", 3), ("1", 1), ("0", 1), ("-2", 1), ("invalid", 5)])
async def test_fallback_bounds_inflight_calls_and_preserves_order(monkeypatch, setting, limit):
    if setting is None:
        monkeypatch.delenv("EMBEDDER_FALLBACK_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("EMBEDDER_FALLBACK_CONCURRENCY", setting)
    started = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak = 0
    calls = []

    async def embed(text):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls.append(text)
        if active == limit:
            started.set()
        try:
            await release.wait()
            # Later inputs finish first, so completion order cannot determine slots.
            for _ in range(12 - int(text)):
                await asyncio.sleep(0)
            return [float(text)], {"tokens": int(text)}
        finally:
            active -= 1

    embedder = Embedder()
    embedder.async_get_embedding_and_usage = AsyncMock(side_effect=embed)
    task = asyncio.create_task(aembed_texts_individually(embedder, [str(i) for i in range(12)]))
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert len(calls) == limit
        release.set()
        embeddings, usages = await task
        assert embeddings == [[float(i)] for i in range(12)]
        assert usages == [{"tokens": i} for i in range(12)]
        assert peak == limit
        assert active == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("all_fail", [False, True])
async def test_failures_keep_input_positions_and_first_error(monkeypatch, all_fail):
    monkeypatch.setenv("EMBEDDER_FALLBACK_CONCURRENCY", "3")
    release_first = asyncio.Event()
    warnings = []
    monkeypatch.setattr("agno.knowledge.embedder.base.log_warning", warnings.append)

    async def embed(text):
        if text == "0":
            await release_first.wait()
        elif text == "2":
            release_first.set()
        if all_fail or text != "1":
            raise EmbeddingError(text, status_code=400 + int(text), model_id=text, provider="test")
        return [1.0], {"tokens": 1}

    embedder = Embedder()
    embedder.async_get_embedding_and_usage = AsyncMock(side_effect=embed)
    if all_fail:
        with pytest.raises(EmbeddingError) as error:
            await aembed_texts_individually(embedder, ["0", "1", "2"])
        assert error.value.provider_status_code == 400
        assert error.value.model_id == "0"
    else:
        assert await aembed_texts_individually(embedder, ["0", "1", "2"]) == (
            [[], [1.0], []],
            [None, {"tokens": 1}, None],
        )
        assert warnings == ["2 of 3 chunks failed to embed at position(s) 0, 2: 0"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_abort_settles_inflight_calls(monkeypatch, cancel):
    monkeypatch.setenv("EMBEDDER_FALLBACK_CONCURRENCY", "3")
    started = asyncio.Event()
    fail = asyncio.Event()
    active = 0
    calls = []

    async def embed(text):
        nonlocal active
        active += 1
        calls.append(text)
        if active == 3:
            started.set()
        try:
            if text == "0":
                await fail.wait()
                raise RuntimeError("unexpected")
            await asyncio.Event().wait()
        finally:
            active -= 1

    embedder = Embedder()
    embedder.async_get_embedding_and_usage = AsyncMock(side_effect=embed)
    task = asyncio.create_task(aembed_texts_individually(embedder, [str(i) for i in range(20)]))
    try:
        await asyncio.wait_for(started.wait(), 1)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            fail.set()
            with pytest.raises(RuntimeError, match="unexpected"):
                await task
        assert active == 0
        assert len(calls) == 3
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_empty_input_makes_no_calls():
    embedder = Embedder()
    embedder.async_get_embedding_and_usage = AsyncMock()
    assert await aembed_texts_individually(embedder, []) == ([], [])
    embedder.async_get_embedding_and_usage.assert_not_awaited()
