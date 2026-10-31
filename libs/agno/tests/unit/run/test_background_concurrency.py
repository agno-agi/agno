"""Unit tests for the background run concurrency limiter."""

import asyncio

import pytest

from agno.run import concurrency
from agno.run.concurrency import (
    DEFAULT_BACKGROUND_MAX_CONCURRENCY,
    background_run_slot,
    get_background_max_concurrency,
    set_background_max_concurrency,
)


@pytest.fixture(autouse=True)
def reset_limiter():
    set_background_max_concurrency(None)
    concurrency._semaphores.clear()
    try:
        yield
    finally:
        set_background_max_concurrency(None)
        concurrency._semaphores.clear()


class TestConfiguration:
    def test_default_limit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("AGNO_BACKGROUND_MAX_CONCURRENCY", raising=False)
        assert get_background_max_concurrency() == DEFAULT_BACKGROUND_MAX_CONCURRENCY

    def test_env_var_limit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "5")
        assert get_background_max_concurrency() == 5

    def test_invalid_env_var_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "not-a-number")
        assert get_background_max_concurrency() == DEFAULT_BACKGROUND_MAX_CONCURRENCY

    def test_programmatic_limit_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "5")
        set_background_max_concurrency(2)
        assert get_background_max_concurrency() == 2

    def test_reset_to_none_restores_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "7")
        set_background_max_concurrency(3)
        set_background_max_concurrency(None)
        assert get_background_max_concurrency() == 7


class TestBackgroundRunSlot:
    @pytest.mark.asyncio
    async def test_caps_concurrent_execution(self):
        """With limit 2, at most 2 slots are held at once across 6 tasks."""
        set_background_max_concurrency(2)

        active = 0
        max_active = 0

        async def job():
            nonlocal active, max_active
            async with background_run_slot():
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*[job() for _ in range(6)])

        assert max_active == 2

    @pytest.mark.asyncio
    async def test_all_jobs_complete(self):
        """Jobs beyond the cap wait for a slot and still complete."""
        set_background_max_concurrency(1)

        completed: list[int] = []

        async def job(i: int):
            async with background_run_slot():
                await asyncio.sleep(0.01)
                completed.append(i)

        await asyncio.gather(*[job(i) for i in range(4)])

        assert sorted(completed) == [0, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_zero_limit_disables_limiting(self):
        """Limit 0 means unlimited: all tasks run concurrently."""
        set_background_max_concurrency(0)

        active = 0
        max_active = 0

        async def job():
            nonlocal active, max_active
            async with background_run_slot():
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*[job() for _ in range(5)])

        assert max_active == 5

    @pytest.mark.asyncio
    async def test_limit_change_applies_to_new_acquisitions(self):
        """Changing the limit rebuilds the semaphore for subsequent acquisitions."""
        set_background_max_concurrency(1)
        async with background_run_slot():
            pass

        set_background_max_concurrency(3)

        active = 0
        max_active = 0

        async def job():
            nonlocal active, max_active
            async with background_run_slot():
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*[job() for _ in range(5)])

        assert max_active == 3

    @pytest.mark.asyncio
    async def test_slot_released_on_exception(self):
        """A failing job releases its slot so later jobs can run."""
        set_background_max_concurrency(1)

        with pytest.raises(ValueError):
            async with background_run_slot():
                raise ValueError("boom")

        done = False
        async with background_run_slot():
            done = True
        assert done is True


