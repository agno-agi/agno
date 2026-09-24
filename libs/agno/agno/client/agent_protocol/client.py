"""Agent Protocol client for Agno.

This module provides a client for communicating with any Agent Protocol-compatible
server, enabling cross-framework agent communication via the LangChain Agent Protocol.

Uses ap_client SDK for sync operations and httpx for async operations,
with ap_client Pydantic models for serialization/deserialization.
"""

from typing import Any, AsyncIterator, Dict, List, Optional

from agno.utils.http import get_default_async_client

try:
    from ap_client import (
        AgentsApi,
        ApiClient,
        BackgroundRunsApi,
        Configuration,
        RunsApi,
        StoreApi,
        ThreadsApi,
    )
    from ap_client.models import (
        Agent,
        AgentSchema,
        Item,
        Message,
        Run,
        RunCreate,
        RunStream,
        RunWaitResponse,
        SearchAgentsRequest,
        StoreDeleteRequest,
        StorePutRequest,
        StoreSearchRequest,
        Thread,
        ThreadCreate,
    )
except ImportError as e:
    raise ImportError(
        "`ap_client` not installed. Install from GitHub with:\n"
        '  pip install "git+https://github.com/langchain-ai/agent-protocol.git#subdirectory=client-python"'
    ) from e


__all__ = ["AgentProtocolClient"]


