"""Tests for the AgentProtocolClient.

Tests cover:
- Client construction and configuration
- Sync method wiring (delegates to ap_client SDK APIs)
- Async methods against a live AgentOS test server (via httpx)
- All protocol areas: runs, threads, agents, store

The async tests spin up a real AgentOS with the Agent Protocol interface
and use the AgentProtocolClient's async methods to talk to it, verifying
end-to-end correctness through the full client → server → Agno agent pipeline.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytest.importorskip("ap_client", reason="ap_client not installed (optional dependency)")

from agno.agent import Agent
from agno.client.agent_protocol.client import AgentProtocolClient
from agno.os.app import AgentOS
from agno.os.interfaces.agent_protocol.router import _runs, _run_tasks, _store, _threads
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

# ap_client models used for type assertions


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _clear_state():
    """Clear in-memory state before each test."""
    _threads.clear()
    _runs.clear()
    _run_tasks.clear()
    _store.clear()
    yield
    _threads.clear()
    _runs.clear()
    _run_tasks.clear()
    _store.clear()


@pytest.fixture
def test_agent():
    return Agent(
        name="client-test-agent",
        id="client_test_agent",
        description="Agent for client testing",
        instructions="You are a test agent.",
    )


@pytest.fixture
def agent_os_app(test_agent):
    """Create a real AgentOS FastAPI app with AP interface."""
    agent_os = AgentOS(agents=[test_agent], agent_protocol_interface=True)
    return agent_os.get_app()


@pytest.fixture
def base_url():
    return "http://testserver/ap"


@pytest.fixture
def client(base_url):
    """Create an AgentProtocolClient pointing at the test server."""
    return AgentProtocolClient(base_url=base_url)


@pytest.fixture
def client_with_headers():
    """Create a client with custom headers."""
    return AgentProtocolClient(
        base_url="http://testserver/ap",
        headers={"X-Api-Key": "test-key-123", "X-Custom": "value"},
    )


def _mock_run_output(agent):
    return RunOutput(
        run_id="mock-run",
        session_id="mock-session",
        agent_id=agent.id,
        agent_name=agent.name,
        content="Client test response",
        status=RunStatus.completed,
    )


# ============================================================================
# 1. Client Construction
# ============================================================================


class TestClientConstruction:
    def test_basic_construction(self, client, base_url):
        assert client.base_url == base_url
        assert client.timeout == 30
        assert client.headers == {}

    def test_trailing_slash_stripped(self):
        c = AgentProtocolClient(base_url="http://example.com/ap/")
        assert c.base_url == "http://example.com/ap"

    def test_custom_timeout(self):
        c = AgentProtocolClient(base_url="http://example.com", timeout=120)
        assert c.timeout == 120

    def test_custom_headers(self, client_with_headers):
        assert client_with_headers.headers == {"X-Api-Key": "test-key-123", "X-Custom": "value"}
        # Verify headers are set on the underlying ap_client
        assert client_with_headers._api_client.default_headers["X-Api-Key"] == "test-key-123"
        assert client_with_headers._api_client.default_headers["X-Custom"] == "value"

    def test_api_instances_created(self, client):
        """Verify all ap_client API instances are initialized."""
        assert client._runs_api is not None
        assert client._bg_runs_api is not None
        assert client._threads_api is not None
        assert client._agents_api is not None
        assert client._store_api is not None


# ============================================================================
# 2. Async Methods Against Live AgentOS
# ============================================================================


class TestAsyncThreads:
    """Test async thread methods against a real AgentOS server."""

    @pytest.mark.asyncio
    async def test_acreate_thread(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                result = await client.acreate_thread(metadata={"env": "test"})

        assert result is not None
        assert result.thread_id is not None
        assert result.metadata == {"env": "test"}

    @pytest.mark.asyncio
    async def test_aget_thread(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                created = await client.acreate_thread()
                fetched = await client.aget_thread(created.thread_id)

        assert fetched.thread_id == created.thread_id

    @pytest.mark.asyncio
    async def test_adelete_thread(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                created = await client.acreate_thread()
                await client.adelete_thread(created.thread_id)

                with pytest.raises(httpx.HTTPStatusError):
                    await client.aget_thread(created.thread_id)

    @pytest.mark.asyncio
    async def test_asearch_threads(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                await client.acreate_thread(metadata={"tag": "a"})
                await client.acreate_thread(metadata={"tag": "b"})

                results = await client.asearch_threads()
        assert len(results) >= 2


class TestAsyncAgents:
    """Test async agent introspection methods."""

    @pytest.mark.asyncio
    async def test_alist_agents(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                agents = await client.alist_agents()

        assert len(agents) >= 1
        ids = [a.agent_id for a in agents]
        assert test_agent.id in ids

    @pytest.mark.asyncio
    async def test_aget_agent(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                agent = await client.aget_agent(test_agent.id)

        assert agent.agent_id == test_agent.id
        assert agent.name == test_agent.name

    @pytest.mark.asyncio
    async def test_aget_agent_schemas(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                schemas = await client.aget_agent_schemas(test_agent.id)

        assert schemas.agent_id == test_agent.id
        assert schemas.input_schema is not None
        assert schemas.output_schema is not None


class TestAsyncRuns:
    """Test async run methods."""

    @pytest.mark.asyncio
    async def test_acreate_run_wait(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with (
                patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client),
                patch.object(test_agent, "arun", new_callable=AsyncMock, return_value=_mock_run_output(test_agent)),
            ):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                result = await client.acreate_run_wait(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "Hello"}]},
                )

        assert result is not None
        assert result.run is not None
        assert result.run.status == "success"

    @pytest.mark.asyncio
    async def test_acreate_background_run(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with (
                patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client),
                patch.object(test_agent, "arun", new_callable=AsyncMock, return_value=_mock_run_output(test_agent)),
            ):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                run = await client.acreate_background_run(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "Background"}]},
                )

        assert run is not None
        assert run.run_id is not None

    @pytest.mark.asyncio
    async def test_aget_run(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with (
                patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client),
                patch.object(test_agent, "arun", new_callable=AsyncMock, return_value=_mock_run_output(test_agent)),
            ):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                run = await client.acreate_background_run(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "Hi"}]},
                )
                fetched = await client.aget_run(run.run_id)

        assert fetched.run_id == run.run_id

    @pytest.mark.asyncio
    async def test_acancel_run(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with (
                patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client),
                patch.object(test_agent, "arun", new_callable=AsyncMock, return_value=_mock_run_output(test_agent)),
            ):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                run = await client.acreate_background_run(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "Cancel me"}]},
                )
                await client.acancel_run(run.run_id)
                cancelled = await client.aget_run(run.run_id)

        assert cancelled.status == "interrupted"

    @pytest.mark.asyncio
    async def test_asearch_runs(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with (
                patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client),
                patch.object(test_agent, "arun", new_callable=AsyncMock, return_value=_mock_run_output(test_agent)),
            ):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                await client.acreate_background_run(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "r1"}]},
                )
                await client.acreate_background_run(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "r2"}]},
                )
                results = await client.asearch_runs()

        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_await_run(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with (
                patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client),
                patch.object(test_agent, "arun", new_callable=AsyncMock, return_value=_mock_run_output(test_agent)),
            ):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                run = await client.acreate_background_run(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "wait"}]},
                )
                result = await client.await_run(run.run_id)

        assert result is not None
        assert result.run is not None

    @pytest.mark.asyncio
    async def test_adelete_run(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with (
                patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client),
                patch.object(test_agent, "arun", new_callable=AsyncMock, return_value=_mock_run_output(test_agent)),
            ):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                run = await client.acreate_background_run(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "delete me"}]},
                )
                await asyncio.sleep(0.1)  # let async task complete
                await client.adelete_run(run.run_id)

                with pytest.raises(httpx.HTTPStatusError):
                    await client.aget_run(run.run_id)


class TestAsyncStore:
    """Test async store methods."""

    @pytest.mark.asyncio
    async def test_aput_and_aget_item(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                await client.aput_item(
                    namespace=["test", "ns"],
                    key="my_key",
                    value={"data": "hello"},
                )
                item = await client.aget_item(namespace=["test", "ns"], key="my_key")

        assert item.key == "my_key"
        assert item.value == {"data": "hello"}

    @pytest.mark.asyncio
    async def test_adelete_item(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                await client.aput_item(namespace=["del"], key="k1", value={"x": 1})
                await client.adelete_item(namespace=["del"], key="k1")

                with pytest.raises(httpx.HTTPStatusError):
                    await client.aget_item(namespace=["del"], key="k1")

    @pytest.mark.asyncio
    async def test_asearch_items(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client):
                client = AgentProtocolClient(base_url="http://testserver/ap")
                await client.aput_item(namespace=["search", "ns"], key="a", value={"v": 1})
                await client.aput_item(namespace=["search", "ns"], key="b", value={"v": 2})
                items = await client.asearch_items(namespace_prefix=["search"])

        assert len(items) == 2


# ============================================================================
# 3. Sync Method Wiring (verify delegation to ap_client)
# ============================================================================


class TestSyncMethodWiring:
    """Verify sync methods correctly delegate to the ap_client SDK APIs."""

    def test_create_thread_delegates(self, client):
        mock_thread = MagicMock()
        client._threads_api.create_thread = MagicMock(return_value=mock_thread)
        result = client.create_thread(metadata={"env": "test"})
        client._threads_api.create_thread.assert_called_once()
        assert result is mock_thread

    def test_get_thread_delegates(self, client):
        mock_thread = MagicMock()
        client._threads_api.get_thread = MagicMock(return_value=mock_thread)
        result = client.get_thread("thread-123")
        client._threads_api.get_thread.assert_called_once_with("thread-123")
        assert result is mock_thread

    def test_delete_thread_delegates(self, client):
        client._threads_api.delete_thread = MagicMock()
        client.delete_thread("thread-123")
        client._threads_api.delete_thread.assert_called_once_with("thread-123")

    def test_list_agents_delegates(self, client):
        mock_agents = [MagicMock()]
        client._agents_api.search_agents = MagicMock(return_value=mock_agents)
        result = client.list_agents()
        client._agents_api.search_agents.assert_called_once()
        assert result is mock_agents

    def test_get_agent_delegates(self, client):
        mock_agent = MagicMock()
        client._agents_api.get_agent = MagicMock(return_value=mock_agent)
        result = client.get_agent("agent-1")
        client._agents_api.get_agent.assert_called_once_with("agent-1")
        assert result is mock_agent

    def test_get_agent_schemas_delegates(self, client):
        mock_schema = MagicMock()
        client._agents_api.get_agent_schemas = MagicMock(return_value=mock_schema)
        result = client.get_agent_schemas("agent-1")
        client._agents_api.get_agent_schemas.assert_called_once_with("agent-1")
        assert result is mock_schema

    def test_get_run_delegates(self, client):
        mock_run = MagicMock()
        client._bg_runs_api.get_run = MagicMock(return_value=mock_run)
        result = client.get_run("run-123")
        client._bg_runs_api.get_run.assert_called_once_with("run-123")
        assert result is mock_run

    def test_cancel_run_delegates(self, client):
        client._bg_runs_api.cancel_run = MagicMock()
        client.cancel_run("run-123")
        client._bg_runs_api.cancel_run.assert_called_once_with("run-123")

    def test_delete_run_delegates(self, client):
        client._bg_runs_api.delete_run = MagicMock()
        client.delete_run("run-123")
        client._bg_runs_api.delete_run.assert_called_once_with("run-123")

    def test_put_item_delegates(self, client):
        client._store_api.put_item = MagicMock()
        client.put_item(namespace=["ns"], key="k", value={"v": 1})
        client._store_api.put_item.assert_called_once()

    def test_delete_item_delegates(self, client):
        client._store_api.delete_item = MagicMock()
        client.delete_item(namespace=["ns"], key="k")
        client._store_api.delete_item.assert_called_once()


# ============================================================================
# 4. End-to-End: Client → Server round trip
# ============================================================================


class TestEndToEnd:
    """Full round trip: client creates thread, runs agent, checks result."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, agent_os_app, test_agent):
        transport = httpx.ASGITransport(app=agent_os_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            with (
                patch("agno.client.agent_protocol.client.get_default_async_client", return_value=http_client),
                patch.object(test_agent, "arun", new_callable=AsyncMock, return_value=_mock_run_output(test_agent)),
            ):
                client = AgentProtocolClient(base_url="http://testserver/ap")

                # 1. List agents
                agents = await client.alist_agents()
                assert len(agents) >= 1

                # 2. Create thread
                thread = await client.acreate_thread(metadata={"test": "lifecycle"})
                assert thread.thread_id

                # 3. Run agent (stateless wait)
                result = await client.acreate_run_wait(
                    agent_id=test_agent.id,
                    input={"messages": [{"role": "user", "content": "Full lifecycle test"}]},
                )
                assert result.run.status == "success"

                # 4. Store data
                await client.aput_item(namespace=["lifecycle"], key="result", value={"ok": True})
                item = await client.aget_item(namespace=["lifecycle"], key="result")
                assert item.value == {"ok": True}

                # 5. Clean up
                await client.adelete_thread(thread.thread_id)
                await client.adelete_item(namespace=["lifecycle"], key="result")