class TestCancellationWhileWaiting:
    @pytest.fixture(autouse=True)
    def reset_cancellation_manager(self):
        from agno.run.cancel import get_cancellation_manager, set_cancellation_manager
        from agno.run.cancellation_management.in_memory_cancellation_manager import (
            InMemoryRunCancellationManager,
        )

        original = get_cancellation_manager()
        set_cancellation_manager(InMemoryRunCancellationManager())
        try:
            yield
        finally:
            set_cancellation_manager(original)

    @pytest.mark.asyncio
    async def test_cancelled_before_wait_raises_immediately(self):
        from agno.exceptions import RunCancelledException
        from agno.run.cancel import cancel_run

        set_background_max_concurrency(1)
        cancel_run("cancelled-run")

        with pytest.raises(RunCancelledException):
            async with background_run_slot(run_id="cancelled-run"):
                pytest.fail("slot body must not execute for a cancelled run")

    @pytest.mark.asyncio
    async def test_cancel_while_waiting_raises_and_frees_no_slot(self):
        """A run cancelled while queued raises RunCancelledException without
        consuming a slot, and the slot holder is unaffected."""
        from agno.exceptions import RunCancelledException
        from agno.run.cancel import cancel_run, register_run

        set_background_max_concurrency(1)

        release_holder = asyncio.Event()
        holder_started = asyncio.Event()

        async def holder():
            async with background_run_slot():
                holder_started.set()
                await release_holder.wait()

        async def waiter():
            async with background_run_slot(run_id="queued-run", cancellation_poll_interval=0.02):
                pytest.fail("cancelled waiter must never execute")

        register_run("queued-run")
        holder_task = asyncio.create_task(holder())
        await holder_started.wait()
        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)  # let the waiter start waiting on the semaphore

        cancel_run("queued-run")
        with pytest.raises(RunCancelledException):
            await asyncio.wait_for(waiter_task, timeout=2)

        # The slot holder is unaffected and the slot is still usable afterwards
        release_holder.set()
        await asyncio.wait_for(holder_task, timeout=2)
        async with background_run_slot(run_id="fresh-run", cancellation_poll_interval=0.02):
            pass

    @pytest.mark.asyncio
    async def test_uncancelled_run_acquires_after_wait(self):
        """A run that is never cancelled acquires the slot once it frees up."""
        set_background_max_concurrency(1)

        release_holder = asyncio.Event()
        holder_started = asyncio.Event()
        executed = asyncio.Event()

        async def holder():
            async with background_run_slot():
                holder_started.set()
                await release_holder.wait()

        async def waiter():
            async with background_run_slot(run_id="patient-run", cancellation_poll_interval=0.02):
                executed.set()

        holder_task = asyncio.create_task(holder())
        await holder_started.wait()
        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        assert not executed.is_set()

        release_holder.set()
        await asyncio.wait_for(waiter_task, timeout=2)
        assert executed.is_set()
        await asyncio.wait_for(holder_task, timeout=2)


class TestQueueConfig:
    def test_default_is_none_not_a_number(self):
        """None means "leave the process setting (env var or library default)
        untouched" - a config constructed to set other fields must never
        silently reset the cap. The effective fallback remains
        DEFAULT_BACKGROUND_MAX_CONCURRENCY via the limiter itself."""
        from agno.job_queue import QueueConfig

        assert QueueConfig().max_concurrency is None
        assert get_background_max_concurrency() == DEFAULT_BACKGROUND_MAX_CONCURRENCY

    def test_config_value_applies_via_setter(self):
        from agno.job_queue import QueueConfig

        config = QueueConfig(max_concurrency=4)
        set_background_max_concurrency(config.max_concurrency)
        assert get_background_max_concurrency() == 4


class TestQueueConfigEnvPrecedence:
    def test_default_config_leaves_env_var_alone(self, monkeypatch: pytest.MonkeyPatch):
        """QueueConfig() without an explicit max_concurrency must NOT
        override AGNO_BACKGROUND_MAX_CONCURRENCY (a config constructed to set
        other fields should not silently reset the cap)."""
        from agno.job_queue import QueueConfig

        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "8")
        config = QueueConfig()
        assert config.max_concurrency is None
        # Mirror the AgentOS wiring: only set when explicitly configured
        if config.max_concurrency is not None:
            set_background_max_concurrency(config.max_concurrency)
        assert get_background_max_concurrency() == 8

    def test_explicit_config_wins_over_env_var(self, monkeypatch: pytest.MonkeyPatch):
        from agno.job_queue import QueueConfig

        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "8")
        config = QueueConfig(max_concurrency=4)
        if config.max_concurrency is not None:
            set_background_max_concurrency(config.max_concurrency)
        assert get_background_max_concurrency() == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_task_execution_provider_keeps_independent_claims(tmp_path, asynchronous):
    from agno.company.execution import _call
    from agno.company.manager import AsyncCompanyManager, CompanyManager
    from agno.db.schemas.tasks import TASK_EXECUTION_CLAIMS
    from agno.db.sqlite import AsyncSqliteDb, SqliteDb

    db = (AsyncSqliteDb if asynchronous else SqliteDb)(db_file=str(tmp_path / "claims.db"))
    manager = (AsyncCompanyManager if asynchronous else CompanyManager)(db)
    product = await _call(manager, "create", name="Runtime")
    project = await _call(manager, "create_project", product_id=product["id"], name="Review")
    task = await _call(manager, "create_task", product_id=product["id"], project_id=project["id"], title="Draft")
    assert hasattr(concurrency, "_TaskExecutionProvider"), "Runtime execution provider is missing"
    provider = concurrency._TaskExecutionProvider(db)
    await provider.ainitialize()
    try:
        for cycle in range(2):
            first, second = f"first-{cycle}", f"second-{cycle}"
            assert await provider.aacquire(task["session_id"], first) == [task["id"]]
            assert await asyncio.to_thread(provider.acquire, task["session_id"], second) == [task["id"]]
            await provider.arelease(task["session_id"], first)
            row = await _call(db, "get_task", task["id"])
            assert row["metadata"][TASK_EXECUTION_CLAIMS] == [second]
            await asyncio.to_thread(provider.release, task["session_id"], second)
            assert not (await _call(db, "get_task", task["id"]))["metadata"].get(TASK_EXECUTION_CLAIMS)
    finally:
        await provider.aclose()
        await _call(db, "close")