class AgentProtocolClient:
    """Client for Agent Protocol servers.

    Provides both sync and async methods for the full Agent Protocol spec.
    Sync methods delegate to the ap_client SDK (urllib3-based).
    Async methods use httpx, deserializing into ap_client Pydantic models.

    Attributes:
        base_url: Base URL of the Agent Protocol server.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {}

        # ap_client for sync operations
        config = Configuration(host=self.base_url)
        self._api_client = ApiClient(config)
        if self.headers:
            for key, value in self.headers.items():
                self._api_client.default_headers[key] = value
        self._runs_api = RunsApi(self._api_client)
        self._bg_runs_api = BackgroundRunsApi(self._api_client)
        self._threads_api = ThreadsApi(self._api_client)
        self._agents_api = AgentsApi(self._api_client)
        self._store_api = StoreApi(self._api_client)

    @staticmethod
    def _parse_run_wait_response(data: Dict[str, Any]) -> RunWaitResponse:
        """Parse a RunWaitResponse from raw JSON, tolerating non-standard message formats.

        The ap_client Message model requires strict role/content fields, but servers
        (including Agno's AP interface) may return simplified message dicts. This method
        builds the RunWaitResponse while gracefully handling such messages.
        """
        run_obj = Run.from_dict(data["run"]) if data.get("run") else None
        values = data.get("values")

        # Try parsing messages through ap_client; fall back to raw dicts on failure
        parsed_messages = None
        raw_messages = data.get("messages")
        if raw_messages:
            try:
                parsed_messages = [Message.from_dict(m) for m in raw_messages]
            except Exception:
                # Messages don't conform to strict ap_client schema -- store as None
                # The raw messages are still available via the values dict
                parsed_messages = None

        return RunWaitResponse(run=run_obj, values=values, messages=parsed_messages)

    # =========================================================================
    # Stateless Runs
    # =========================================================================

    def create_run_wait(
        self,
        input: Optional[Any] = None,
        agent_id: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RunWaitResponse:
        """Create a stateless run and wait for the result."""
        from ap_client.models import Config, Input

        body = RunCreate(
            agent_id=agent_id,
            input=Input.from_dict(input) if input else None,
            messages=[Message.from_dict(m) for m in messages] if messages else None,
            config=Config.from_dict(config) if config else None,
            metadata=metadata,
        )
        return self._runs_api.create_and_wait_run(body)

    async def acreate_run_wait(
        self,
        input: Optional[Any] = None,
        agent_id: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RunWaitResponse:
        """Async: Create a stateless run and wait for the result."""
        body: Dict[str, Any] = {}
        if agent_id:
            body["agent_id"] = agent_id
        if input:
            body["input"] = input
        if messages:
            body["messages"] = messages
        if config:
            body["config"] = config
        if metadata:
            body["metadata"] = metadata

        client = get_default_async_client()
        resp = await client.post(
            f"{self.base_url}/runs/wait",
            json=body,
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return self._parse_run_wait_response(resp.json())

    def create_run_stream(
        self,
        input: Optional[Any] = None,
        agent_id: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        stream_mode: Optional[str] = None,
    ) -> str:
        """Create a stateless run and stream the output."""
        from ap_client.models import Input, StreamMode

        body = RunStream(
            agent_id=agent_id,
            input=Input.from_dict(input) if input else None,
            messages=[Message.from_dict(m) for m in messages] if messages else None,
            stream_mode=StreamMode(stream_mode) if stream_mode else None,
        )
        return self._runs_api.create_and_stream_run(body)

    async def acreate_run_stream(
        self,
        input: Optional[Any] = None,
        agent_id: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        stream_mode: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Async: Create a stateless run and stream the output."""
        body: Dict[str, Any] = {}
        if agent_id:
            body["agent_id"] = agent_id
        if input:
            body["input"] = input
        if messages:
            body["messages"] = messages
        if stream_mode:
            body["stream_mode"] = stream_mode

        client = get_default_async_client()
        async with client.stream(
            "POST",
            f"{self.base_url}/runs/stream",
            json=body,
            headers=self.headers,
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                yield line

    # =========================================================================
    # Background Runs
    # =========================================================================

    def create_background_run(
        self,
        thread_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        input: Optional[Any] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        webhook: Optional[str] = None,
    ) -> Run:
        """Create a background run."""
        from ap_client.models import Input

        body = RunStream(
            thread_id=thread_id,
            agent_id=agent_id,
            input=Input.from_dict(input) if input else None,
            messages=[Message.from_dict(m) for m in messages] if messages else None,
            metadata=metadata,
            webhook=webhook,
        )
        return self._bg_runs_api.create_run(body)

    async def acreate_background_run(
        self,
        thread_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        input: Optional[Any] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        webhook: Optional[str] = None,
    ) -> Run:
        """Async: Create a background run."""
        body: Dict[str, Any] = {}
        if thread_id:
            body["thread_id"] = thread_id
        if agent_id:
            body["agent_id"] = agent_id
        if input:
            body["input"] = input
        if messages:
            body["messages"] = messages
        if metadata:
            body["metadata"] = metadata
        if webhook:
            body["webhook"] = webhook

        client = get_default_async_client()
        resp = await client.post(
            f"{self.base_url}/runs",
            json=body,
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return Run.from_dict(resp.json())  # type: ignore

    def get_run(self, run_id: str) -> Run:
        """Get a run by ID."""
        return self._bg_runs_api.get_run(run_id)

    async def aget_run(self, run_id: str) -> Run:
        """Async: Get a run by ID."""
        client = get_default_async_client()
        resp = await client.get(
            f"{self.base_url}/runs/{run_id}",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return Run.from_dict(resp.json())  # type: ignore

    def wait_run(self, run_id: str) -> RunWaitResponse:
        """Wait for a run to complete."""
        return self._bg_runs_api.wait_run(run_id)

    async def await_run(self, run_id: str) -> RunWaitResponse:
        """Async: Wait for a run to complete."""
        client = get_default_async_client()
        resp = await client.get(
            f"{self.base_url}/runs/{run_id}/wait",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return self._parse_run_wait_response(resp.json())

    def cancel_run(self, run_id: str) -> None:
        """Cancel a run."""
        self._bg_runs_api.cancel_run(run_id)

    async def acancel_run(self, run_id: str) -> None:
        """Async: Cancel a run."""
        client = get_default_async_client()
        resp = await client.post(
            f"{self.base_url}/runs/{run_id}/cancel",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def delete_run(self, run_id: str) -> None:
        """Delete a finished run."""
        self._bg_runs_api.delete_run(run_id)

    async def adelete_run(self, run_id: str) -> None:
        """Async: Delete a finished run."""
        client = get_default_async_client()
        resp = await client.delete(
            f"{self.base_url}/runs/{run_id}",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def search_runs(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Run]:
        """Search runs."""
        from ap_client.models import RunSearchRequest

        body = RunSearchRequest(
            metadata=metadata,
            status=status,
            limit=limit,
            offset=offset,
        )
        return self._bg_runs_api.search_runs(body)

    async def asearch_runs(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Run]:
        """Async: Search runs."""
        body: Dict[str, Any] = {"limit": limit, "offset": offset}
        if metadata:
            body["metadata"] = metadata
        if status:
            body["status"] = status

        client = get_default_async_client()
        resp = await client.post(
            f"{self.base_url}/runs/search",
            json=body,
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [Run.from_dict(r) for r in resp.json()]  # type: ignore

    # =========================================================================
    # Threads
    # =========================================================================

    def create_thread(
        self,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Thread:
        """Create a new thread."""
        body = ThreadCreate(metadata=metadata)
        return self._threads_api.create_thread(body)

    async def acreate_thread(
        self,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Thread:
        """Async: Create a new thread."""
        body: Dict[str, Any] = {}
        if metadata:
            body["metadata"] = metadata

        client = get_default_async_client()
        resp = await client.post(
            f"{self.base_url}/threads",
            json=body,
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return Thread.from_dict(resp.json())  # type: ignore

    def get_thread(self, thread_id: str) -> Thread:
        """Get a thread by ID."""
        return self._threads_api.get_thread(thread_id)

    async def aget_thread(self, thread_id: str) -> Thread:
        """Async: Get a thread by ID."""
        client = get_default_async_client()
        resp = await client.get(
            f"{self.base_url}/threads/{thread_id}",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return Thread.from_dict(resp.json())  # type: ignore

    def delete_thread(self, thread_id: str) -> None:
        """Delete a thread."""
        self._threads_api.delete_thread(thread_id)

    async def adelete_thread(self, thread_id: str) -> None:
        """Async: Delete a thread."""
        client = get_default_async_client()
        resp = await client.delete(
            f"{self.base_url}/threads/{thread_id}",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def search_threads(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Thread]:
        """Search threads."""
        from ap_client.models import ThreadSearchRequest

        body = ThreadSearchRequest(
            metadata=metadata,
            status=status,
            limit=limit,
            offset=offset,
        )
        return self._threads_api.search_threads(body)

    async def asearch_threads(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Thread]:
        """Async: Search threads."""
        body: Dict[str, Any] = {"limit": limit, "offset": offset}
        if metadata:
            body["metadata"] = metadata
        if status:
            body["status"] = status

        client = get_default_async_client()
        resp = await client.post(
            f"{self.base_url}/threads/search",
            json=body,
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [Thread.from_dict(t) for t in resp.json()]  # type: ignore

    # =========================================================================
    # Agents (Introspection)
    # =========================================================================

    def list_agents(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Agent]:
        """List/search agents."""
        body = SearchAgentsRequest(
            metadata=metadata,
            limit=limit,
            offset=offset,
        )
        return self._agents_api.search_agents(body)

    async def alist_agents(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Agent]:
        """Async: List/search agents."""
        body: Dict[str, Any] = {"limit": limit, "offset": offset}
        if metadata:
            body["metadata"] = metadata

        client = get_default_async_client()
        resp = await client.post(
            f"{self.base_url}/agents/search",
            json=body,
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [Agent.from_dict(a) for a in resp.json()]  # type: ignore

    def get_agent(self, agent_id: str) -> Agent:
        """Get an agent by ID."""
        return self._agents_api.get_agent(agent_id)

    async def aget_agent(self, agent_id: str) -> Agent:
        """Async: Get an agent by ID."""
        client = get_default_async_client()
        resp = await client.get(
            f"{self.base_url}/agents/{agent_id}",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return Agent.from_dict(resp.json())  # type: ignore

    def get_agent_schemas(self, agent_id: str) -> AgentSchema:
        """Get an agent's input/output schemas."""
        return self._agents_api.get_agent_schemas(agent_id)

    async def aget_agent_schemas(self, agent_id: str) -> AgentSchema:
        """Async: Get an agent's input/output schemas."""
        client = get_default_async_client()
        resp = await client.get(
            f"{self.base_url}/agents/{agent_id}/schemas",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return AgentSchema.from_dict(resp.json())  # type: ignore

    # =========================================================================
    # Store
    # =========================================================================

    def put_item(
        self,
        namespace: List[str],
        key: str,
        value: Dict[str, Any],
    ) -> None:
        """Create or update an item in the store."""
        body = StorePutRequest(namespace=namespace, key=key, value=value)
        self._store_api.put_item(body)

    async def aput_item(
        self,
        namespace: List[str],
        key: str,
        value: Dict[str, Any],
    ) -> None:
        """Async: Create or update an item in the store."""
        client = get_default_async_client()
        resp = await client.put(
            f"{self.base_url}/store/items",
            json={"namespace": namespace, "key": key, "value": value},
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def get_item(
        self,
        namespace: List[str],
        key: str,
    ) -> Item:
        """Get an item from the store."""
        return self._store_api.get_item(namespace=namespace, key=key)

    async def aget_item(
        self,
        namespace: List[str],
        key: str,
    ) -> Item:
        """Async: Get an item from the store."""
        client = get_default_async_client()
        resp = await client.get(
            f"{self.base_url}/store/items",
            params={"namespace": namespace, "key": key},
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return Item.from_dict(resp.json())  # type: ignore

    def delete_item(
        self,
        namespace: List[str],
        key: str,
    ) -> None:
        """Delete an item from the store."""
        body = StoreDeleteRequest(namespace=namespace, key=key)
        self._store_api.delete_item(body)

    async def adelete_item(
        self,
        namespace: List[str],
        key: str,
    ) -> None:
        """Async: Delete an item from the store."""
        client = get_default_async_client()
        resp = await client.request(
            "DELETE",
            f"{self.base_url}/store/items",
            json={"namespace": namespace, "key": key},
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def search_items(
        self,
        namespace_prefix: List[str],
        filter: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Item]:
        """Search items in the store."""
        body = StoreSearchRequest(
            namespace_prefix=namespace_prefix,
            filter=filter,
            limit=limit,
            offset=offset,
        )
        result = self._store_api.search_items(body)
        return result.items if result and result.items else []

    async def asearch_items(
        self,
        namespace_prefix: List[str],
        filter: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Item]:
        """Async: Search items in the store."""
        body: Dict[str, Any] = {
            "namespace_prefix": namespace_prefix,
            "limit": limit,
            "offset": offset,
        }
        if filter:
            body["filter"] = filter

        client = get_default_async_client()
        resp = await client.post(
            f"{self.base_url}/store/items/search",
            json=body,
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        return [Item.from_dict(i) for i in items]  # type: ignore
