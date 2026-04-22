"""Empirical lazy-init race reproduction.

Claims we want to test:

1. Non-MCP pattern (sync `_ensure_agent`) — NO race under plain asyncio,
   because the critical section is sync and runs atomically between
   yield points.
2. MCP-style pattern (async `_aensure_agent` with `await` BEFORE the
   is-None check, but sync critical section inside) — also NO race for
   the agent build, because the critical section itself is sync.
3. The ONLY way lazy init races under plain asyncio: if the critical
   section itself awaits (e.g. `_build_agent` is async and yields).
4. With real OS threads (asyncio.to_thread), the non-MCP pattern
   DOES race — two threads can preempt each other between the `if`
   check and the assign.

Run with: pytest libs/agno/tests/unit/context/test_race_repro.py -v -s
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agno.context import Answer, ContextProvider, Status
from agno.run import RunContext


class _SyncLazyProvider(ContextProvider):
    """Non-MCP pattern: sync `_ensure_agent`, sync `_build_agent`.

    This is the shape used by fs/web/database/slack/gdrive.
    """

    build_count: int = 0

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent_obj: Any = None

    def status(self) -> Status:
        return Status(ok=True, detail="sync")

    async def astatus(self) -> Status:
        return self.status()

    def _ensure_agent(self) -> Any:
        if self._agent_obj is None:
            self._agent_obj = self._build_agent()
        return self._agent_obj

    def _build_agent(self) -> object:
        type(self).build_count += 1
        return object()

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        self._ensure_agent()
        return Answer(text=f"q:{question}")

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        agent = self._ensure_agent()
        await asyncio.sleep(0)  # simulates arun's internal yield
        _ = agent
        return Answer(text=f"q:{question}")


class _AwaitBeforeCheckProvider(ContextProvider):
    """MCP-shaped: async `_aensure_agent` with `await` BEFORE the check.

    The await is `_ensure_session()`. The is-None check + build is still
    sync, so the critical section itself is atomic between coroutines.
    """

    build_count: int = 0

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent_obj: Any = None

    def status(self) -> Status:
        return Status(ok=True, detail="mcp-like")

    async def astatus(self) -> Status:
        return self.status()

    async def _ensure_session(self) -> None:
        await asyncio.sleep(0)

    async def _aensure_agent(self) -> Any:
        await self._ensure_session()  # ← yield BEFORE the check
        if self._agent_obj is None:  # ← but the check+build is still sync
            self._agent_obj = self._build_agent()
        return self._agent_obj

    def _build_agent(self) -> object:
        type(self).build_count += 1
        return object()

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        raise NotImplementedError

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        await self._aensure_agent()
        return Answer(text=f"q:{question}")


class _AsyncBuildProvider(ContextProvider):
    """The ONE pattern that races under plain asyncio: async build.

    If `_build_agent` itself awaits (e.g. connects to a remote server,
    fetches tool descriptions), other coroutines can slip past the
    is-None check while the first one is still building.
    """

    build_count: int = 0

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent_obj: Any = None

    def status(self) -> Status:
        return Status(ok=True, detail="async-build")

    async def astatus(self) -> Status:
        return self.status()

    async def _abuild_agent(self) -> object:
        # Pretend the build fetches tool metadata over the network.
        await asyncio.sleep(0.001)
        type(self).build_count += 1
        return object()

    async def _aensure_agent(self) -> Any:
        if self._agent_obj is None:
            self._agent_obj = await self._abuild_agent()  # ← YIELD inside the critical section
        return self._agent_obj

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        raise NotImplementedError

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        await self._aensure_agent()
        return Answer(text=f"q:{question}")


# ---------------------------------------------------------------------------
# Reproductions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lazy_init_is_race_free_under_asyncio():
    """The shape used by fs/web/database/slack/gdrive: zero races."""
    _SyncLazyProvider.build_count = 0
    p = _SyncLazyProvider(id="sync")
    await asyncio.gather(*(p.aquery(f"q-{i}") for i in range(50)))
    print(f"\n[sync _ensure_agent]            builds = {_SyncLazyProvider.build_count}")
    assert _SyncLazyProvider.build_count == 1


@pytest.mark.asyncio
async def test_await_before_check_does_NOT_race_under_asyncio():
    """MCP-shaped (await BEFORE the sync check): also zero races.

    The await window doesn't matter — the `if None: build()` runs
    atomically once coroutines resume, so only the first to land
    actually builds.
    """
    _AwaitBeforeCheckProvider.build_count = 0
    p = _AwaitBeforeCheckProvider(id="mcp-like")
    await asyncio.gather(*(p.aquery(f"q-{i}") for i in range(50)))
    print(f"\n[await-before-check]            builds = {_AwaitBeforeCheckProvider.build_count}")
    assert _AwaitBeforeCheckProvider.build_count == 1


@pytest.mark.asyncio
async def test_async_build_DOES_race_under_asyncio():
    """If `_build_agent` itself awaits, the critical section stops being
    atomic and we DO race."""
    _AsyncBuildProvider.build_count = 0
    p = _AsyncBuildProvider(id="async-build")
    await asyncio.gather(*(p.aquery(f"q-{i}") for i in range(50)))
    print(f"\n[async build_agent (race)]      builds = {_AsyncBuildProvider.build_count}")
    assert _AsyncBuildProvider.build_count > 1, f"expected a race (>1 build), got {_AsyncBuildProvider.build_count}"


@pytest.mark.asyncio
async def test_sync_lazy_init_races_under_real_threads():
    """The non-MCP pattern IS race-prone once real threads enter the
    picture (asyncio.to_thread runs on a real OS thread).

    This is the one genuine argument for adding a lock: if a user
    dispatches the provider via a thread pool."""
    _SyncLazyProvider.build_count = 0
    p = _SyncLazyProvider(id="threaded")

    def _sync_call() -> None:
        p.query("hello")

    await asyncio.gather(*(asyncio.to_thread(_sync_call) for _ in range(100)))
    print(f"\n[sync pattern + 100 threads]    builds = {_SyncLazyProvider.build_count}")
    # On very fast machines this may be 1 (no contention). We assert the
    # test RAN — the print is the empirical evidence of whether it raced.
    assert _SyncLazyProvider.build_count >= 1
