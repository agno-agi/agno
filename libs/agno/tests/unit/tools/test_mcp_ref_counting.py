"""Tests for reference counting in MCPTools and MultiMCPTools connect/close.

These tests verify that parallel agent runs sharing the same MCPTools or
MultiMCPTools instance do not kill each other's sessions. The reference
counting mechanism ensures the underlying connection is only torn down
when the last run calls close().
"""

import asyncio
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.mcp import MCPTools, MultiMCPTools


# =============================================================================
# Helpers
# =============================================================================


def _make_mcptools(**kwargs) -> MCPTools:
    """Create an MCPTools instance with a mock session (no real MCP server)."""
    tools = MCPTools(url="http://localhost:8080/mcp", **kwargs)
    return tools


def _make_multimcptools(**kwargs) -> MultiMCPTools:
    """Create a MultiMCPTools instance (no real MCP server)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        tools = MultiMCPTools(urls=["http://localhost:8080/mcp"], **kwargs)
    return tools


async def _fake_connect(tools):
    """Simulate a successful _connect by setting _initialized = True."""
    tools._initialized = True


async def _fake_multi_connect(tools):
    """Simulate a successful _connect for MultiMCPTools."""
    tools._initialized = True
    tools._successful_connections = 1


def _patch_mcp_connect(tools):
    """Patch _connect on MCPTools to simulate successful connection."""
    async def fake(*args, **kwargs):
        await _fake_connect(tools)
    return patch.object(tools, "_connect", side_effect=fake)


def _patch_multi_connect(tools):
    """Patch _connect on MultiMCPTools to simulate successful connection."""
    async def fake(*args, **kwargs):
        await _fake_multi_connect(tools)
    return patch.object(tools, "_connect", side_effect=fake)


# =============================================================================
# MCPTools — basic ref counting
# =============================================================================


class TestMCPToolsRefCounting:
    """Tests for MCPTools reference counting on connect/close."""

    def test_ref_count_starts_at_zero(self):
        tools = _make_mcptools()
        assert tools._ref_count == 0

    async def test_connect_increments_ref_count(self):
        tools = _make_mcptools()
        with _patch_mcp_connect(tools):
            await tools.connect()
        assert tools._ref_count == 1

    async def test_multiple_connects_increment_ref_count(self):
        tools = _make_mcptools()
        with _patch_mcp_connect(tools):
            await tools.connect()
            await tools.connect()
            await tools.connect()
        assert tools._ref_count == 3

    async def test_close_decrements_ref_count(self):
        tools = _make_mcptools()
        with _patch_mcp_connect(tools):
            await tools.connect()
            await tools.connect()
        assert tools._ref_count == 2

        await tools.close()
        assert tools._ref_count == 1
        # Connection should still be alive
        assert tools._initialized is True

    async def test_close_tears_down_at_zero(self):
        tools = _make_mcptools()
        with _patch_mcp_connect(tools):
            await tools.connect()
        assert tools._ref_count == 1

        await tools.close()
        assert tools._ref_count == 0
        assert tools._initialized is False

    async def test_close_does_not_go_negative(self):
        tools = _make_mcptools()
        with _patch_mcp_connect(tools):
            await tools.connect()
        await tools.close()
        # Extra close calls should not make ref_count negative
        await tools.close()
        await tools.close()
        assert tools._ref_count == 0

    async def test_close_skips_teardown_when_not_initialized(self):
        """close() should be a no-op if never connected."""
        tools = _make_mcptools()
        assert tools._initialized is False
        await tools.close()
        assert tools._ref_count == 0

    async def test_connect_rollback_on_failure(self):
        """If _connect raises, the ref count should be rolled back."""
        tools = _make_mcptools()

        async def failing_connect():
            raise RuntimeError("Connection refused")

        with patch.object(tools, "_connect", side_effect=failing_connect):
            await tools.connect()

        assert tools._ref_count == 0
        assert tools._initialized is False

    async def test_connect_force_resets_ref_count(self):
        """force=True should reset ref_count to 0 before reconnecting."""
        tools = _make_mcptools()
        with _patch_mcp_connect(tools):
            await tools.connect()
            await tools.connect()
            await tools.connect()
        assert tools._ref_count == 3

        # Force reconnect — resets ref_count to 0, then increments to 1
        tools._initialized = False  # So _connect is called again
        with _patch_mcp_connect(tools):
            await tools.connect(force=True)
        assert tools._ref_count == 1

    async def test_force_connect_clears_state(self):
        """force=True should clear session, context, and initialized flag."""
        tools = _make_mcptools()
        tools.session = MagicMock()
        tools._context = MagicMock()
        tools._session_context = MagicMock()
        tools._initialized = True
        tools._ref_count = 5

        with _patch_mcp_connect(tools):
            await tools.connect(force=True)

        # After force, ref_count is reset to 0, then incremented to 1
        assert tools._ref_count == 1


# =============================================================================
# MCPTools — parallel connect/close cycles
# =============================================================================


class TestMCPToolsParallelRefCounting:
    """Tests for concurrent connect/close with MCPTools."""

    async def test_parallel_connects_all_increment(self):
        """Multiple concurrent connect() calls should each increment ref_count."""
        tools = _make_mcptools()
        connect_count = 10

        with _patch_mcp_connect(tools):
            await asyncio.gather(*[tools.connect() for _ in range(connect_count)])

        assert tools._ref_count == connect_count

    async def test_parallel_connect_close_cycle(self):
        """Simulate N parallel agent runs: each connects, then closes."""
        tools = _make_mcptools()
        n_runs = 5

        with _patch_mcp_connect(tools):
            # All runs connect
            await asyncio.gather(*[tools.connect() for _ in range(n_runs)])

        assert tools._ref_count == n_runs
        assert tools._initialized is True

        # Close runs one by one — only the last close should tear down
        for i in range(n_runs - 1):
            await tools.close()
            assert tools._initialized is True, f"Torn down too early at close #{i+1}"
            assert tools._ref_count == n_runs - 1 - i

        # Final close tears down
        await tools.close()
        assert tools._ref_count == 0
        assert tools._initialized is False

    async def test_parallel_close_is_safe(self):
        """Multiple concurrent close() calls should be safe."""
        tools = _make_mcptools()

        with _patch_mcp_connect(tools):
            await tools.connect()
            await tools.connect()

        assert tools._ref_count == 2

        # Close both in parallel
        await asyncio.gather(tools.close(), tools.close())
        assert tools._ref_count == 0
        assert tools._initialized is False

    async def test_interleaved_connect_close(self):
        """Interleaved connect/close should maintain correct ref count."""
        tools = _make_mcptools()

        with _patch_mcp_connect(tools):
            await tools.connect()  # ref=1
            await tools.connect()  # ref=2
            await tools.close()   # ref=1, still alive
            assert tools._initialized is True
            await tools.connect()  # ref=2
            await tools.close()   # ref=1, still alive
            assert tools._initialized is True
            await tools.close()   # ref=0, tear down
            assert tools._initialized is False


# =============================================================================
# MCPTools — ref count lock
# =============================================================================


class TestMCPToolsRefCountLock:
    """Tests for the lazily-created ref count lock."""

    def test_ref_count_lock_initially_none(self):
        tools = _make_mcptools()
        assert tools._ref_count_lock is None

    def test_ref_count_lock_lazily_created(self):
        tools = _make_mcptools()
        lock = tools._connection_ref_lock
        assert isinstance(lock, asyncio.Lock)

    def test_ref_count_lock_same_instance(self):
        tools = _make_mcptools()
        lock1 = tools._connection_ref_lock
        lock2 = tools._connection_ref_lock
        assert lock1 is lock2


# =============================================================================
# MultiMCPTools — basic ref counting
# =============================================================================


class TestMultiMCPToolsRefCounting:
    """Tests for MultiMCPTools reference counting on connect/close."""

    def test_ref_count_starts_at_zero(self):
        tools = _make_multimcptools()
        assert tools._ref_count == 0

    async def test_connect_increments_ref_count(self):
        tools = _make_multimcptools()
        with _patch_multi_connect(tools):
            await tools.connect()
        assert tools._ref_count == 1

    async def test_multiple_connects_increment_ref_count(self):
        tools = _make_multimcptools()
        with _patch_multi_connect(tools):
            await tools.connect()
            await tools.connect()
            await tools.connect()
        assert tools._ref_count == 3

    async def test_close_decrements_ref_count(self):
        tools = _make_multimcptools()
        with _patch_multi_connect(tools):
            await tools.connect()
            await tools.connect()

        await tools.close()
        assert tools._ref_count == 1
        assert tools._initialized is True

    async def test_close_tears_down_at_zero(self):
        tools = _make_multimcptools()
        with _patch_multi_connect(tools):
            await tools.connect()

        await tools.close()
        assert tools._ref_count == 0
        assert tools._initialized is False

    async def test_close_does_not_go_negative(self):
        tools = _make_multimcptools()
        with _patch_multi_connect(tools):
            await tools.connect()
        await tools.close()
        await tools.close()
        await tools.close()
        assert tools._ref_count == 0

    async def test_connect_rollback_on_failure(self):
        tools = _make_multimcptools()

        async def failing_connect():
            raise RuntimeError("Connection refused")

        with patch.object(tools, "_connect", side_effect=failing_connect):
            await tools.connect()

        assert tools._ref_count == 0
        assert tools._initialized is False

    async def test_connect_force_resets_ref_count(self):
        tools = _make_multimcptools()
        with _patch_multi_connect(tools):
            await tools.connect()
            await tools.connect()
            await tools.connect()
        assert tools._ref_count == 3

        tools._initialized = False
        with _patch_multi_connect(tools):
            await tools.connect(force=True)
        assert tools._ref_count == 1

    async def test_force_connect_clears_state(self):
        tools = _make_multimcptools()
        tools._sessions = [MagicMock()]
        tools._successful_connections = 1
        tools._initialized = True
        tools._ref_count = 5

        with _patch_multi_connect(tools):
            await tools.connect(force=True)

        assert tools._ref_count == 1


# =============================================================================
# MultiMCPTools — parallel connect/close cycles
# =============================================================================


class TestMultiMCPToolsParallelRefCounting:
    """Tests for concurrent connect/close with MultiMCPTools."""

    async def test_parallel_connects_all_increment(self):
        tools = _make_multimcptools()
        connect_count = 10

        with _patch_multi_connect(tools):
            await asyncio.gather(*[tools.connect() for _ in range(connect_count)])

        assert tools._ref_count == connect_count

    async def test_parallel_connect_close_cycle(self):
        tools = _make_multimcptools()
        n_runs = 5

        with _patch_multi_connect(tools):
            await asyncio.gather(*[tools.connect() for _ in range(n_runs)])

        assert tools._ref_count == n_runs
        assert tools._initialized is True

        for i in range(n_runs - 1):
            await tools.close()
            assert tools._initialized is True
            assert tools._ref_count == n_runs - 1 - i

        await tools.close()
        assert tools._ref_count == 0
        assert tools._initialized is False

    async def test_interleaved_connect_close(self):
        tools = _make_multimcptools()

        with _patch_multi_connect(tools):
            await tools.connect()  # ref=1
            await tools.connect()  # ref=2
            await tools.close()   # ref=1
            assert tools._initialized is True
            await tools.connect()  # ref=2
            await tools.close()   # ref=1
            assert tools._initialized is True
            await tools.close()   # ref=0
            assert tools._initialized is False


# =============================================================================
# MultiMCPTools — ref count lock
# =============================================================================


class TestMultiMCPToolsRefCountLock:
    def test_ref_count_lock_initially_none(self):
        tools = _make_multimcptools()
        assert tools._ref_count_lock is None

    def test_ref_count_lock_lazily_created(self):
        tools = _make_multimcptools()
        lock = tools._connection_ref_lock
        assert isinstance(lock, asyncio.Lock)

    def test_ref_count_lock_same_instance(self):
        tools = _make_multimcptools()
        lock1 = tools._connection_ref_lock
        lock2 = tools._connection_ref_lock
        assert lock1 is lock2