@pytest.mark.asyncio
async def test_task_execution_provider_opaque_async_database_stays_on_own_loop(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine

    from agno.db.sqlite import AsyncSqliteDb

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    db = AsyncSqliteDb(db_engine=engine, db_url="sqlite+aiosqlite:///must-not-be-used.db")
    assert hasattr(concurrency, "_TaskExecutionProvider"), "Runtime execution provider is missing"
    provider = concurrency._TaskExecutionProvider(db)
    await provider.ainitialize()
    try:
        assert await provider.aacquire("unrelated", "first") == []
        with pytest.raises(RuntimeError, match="async calling path"):
            provider.acquire("unrelated", "second")
        with pytest.raises(RuntimeError, match="owning event loop"):
            await asyncio.to_thread(lambda: asyncio.run(provider.aacquire("unrelated", "third")))
    finally:
        await provider.aclose()
        # Provider must not close an injected engine owned by the application.
        assert await db.acquire_task_execution("unrelated", "fourth") == []
        await db.close()


@pytest.mark.asyncio
async def test_task_execution_provider_checks_partial_capability():
    from agno.db.in_memory import InMemoryDb

    assert hasattr(concurrency, "_TaskExecutionProvider"), "Runtime execution provider is missing"
    provider = concurrency._TaskExecutionProvider(InMemoryDb())
    await provider.ainitialize()
    assert await provider.aacquire("unrelated", "unused") == []
    await provider.aclose()

    class PartialCompanyDb(InMemoryDb):
        def create_task(self, task_data, reuse=False):
            return task_data

    with pytest.raises(NotImplementedError, match="execution guard"):
        concurrency._TaskExecutionProvider(PartialCompanyDb())


@pytest.mark.asyncio
async def test_task_execution_provider_requires_external_table(tmp_path):
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "external.db"))
    provider = concurrency._TaskExecutionProvider(db, auto_provision=False)
    try:
        with pytest.raises(RuntimeError, match="Tasks table"):
            await provider.ainitialize()
    finally:
        await provider.aclose()
        db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("synchronous", [False, True])
async def test_task_execution_provider_shutdown_drains_owned_write(tmp_path, synchronous):
    import threading

    from agno.db.sqlite import AsyncSqliteDb

    db = AsyncSqliteDb(db_file=str(tmp_path / "drain.db"))
    provider = concurrency._TaskExecutionProvider(db)
    await provider.ainitialize()
    entered, finish = threading.Event(), threading.Event()
    original = provider._owned_db.acquire_task_execution

    async def acquire(*args, **kwargs):
        entered.set()
        await asyncio.to_thread(finish.wait)
        return await original(*args, **kwargs)

    provider._owned_db.acquire_task_execution = acquire
    if synchronous:
        thread = threading.Thread(target=provider.acquire, args=("unrelated", "draining"), daemon=True)
        thread.start()
        write = None
    else:
        write = asyncio.create_task(provider.aacquire("unrelated", "draining"))
    assert await asyncio.to_thread(entered.wait, 3)
    closing = asyncio.create_task(provider.aclose())
    try:
        await asyncio.sleep(0.03)
        assert not closing.done(), "provider closed before the admitted write finished"
    finally:
        finish.set()
        # Avoid hanging a failing implementation whose loop already stopped.
        if write is not None and closing.done():
            write.cancel()
        await asyncio.gather(*([write] if write is not None else []), closing, return_exceptions=True)
        if synchronous:
            thread.join(timeout=0.1)
        await db.close()


