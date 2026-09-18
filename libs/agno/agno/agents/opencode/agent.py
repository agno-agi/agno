import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Type, Union
from uuid import uuid4

import httpx
from pydantic import BaseModel

from agno.agents.base import BaseExternalAgent
from agno.exceptions import RunCancelledException
from agno.metrics import ModelMetrics, RunMetrics
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.session.agent import AgentSession
from agno.utils.log import log_warning

# Key used to persist the OpenCode session id inside AgentSession.session_data
OPENCODE_SESSION_KEY = "opencode_session_id"


@dataclass
class OpenCodeAgent(BaseExternalAgent):
    """Adapter for the OpenCode coding agent (https://opencode.ai).

    Talks to a running OpenCode server (`opencode serve`) over its HTTP API so it
    can be used with AgentOS endpoints or standalone via .run() / .print_response().

    OpenCode runs as a headless server with first-class sessions and an SSE event
    bus. Tool execution (file edits, shell, search) happens inside the OpenCode
    server, in the directory it was started in.

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        base_url: URL of the running OpenCode server (default http://127.0.0.1:4096).
        model: Model in "provider/model" form (e.g. "anthropic/claude-sonnet-4-5").
            Defaults to the server's configured default model.
        system_prompt: Optional system prompt for the agent.
        opencode_agent: OpenCode agent mode to run (e.g. "build", "plan", or a
            custom agent defined in opencode config).
        tools: Per-tool enable/disable map (e.g. {"bash": False, "edit": True}).
        output_schema: Pydantic model (or raw JSON schema dict) for structured
            output. The response content becomes a validated model instance
            (or dict when a raw schema is given).
        username: HTTP basic auth username (when OPENCODE_SERVER_PASSWORD is set
            on the server; server default username is "opencode").
        password: HTTP basic auth password.
        timeout: Overall request timeout in seconds for a single run.
        message_kwargs: Additional fields merged into the message request body.

    Runs report token usage and cost (RunOutput.metrics), and in-flight runs can
    be cancelled via cancel_run / acancel_run (wired to AgentOS /cancel).

    Example:
        from agno.agents.opencode import OpenCodeAgent

        # Start the server first: opencode serve --port 4096
        agent = OpenCodeAgent(
            name="OpenCode Dev",
            base_url="http://127.0.0.1:4096",
        )

        # Standalone usage
        agent.print_response("List the files in this project", stream=True)

        # Or deploy with AgentOS
        from agno.os import AgentOS
        AgentOS(agents=[agent])
    """

    base_url: str = "http://127.0.0.1:4096"
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    opencode_agent: Optional[str] = None
    tools: Optional[Dict[str, bool]] = None
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None
    username: Optional[str] = None
    password: Optional[str] = None
    timeout: float = 600.0
    message_kwargs: Dict[str, Any] = field(default_factory=dict)
    framework: str = "opencode"

    # Maps Agno session_id -> OpenCode session id. Keyed per session to avoid cross-session bleed.
    _oc_session_ids: Dict[str, str] = field(default_factory=dict, init=False, repr=False)
    # Maps in-flight run_id -> OpenCode session id, for cancellation
    _active_runs: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    # ---------------------------------------------------------------------------
    # HTTP helpers
    # ---------------------------------------------------------------------------

    def _client(self, *, streaming: bool = False) -> httpx.AsyncClient:
        auth = httpx.BasicAuth(self.username or "opencode", self.password) if self.password else None
        # SSE connections stay open across long tool runs, so the read timeout is
        # disabled for streaming clients; overall run duration is bounded elsewhere.
        timeout = httpx.Timeout(self.timeout, read=None) if streaming else httpx.Timeout(self.timeout, connect=10.0)
        return httpx.AsyncClient(base_url=self.base_url.rstrip("/"), auth=auth, timeout=timeout)

    def _build_message_body(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if self.model:
            if "/" not in self.model:
                raise ValueError(f"OpenCodeAgent model must be 'provider/model', got: {self.model}")
            provider_id, model_id = self.model.split("/", 1)
            body["model"] = {"providerID": provider_id, "modelID": model_id}
        if self.system_prompt:
            body["system"] = self.system_prompt
        if self.opencode_agent:
            body["agent"] = self.opencode_agent
        if self.tools:
            body["tools"] = self.tools
        if self.output_schema is not None:
            schema = (
                self.output_schema if isinstance(self.output_schema, dict) else self.output_schema.model_json_schema()
            )
            body["format"] = {"type": "json_schema", "schema": schema}
        body.update(self.message_kwargs)
        return body

    async def _ensure_oc_session(
        self, client: httpx.AsyncClient, agno_session_id: Optional[str], session: Optional[AgentSession]
    ) -> str:
        """Resolve (or create) the OpenCode session tied to this Agno session."""
        oc_session_id: Optional[str] = None
        if agno_session_id:
            oc_session_id = self._oc_session_ids.get(agno_session_id)
            if oc_session_id is None and session is not None and session.session_data:
                oc_session_id = session.session_data.get(OPENCODE_SESSION_KEY)

        # Verify a remembered session still exists on the server (it may have restarted)
        if oc_session_id:
            response = await client.get(f"/session/{oc_session_id}")
            if response.status_code == 200:
                return oc_session_id
            oc_session_id = None

        response = await client.post("/session", json={"title": agno_session_id or "agno-run"})
        response.raise_for_status()
        oc_session_id = str(response.json()["id"])

        if agno_session_id:
            self._oc_session_ids[agno_session_id] = oc_session_id
        if session is not None:
            if session.session_data is None:
                session.session_data = {}
            session.session_data[OPENCODE_SESSION_KEY] = oc_session_id
        return oc_session_id

    @staticmethod
    def _raise_for_status_with_detail(response: httpx.Response) -> None:
        """Raise on HTTP errors, including the server's error body for debuggability."""
        if response.status_code < 400:
            return
        detail = response.text
        try:
            data = response.json()
            detail = data.get("data", {}).get("message") or data.get("message") or detail
        except Exception:
            pass
        raise RuntimeError(f"OpenCode server returned {response.status_code}: {detail}")

    @staticmethod
    def _check_message_error(payload: Dict[str, Any]) -> None:
        """Raise if the assistant message reported an error so the base class can surface it."""
        error = (payload.get("info") or {}).get("error")
        if error:
            name = error.get("name", "error") if isinstance(error, dict) else "error"
            if name == "MessageAbortedError":
                raise RunCancelledException("Run cancelled")
            detail = error.get("data", error) if isinstance(error, dict) else error
            raise RuntimeError(f"OpenCode error ({name}): {detail}")

    @staticmethod
    def _extract_text(payload: Dict[str, Any]) -> str:
        parts = payload.get("parts") or []
        return "".join(part.get("text", "") for part in parts if part.get("type") == "text")

    @staticmethod
    def _metrics_from_info(info: Dict[str, Any]) -> Optional[RunMetrics]:
        """Build RunMetrics from the assistant message's tokens/cost fields."""
        tokens = info.get("tokens") or {}
        cost = info.get("cost")
        if not tokens and cost is None:
            return None
        cache = tokens.get("cache") or {}
        input_tokens = int(tokens.get("input") or 0)
        output_tokens = int(tokens.get("output") or 0)
        model_metrics = ModelMetrics(
            id=str(info.get("modelID") or ""),
            provider=str(info.get("providerID") or ""),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=int(tokens.get("total") or (input_tokens + output_tokens)),
            reasoning_tokens=int(tokens.get("reasoning") or 0),
            cache_read_tokens=int(cache.get("read") or 0),
            cache_write_tokens=int(cache.get("write") or 0),
            cost=float(cost) if cost is not None else None,
        )
        return RunMetrics(
            input_tokens=model_metrics.input_tokens,
            output_tokens=model_metrics.output_tokens,
            total_tokens=model_metrics.total_tokens,
            reasoning_tokens=model_metrics.reasoning_tokens,
            cache_read_tokens=model_metrics.cache_read_tokens,
            cache_write_tokens=model_metrics.cache_write_tokens,
            cost=model_metrics.cost,
            details={"model": [model_metrics]},
        )

    def _structured_content(self, payload: Dict[str, Any]) -> Any:
        """Parse the structured result when output_schema is configured.

        Prefers the server-validated `info.structured` value, falling back to
        parsing the text content as JSON. Returns a validated model instance
        for pydantic schemas, or the raw dict for plain-dict schemas.
        """
        data = (payload.get("info") or {}).get("structured")
        if data is None:
            text = self._extract_text(payload)
            if not text:
                raise RuntimeError("OpenCode returned no structured output for the configured output_schema")
            data = json.loads(text)
        if isinstance(self.output_schema, type) and issubclass(self.output_schema, BaseModel):
            return self.output_schema.model_validate(data)
        return data

    # ---------------------------------------------------------------------------
    # Adapter hooks
    # ---------------------------------------------------------------------------

    async def _arun_adapter(self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> Any:
        """Non-streaming: send the prompt and return the final content."""
        run_id = kwargs.get("run_id", str(uuid4()))
        agno_session_id = kwargs.get("session_id")
        session = kwargs.get("session")
        adapter_state = kwargs.get("adapter_state")

        async with self._client() as client:
            oc_session_id = await self._ensure_oc_session(client, agno_session_id, session)
            body = self._build_message_body()
            body["parts"] = [{"type": "text", "text": str(input)}]

            self._active_runs[run_id] = oc_session_id
            try:
                response = await client.post(f"/session/{oc_session_id}/message", json=body)
            finally:
                self._active_runs.pop(run_id, None)
            self._raise_for_status_with_detail(response)
            payload = response.json()

        self._check_message_error(payload)
        if adapter_state is not None:
            metrics = self._metrics_from_info(payload.get("info") or {})
            if metrics is not None:
                adapter_state["metrics"] = metrics
        if self.output_schema is not None:
            return self._structured_content(payload)
        return self._extract_text(payload)

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming: subscribe to the server's SSE event bus while the prompt runs.

        Token-level text arrives as `message.part.delta` events (field == "text").
        Tool calls arrive as `message.part.updated` events for parts of type "tool",
        transitioning through pending -> running -> completed/error states.
        """
        run_id = kwargs.get("run_id", str(uuid4()))
        agno_session_id = kwargs.get("session_id")
        session = kwargs.get("session")
        adapter_state = kwargs.get("adapter_state")

        async with self._client(streaming=True) as client:
            oc_session_id = await self._ensure_oc_session(client, agno_session_id, session)
            body = self._build_message_body()
            body["parts"] = [{"type": "text", "text": str(input)}]

            self._active_runs[run_id] = oc_session_id
            event_queue: asyncio.Queue = asyncio.Queue()

            async def _pump_events() -> None:
                async with client.stream("GET", "/event") as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                await event_queue.put(json.loads(line[6:]))
                            except json.JSONDecodeError:
                                continue

            # Subscribe before sending the prompt so no early events are missed
            pump_task = asyncio.create_task(_pump_events())
            post_task = asyncio.create_task(client.post(f"/session/{oc_session_id}/message", json=body))

            got_text_deltas = False
            saw_idle = False
            # partID -> part type, so reasoning deltas are not streamed as content
            part_types: Dict[str, str] = {}
            # callID -> (tool name, args) for tools whose start was already emitted
            started_tools: Dict[str, Tuple[str, Dict[str, Any]]] = {}
            completed_tools: set = set()

            try:
                while True:
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # The message request finishing (or failing) ends the run even
                        # if the idle event was dropped from the bus.
                        if post_task.done():
                            break
                        continue

                    event_type = event.get("type", "")
                    properties = event.get("properties", {}) or {}
                    if properties.get("sessionID") != oc_session_id:
                        continue

                    if event_type == "message.part.delta":
                        part_id = properties.get("partID", "")
                        if properties.get("field") == "text" and part_types.get(part_id, "text") == "text":
                            delta = properties.get("delta", "")
                            if delta:
                                got_text_deltas = True
                                yield RunContentEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    content=delta,
                                )

                    elif event_type == "message.part.updated":
                        part = properties.get("part", {}) or {}
                        part_id = part.get("id", "")
                        part_type = part.get("type", "")
                        if part_id:
                            part_types[part_id] = part_type

                        if part_type == "tool":
                            state = part.get("state", {}) or {}
                            status = state.get("status", "")
                            call_id = part.get("callID") or part_id
                            tool_name = part.get("tool", "unknown")

                            if status in ("running", "completed", "error") and call_id not in started_tools:
                                tool_args = state.get("input") or {}
                                started_tools[call_id] = (tool_name, tool_args)
                                yield ToolCallStartedEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    tool=ToolExecution(
                                        tool_call_id=call_id,
                                        tool_name=tool_name,
                                        tool_args=tool_args,
                                    ),
                                )

                            if status in ("completed", "error") and call_id not in completed_tools:
                                completed_tools.add(call_id)
                                name, args = started_tools.get(call_id, (tool_name, {}))
                                result = state.get("output") or state.get("error") or ""
                                yield ToolCallCompletedEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    tool=ToolExecution(
                                        tool_call_id=call_id,
                                        tool_name=name,
                                        tool_args=args,
                                        result=str(result),
                                    ),
                                )

                    elif event_type == "session.error":
                        error = properties.get("error", {})
                        error_name = error.get("name", "") if isinstance(error, dict) else ""
                        if error_name == "MessageAbortedError":
                            raise RunCancelledException("Run cancelled")
                        raise RuntimeError(f"OpenCode session error: {error}")

                    elif event_type == "session.idle":
                        saw_idle = True

                    if saw_idle and post_task.done():
                        break

                response = await post_task
                self._raise_for_status_with_detail(response)
                payload = response.json()
                self._check_message_error(payload)

                if adapter_state is not None:
                    metrics = self._metrics_from_info(payload.get("info") or {})
                    if metrics is not None:
                        adapter_state["metrics"] = metrics
                    if self.output_schema is not None:
                        adapter_state["final_content"] = self._structured_content(payload)

                # Some models or configs do not emit deltas; fall back to the final text
                if not got_text_deltas:
                    final_text = self._extract_text(payload)
                    if final_text:
                        yield RunContentEvent(
                            run_id=run_id,
                            agent_id=self.get_id(),
                            agent_name=self.name or "",
                            content=final_text,
                        )
            finally:
                self._active_runs.pop(run_id, None)
                pump_task.cancel()
                if not post_task.done():
                    post_task.cancel()

    # ---------------------------------------------------------------------------
    # Cancellation (wired to AgentOS POST /agents/{id}/runs/{run_id}/cancel)
    # ---------------------------------------------------------------------------

    async def acancel_run(self, run_id: str) -> None:
        """Abort the OpenCode session processing the given run."""
        oc_session_id = self._active_runs.get(run_id)
        if oc_session_id is None:
            log_warning(f"OpenCodeAgent has no active run '{run_id}' to cancel")
            return
        async with self._client() as client:
            response = await client.post(f"/session/{oc_session_id}/abort")
            self._raise_for_status_with_detail(response)

    def cancel_run(self, run_id: str) -> None:
        """Sync variant of acancel_run."""
        oc_session_id = self._active_runs.get(run_id)
        if oc_session_id is None:
            log_warning(f"OpenCodeAgent has no active run '{run_id}' to cancel")
            return
        auth = httpx.BasicAuth(self.username or "opencode", self.password) if self.password else None
        with httpx.Client(base_url=self.base_url.rstrip("/"), auth=auth, timeout=30.0) as client:
            response = client.post(f"/session/{oc_session_id}/abort")
            self._raise_for_status_with_detail(response)
