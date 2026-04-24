"""Tests for fire-and-forget learning extraction.

Verifies that:
1. Learning does not block RunCompleted / run return
2. Learning is serialised (FIFO) across consecutive runs
3. Learning uses a dedicated executor (not the shared background_executor)
4. Learning future/task is not cancelled in finally blocks
5. Works for both Agent and Team
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeLearningMachine:
    """A mock LearningMachine that records process calls with timing."""

    def __init__(self, delay: float = 0.0):
        self.calls: list = []
        self.delay = delay
        self.process_running = threading.Event()
        self._lock = threading.Lock()

    def process(self, messages, **kwargs):
        with self._lock:
            self.process_running.set()
            self.calls.append({"messages": list(messages), "kwargs": kwargs, "thread": threading.current_thread().name})
        if self.delay:
            time.sleep(self.delay)

    async def aprocess(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), "kwargs": kwargs})
        if self.delay:
            await asyncio.sleep(self.delay)


class FakeDb:
    """Minimal fake DB for agent/team init."""

    def get_session(self, **kwargs):
        return None

    def upsert_session(self, **kwargs):
        pass

    def get_learning(self, **kwargs):
        return None

    def upsert_learning(self, **kwargs):
        pass


def _make_agent_with_learning(learning_delay: float = 0.0):
    """Create a minimal Agent with learning configured."""
    from agno.agent.agent import Agent

    fake_learning = FakeLearningMachine(delay=learning_delay)
    agent = Agent(name="test-agent", db=FakeDb())
    agent._learning = fake_learning
    agent._learning_init_attempted = True
    return agent, fake_learning


def _make_team_with_learning(learning_delay: float = 0.0):
    """Create a minimal Team with learning configured."""
    from agno.team.team import Team

    fake_learning = FakeLearningMachine(delay=learning_delay)
    team = Team(name="test-team", members=[], db=FakeDb())
    team._learning = fake_learning
    team._learning_init_attempted = True
    return team, fake_learning


# ---------------------------------------------------------------------------
# Test: Agent has dedicated learning_executor
# ---------------------------------------------------------------------------


class TestAgentLearningExecutor:
    def test_learning_executor_is_separate_from_background(self):
        from agno.agent.agent import Agent

        agent = Agent(name="test")
        bg = agent.background_executor
        le = agent.learning_executor

        assert bg is not le
        assert isinstance(le, ThreadPoolExecutor)
        assert isinstance(bg, ThreadPoolExecutor)

    def test_learning_executor_is_single_threaded(self):
        from agno.agent.agent import Agent

        agent = Agent(name="test")
        le = agent.learning_executor
        # max_workers=1 for FIFO serialisation
        assert le._max_workers == 1

    def test_learning_executor_is_lazy(self):
        from agno.agent.agent import Agent

        agent = Agent(name="test")
        assert agent._learning_executor is None
        _ = agent.learning_executor
        assert agent._learning_executor is not None

    def test_learning_lock_is_asyncio_lock(self):
        from agno.agent.agent import Agent

        agent = Agent(name="test")
        lock = agent.learning_lock
        assert isinstance(lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# Test: Team has dedicated learning_executor
# ---------------------------------------------------------------------------


class TestTeamLearningExecutor:
    def test_team_learning_executor_properties(self):
        from concurrent.futures import ThreadPoolExecutor

        from agno.team._init import learning_executor, learning_lock
        from agno.team.team import Team

        team = Team(name="test", members=[])
        assert team._learning_executor is None
        assert team._learning_lock is None

        le = learning_executor(team)
        assert isinstance(le, ThreadPoolExecutor)
        assert le._max_workers == 1

        lock = learning_lock(team)
        assert isinstance(lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# Test: wait_for_open_threads does NOT wait for learning
# ---------------------------------------------------------------------------


class TestWaitFunctionsSkipLearning:
    def test_sync_wait_ignores_learning_future(self):
        """wait_for_open_threads should not wait on learning_future."""
        from agno.utils.agent import wait_for_open_threads

        # A future that would block if waited upon
        blocking_future = ThreadPoolExecutor(max_workers=1).submit(time.sleep, 5)
        try:
            # If this waits, it would take 5 seconds. Should return instantly.
            start = time.monotonic()
            wait_for_open_threads(learning_future=blocking_future)
            elapsed = time.monotonic() - start
            assert elapsed < 1.0, f"wait_for_open_threads blocked for {elapsed:.1f}s (should skip learning)"
        finally:
            blocking_future.cancel()

    def test_async_wait_ignores_learning_task(self):
        """await_for_open_threads should not await learning_task."""
        from agno.utils.agent import await_for_open_threads

        async def slow_learning():
            await asyncio.sleep(5)

        async def run_test():
            task = asyncio.create_task(slow_learning())
            try:
                start = time.monotonic()
                await await_for_open_threads(learning_task=task)
                elapsed = time.monotonic() - start
                assert elapsed < 1.0, f"await_for_open_threads blocked for {elapsed:.1f}s"
            finally:
                task.cancel()

        asyncio.get_event_loop().run_until_complete(run_test())

    def test_sync_stream_wait_ignores_learning(self):
        """wait_for_thread_tasks_stream should not wait on learning_future."""
        from agno.utils.agent import wait_for_thread_tasks_stream

        blocking_future = ThreadPoolExecutor(max_workers=1).submit(time.sleep, 5)
        try:
            start = time.monotonic()
            list(wait_for_thread_tasks_stream(
                run_response=MagicMock(),
                learning_future=blocking_future,
            ))
            elapsed = time.monotonic() - start
            assert elapsed < 1.0
        finally:
            blocking_future.cancel()

    def test_async_stream_wait_ignores_learning(self):
        """await_for_thread_tasks_stream should not await learning_task."""
        from agno.utils.agent import await_for_thread_tasks_stream

        async def slow_learning():
            await asyncio.sleep(5)

        async def run_test():
            task = asyncio.create_task(slow_learning())
            try:
                start = time.monotonic()
                async for _ in await_for_thread_tasks_stream(
                    run_response=MagicMock(),
                    learning_task=task,
                ):
                    pass
                elapsed = time.monotonic() - start
                assert elapsed < 1.0
            finally:
                task.cancel()

        asyncio.get_event_loop().run_until_complete(run_test())


# ---------------------------------------------------------------------------
# Test: FIFO serialisation via dedicated executor
# ---------------------------------------------------------------------------


class TestFIFOSerialisation:
    def test_sync_learning_is_serialised(self):
        """Two learning tasks submitted to the learning_executor run sequentially."""
        agent, fake_learning = _make_agent_with_learning(learning_delay=0.1)
        fake_learning.delay = 0.1  # Each process call takes 0.1s

        executor = agent.learning_executor

        # Submit two tasks
        f1 = executor.submit(fake_learning.process, ["msg1"])
        f2 = executor.submit(fake_learning.process, ["msg2"])

        # Both should complete
        f1.result(timeout=5)
        f2.result(timeout=5)

        # They should have run in order
        assert len(fake_learning.calls) == 2
        assert fake_learning.calls[0]["messages"] == ["msg1"]
        assert fake_learning.calls[1]["messages"] == ["msg2"]

    def test_async_learning_is_serialised(self):
        """Two async learning tasks guarded by learning_lock run sequentially."""
        agent, fake_learning = _make_agent_with_learning(learning_delay=0.1)

        execution_order = []

        async def tracked_process(messages):
            execution_order.append(f"start-{messages[0]}")
            await fake_learning.aprocess(messages)
            execution_order.append(f"end-{messages[0]}")

        async def run_test():
            lock = agent.learning_lock
            # Task 1 acquires lock first
            t1 = asyncio.create_task(_locked_aprocess(lock, tracked_process, ["msg1"]))
            # Small delay to ensure t1 starts first
            await asyncio.sleep(0.01)
            t2 = asyncio.create_task(_locked_aprocess(lock, tracked_process, ["msg2"]))

            await asyncio.gather(t1, t2)

        asyncio.get_event_loop().run_until_complete(run_test())

        # Should be strictly sequential: start1, end1, start2, end2
        assert execution_order == ["start-msg1", "end-msg1", "start-msg2", "end-msg2"]


async def _locked_aprocess(lock, process_fn, messages):
    async with lock:
        await process_fn(messages)


# ---------------------------------------------------------------------------
# Test: process_learnings_with_messages uses snapshot
# ---------------------------------------------------------------------------


class TestProcessWithSnapshot:
    def test_sync_process_uses_message_snapshot(self):
        """_process_learnings_with_messages should use pre-snapshot messages."""
        from agno.agent._managers import _process_learnings_with_messages

        agent, fake_learning = _make_agent_with_learning()

        snapshot = ["msg1", "msg2"]
        _process_learnings_with_messages(agent, messages=snapshot, session_id="s1", user_id="u1")

        assert len(fake_learning.calls) == 1
        assert fake_learning.calls[0]["messages"] == ["msg1", "msg2"]

    def test_sync_process_handles_none_learning(self):
        """Should gracefully handle agent with no learning."""
        from agno.agent.agent import Agent
        from agno.agent._managers import _process_learnings_with_messages

        agent = Agent(name="test")
        agent._learning = None
        # Should not raise
        _process_learnings_with_messages(agent, messages=[], session_id="s1", user_id="u1")

    def test_sync_process_handles_exception(self):
        """Should log warning, not propagate exception."""
        from agno.agent._managers import _process_learnings_with_messages
        from agno.agent.agent import Agent

        agent = Agent(name="test")
        failing_learning = MagicMock()
        failing_learning.process.side_effect = RuntimeError("DB error")
        agent._learning = failing_learning

        # Should not raise
        _process_learnings_with_messages(agent, messages=["msg"], session_id="s1", user_id="u1")

    @pytest.mark.asyncio
    async def test_async_process_uses_message_snapshot(self):
        """_aprocess_learnings_with_messages should use pre-snapshot messages."""
        from agno.agent._managers import _aprocess_learnings_with_messages

        agent, fake_learning = _make_agent_with_learning()

        snapshot = ["msg1", "msg2"]
        await _aprocess_learnings_with_messages(agent, messages=snapshot, session_id="s1", user_id="u1")

        assert len(fake_learning.calls) == 1
        assert fake_learning.calls[0]["messages"] == ["msg1", "msg2"]

    @pytest.mark.asyncio
    async def test_async_process_handles_exception(self):
        """Should log warning, not propagate exception."""
        from agno.agent._managers import _aprocess_learnings_with_messages
        from agno.agent.agent import Agent

        agent = Agent(name="test")
        failing_learning = MagicMock()
        failing_learning.aprocess.side_effect = RuntimeError("DB error")
        agent._learning = failing_learning
        # Ensure lock is created in the current event loop
        _ = agent.learning_lock

        # Should not raise
        await _aprocess_learnings_with_messages(agent, messages=["msg"], session_id="s1", user_id="u1")


# ---------------------------------------------------------------------------
# Test: Team managers
# ---------------------------------------------------------------------------


class TestTeamManagers:
    def test_team_process_with_snapshot(self):
        """_process_learnings_with_messages should work for team."""
        from agno.team._managers import _process_learnings_with_messages

        team, fake_learning = _make_team_with_learning()

        _process_learnings_with_messages(team, messages=["msg1"], session_id="s1", user_id="u1")

        assert len(fake_learning.calls) == 1
        assert fake_learning.calls[0]["kwargs"]["team_id"] == team.id

    @pytest.mark.asyncio
    async def test_team_async_process_with_snapshot(self):
        """_aprocess_learnings_with_messages should work for team."""
        from agno.team._managers import _aprocess_learnings_with_messages

        team, fake_learning = _make_team_with_learning()

        await _aprocess_learnings_with_messages(team, messages=["msg1"], session_id="s1", user_id="u1")

        assert len(fake_learning.calls) == 1
        assert fake_learning.calls[0]["kwargs"]["team_id"] == team.id


# ---------------------------------------------------------------------------
# Test: collect_background_metrics still works without learning
# ---------------------------------------------------------------------------


class TestCollectBackgroundMetrics:
    def test_collects_memory_only(self):
        from agno.utils.agent import collect_background_metrics
        from concurrent.futures import ThreadPoolExecutor

        from agno.metrics import RunMetrics

        collector = RunMetrics()
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(lambda: collector)

        result = collect_background_metrics(future)
        assert len(result) == 1
        assert isinstance(result[0], RunMetrics)

    def test_ignores_none(self):
        from agno.utils.agent import collect_background_metrics

        result = collect_background_metrics(None, None)
        assert result == []