@pytest.mark.asyncio
async def test_task_execution_provider_failed_init_disposes_owned_loop(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    db = AsyncSqliteDb(db_file=str(tmp_path / "missing-table.db"))
    provider = concurrency._TaskExecutionProvider(db, auto_provision=False)
    try:
        with pytest.raises(RuntimeError, match="Tasks table"):
            await provider.ainitialize()
        assert not provider._thread.is_alive(), "failed startup left its owned database loop running"
    finally:
        await provider.aclose()
        await db.close()


@pytest.mark.asyncio
async def test_task_execution_provider_initialization_is_shared(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine

    from agno.db.sqlite import AsyncSqliteDb

    db = AsyncSqliteDb(db_engine=create_async_engine("sqlite+aiosqlite:///:memory:"))
    entered, finish = asyncio.Event(), asyncio.Event()
    original = db._get_table
    calls = 0

    async def get_table(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await finish.wait()
        return await original(*args, **kwargs)

    db._get_table = get_table
    provider = concurrency._TaskExecutionProvider(db)
    first = asyncio.create_task(provider.ainitialize())
    await entered.wait()
    second = asyncio.create_task(provider.ainitialize())
    await asyncio.sleep(0)
    assert not second.done()
    assert calls == 1
    finish.set()
    await asyncio.gather(first, second)
    await provider.aclose()
    await db.close()


@pytest.mark.asyncio
async def test_task_execution_provider_close_waits_for_initialization(tmp_path, monkeypatch):
    from agno.db.sqlite import AsyncSqliteDb

    db = AsyncSqliteDb(db_file=str(tmp_path / "initializing.db"))
    provider = concurrency._TaskExecutionProvider(db)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = provider._initialize

    async def initialize():
        entered.set()
        await finish.wait()
        await original()

    monkeypatch.setattr(provider, "_initialize", initialize)
    initializing = asyncio.create_task(provider.ainitialize())
    await entered.wait()
    closing = asyncio.create_task(provider.aclose())
    try:
        await asyncio.sleep(0.02)
        assert not closing.done()
    finally:
        finish.set()
        await asyncio.gather(initializing, closing, return_exceptions=True)
        if provider._thread is not None and provider._thread.is_alive():
            provider._loop.call_soon_threadsafe(provider._loop.stop)
            await asyncio.to_thread(provider._thread.join)
        await db.close()
    assert not provider._thread.is_alive()


@pytest.mark.asyncio
async def test_task_stream_can_be_closed_by_another_task(tmp_path):
    from agno.company.manager import CompanyManager
    from agno.db.schemas.tasks import TASK_EXECUTION_CLAIMS
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "stream-close.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Streams")
    project = manager.create_project(product_id=product["id"], name="Draft")
    task = manager.create_task(product_id=product["id"], project_id=project["id"], title="Work")
    provider = concurrency._TaskExecutionProvider(db)
    await provider.ainitialize()

    class Producer:
        @concurrency.guard_task_execution()
        async def stream(self, session_id):
            yield "first"
            yield "second"

    try:
        for _ in range(2):
            with concurrency.task_execution_scope(provider):
                iterator = Producer().stream(task["session_id"])
            assert await iterator.__anext__() == "first"
            assert (db.get_task(task["id"])["metadata"] or {}).get(TASK_EXECUTION_CLAIMS)
            await asyncio.create_task(iterator.aclose())
            assert not (db.get_task(task["id"])["metadata"] or {}).get(TASK_EXECUTION_CLAIMS)
            assert concurrency.current_task_execution() is None
    finally:
        await provider.aclose()
        db.close()


@pytest.mark.asyncio
async def test_task_execution_bridge_preserves_relative_file_and_table(tmp_path, monkeypatch):
    from agno.company.manager import AsyncCompanyManager
    from agno.db.sqlite import AsyncSqliteDb

    monkeypatch.chdir(tmp_path)
    db = AsyncSqliteDb(db_file="relative.db", tasks_table="custom_tasks")
    manager = AsyncCompanyManager(db)
    product = await manager.create(name="Relative")
    project = await manager.create_project(product_id=product["id"], name="Draft")
    task = await manager.create_task(product_id=product["id"], project_id=project["id"], title="Work")
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    provider = concurrency._TaskExecutionProvider(db)
    await provider.ainitialize()
    try:
        for token in ("first", "second"):
            assert await asyncio.to_thread(provider.acquire, task["session_id"], token) == [task["id"]]
            await provider.arelease(task["session_id"], token)
        assert not (other / "relative.db").exists()
    finally:
        await provider.aclose()
        await db.close()


@pytest.mark.asyncio
async def test_task_execution_custom_async_adapter_is_not_cloned(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    class CustomDb(AsyncSqliteDb):
        def __init__(self, required_setting, **kwargs):
            super().__init__(**kwargs)
            self.required_setting = required_setting

    db = CustomDb("custom", db_file=str(tmp_path / "custom.db"))
    provider = concurrency._TaskExecutionProvider(db)
    await provider.ainitialize()
    try:
        assert provider._owned_db is None
        assert await provider.aacquire("ordinary", "first") == []
        with pytest.raises(RuntimeError, match="async calling path"):
            provider.acquire("ordinary", "second")
    finally:
        await provider.aclose()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("separate_task", [False, True])
async def test_retained_child_claim_survives_all_outer_wrappers(tmp_path, separate_task):
    from agno.company.manager import CompanyManager
    from agno.db.schemas.tasks import TASK_EXECUTION_CLAIMS
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "retained-child.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Retained")
    project = manager.create_project(product_id=product["id"], name="Draft")
    task = manager.create_task(product_id=product["id"], project_id=project["id"], title="Root")
    child = (
        manager.create_task(product_id=product["id"], project_id=project["id"], title="Child")
        if separate_task
        else None
    )
    provider = concurrency._TaskExecutionProvider(db)
    await provider.ainitialize()

    class Producer:
        @concurrency.guard_task_execution()
        async def root(self, session_id):
            await self.child(child["session_id"] if child else "derived-session")

        @concurrency.guard_task_execution()
        async def child(self, session_id):
            concurrency.retain_task_execution()
            concurrency.retain_task_execution()
            raise RuntimeError("could not confirm termination")

    try:
        for _ in range(2):
            with concurrency.task_execution_scope(provider):
                with pytest.raises(RuntimeError, match="confirm termination"):
                    await Producer().root(task["session_id"])
            for row in [task] + ([child] if child else []):
                tokens = (db.get_task(row["id"])["metadata"] or {}).get(TASK_EXECUTION_CLAIMS)
                assert len(tokens) == 1
                await provider.arelease(row["session_id"], tokens[0])
    finally:
        await provider.aclose()
        db.close()


@pytest.mark.asyncio
async def test_child_identity_refusal_releases_definitely_acquired_claim(tmp_path):
    from agno.company.manager import CompanyManager
    from agno.db.schemas.tasks import TASK_EXECUTION_CLAIMS
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "child-refusal.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Refusal")
    project = manager.create_project(product_id=product["id"], name="Draft")
    root = manager.create_task(product_id=product["id"], project_id=project["id"], title="Root")
    child = manager.create_task(product_id=product["id"], project_id=project["id"], title="Child")
    provider = concurrency._TaskExecutionProvider(db)
    await provider.ainitialize()

    class Producer:
        @concurrency.guard_task_execution()
        def prepare(self, session_id):
            return self.stream(child["session_id"])

        @concurrency.guard_task_execution()
        async def stream(self, session_id):
            yield "must not execute"

    try:
        with concurrency.task_execution_scope(provider):
            iterator = Producer().prepare(root["session_id"])
        table = db._get_table("tasks")
        with db.Session() as session, session.begin():
            session.execute(table.delete().where(table.c.id == root["id"]))
        with pytest.raises(ValueError, match="identity changed"):
            await iterator.__anext__()
        assert not (db.get_task(child["id"])["metadata"] or {}).get(TASK_EXECUTION_CLAIMS)
    finally:
        await provider.aclose()
        db.close()


def test_new_task_execution_scope_does_not_inherit_previous_producer():
    producer = concurrency._task_execution_producer.set(("old", "session", ("task",), {}))
    claim = concurrency._task_execution_claim.set({"owners": [("old", "session", ("task",))]})
    try:
        for _ in range(2):
            with concurrency.task_execution_scope(None):
                assert concurrency.current_task_execution() is None
                assert concurrency._task_execution_claim.get() is None
            assert concurrency.current_task_execution()[0] == "old"
    finally:
        concurrency._task_execution_claim.reset(claim)
        concurrency._task_execution_producer.reset(producer)
