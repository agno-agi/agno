import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.agents.base import BaseExternalAgent
from agno.models.response import ToolExecution
from agno.tools.function import UserInputField
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    RunPausedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)


def _sdk() -> Any:
    """Lazy-import the claude_agent_sdk module."""
    try:
        import claude_agent_sdk  # type: ignore

        return claude_agent_sdk
    except ImportError as e:
        raise ImportError("claude-agent-sdk is required: pip install claude-agent-sdk") from e


@dataclass
class ClaudeAgent(BaseExternalAgent):
    """Adapter for the Claude Agent SDK (claude-agent-sdk).

    Wraps the Claude Agent SDK's query() function so it can be used with AgentOS
    endpoints or standalone via .run() / .print_response().

    The Claude Agent SDK runs Claude Code as a subprocess. Tool execution is handled
    internally by the SDK — you configure tools via allowed_tools and MCP servers.

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        system_prompt: Optional system prompt for the agent.
        model: Model to use (e.g. "claude-sonnet-4-20250514"). Defaults to SDK default.
        allowed_tools: List of tools the agent can use (e.g. ["Read", "Bash", "WebSearch"]).
        disallowed_tools: List of tools to block.
        permission_mode: Permission mode ("default", "acceptEdits", "plan", "bypassPermissions").
        max_turns: Maximum number of turns.
        max_budget_usd: Maximum cost budget in USD.
        cwd: Working directory for the agent.
        mcp_servers: MCP server configurations for custom tools.
        options_kwargs: Additional kwargs passed to ClaudeAgentOptions.

    Example:
        from agno.agents.claude import ClaudeAgent

        agent = ClaudeAgent(
            name="Claude Coder",
            allowed_tools=["Read", "Edit", "Bash"],
            permission_mode="acceptEdits",
            max_turns=10,
        )

        # Standalone usage
        agent.print_response("Read main.py and summarize it", stream=True)

        # Or deploy with AgentOS
        from agno.os import AgentOS
        AgentOS(agents=[agent])
    """

    system_prompt: Optional[str] = None
    model: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    disallowed_tools: Optional[List[str]] = None
    permission_mode: Optional[str] = None
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    cwd: Optional[str] = None
    mcp_servers: Optional[Dict[str, Any]] = None
    sandbox: Optional[Dict[str, Any]] = None
    # HITL mode: "confirmation" shows approve/deny buttons,
    # "user_input" shows editable input fields for tool arguments.
    hitl_mode: Optional[str] = None
    options_kwargs: Dict[str, Any] = field(default_factory=dict)
    framework: str = "claude-agent-sdk"

    @property
    def hitl_enabled(self) -> bool:
        """HITL is active when permission_mode is 'default' or hitl_mode is set."""
        return self.permission_mode == "default" or self.hitl_mode is not None

    # Maps Agno session_id -> SDK session id. Keyed per session to avoid cross-session bleed.
    _sdk_session_ids: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    # HITL state: pending permission request that the can_use_tool callback is waiting on
    _pending_permission: Optional[asyncio.Event] = field(default=None, init=False, repr=False)
    _permission_decision: Optional[bool] = field(default=None, init=False, repr=False)
    _permission_updated_args: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)
    _permission_queue: Optional[asyncio.Queue] = field(default=None, init=False, repr=False)
    # Persisted event queue from the paused run — the continue call consumes remaining events
    _paused_event_queue: Optional[asyncio.Queue] = field(default=None, init=False, repr=False)
    _paused_query_task: Optional[asyncio.Task] = field(default=None, init=False, repr=False)  # type: ignore[type-arg]
    _paused_perm_task: Optional[asyncio.Task] = field(default=None, init=False, repr=False)  # type: ignore[type-arg]
    _paused_run_state: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)

    def _build_options(self, *, streaming: bool = False, **kwargs: Any) -> Any:
        """Build ClaudeAgentOptions from agent config."""
        sdk = _sdk()

        opts: Dict[str, Any] = {}

        if self.system_prompt:
            opts["system_prompt"] = self.system_prompt
        if self.model:
            opts["model"] = self.model
        if self.allowed_tools:
            opts["allowed_tools"] = self.allowed_tools
        if self.disallowed_tools:
            opts["disallowed_tools"] = self.disallowed_tools
        if self.permission_mode:
            opts["permission_mode"] = self.permission_mode
        if self.max_turns is not None:
            opts["max_turns"] = self.max_turns
        if self.max_budget_usd is not None:
            opts["max_budget_usd"] = self.max_budget_usd
        if self.cwd:
            opts["cwd"] = self.cwd
        if self.mcp_servers:
            opts["mcp_servers"] = self.mcp_servers
        if self.sandbox:
            opts["sandbox"] = self.sandbox

        # HITL: register PreToolUse hook that pauses for user approval
        if self.hitl_enabled:
            opts["hooks"] = self._make_hitl_hooks(kwargs.get("run_id", ""))

        # Enable token-level streaming when streaming is requested
        if streaming:
            opts["include_partial_messages"] = True

        # Resume only the SDK session tied to this Agno session_id.
        session_id = kwargs.get("session_id")
        if session_id:
            sdk_session_id = self._sdk_session_ids.get(session_id)
            if sdk_session_id:
                opts["resume"] = sdk_session_id

        opts.update(self.options_kwargs)
        return sdk.ClaudeAgentOptions(**opts)

    def _make_hitl_hooks(self, run_id: str) -> Dict[str, Any]:
        """Build PreToolUse hooks that integrate with Agno's HITL.

        When Claude wants to use a tool, the hook:
        1. Creates a RunPausedEvent with the tool info
        2. Puts it in the permission queue (picked up by _arun_adapter_stream)
        3. Waits on an asyncio.Event for the user's decision
        4. Returns permissionDecision allow/deny based on user response
        """
        sdk = _sdk()

        # Read-only / internal tools that should auto-approve without pausing
        _auto_approve_tools = {
            "ToolSearch", "Read", "Glob", "Grep", "WebSearch",
            "ToolSearch", "ListFiles", "SearchFiles",
        }

        async def _hitl_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
            tool_name = input_data.get("tool_name", "unknown") if isinstance(input_data, dict) else "unknown"
            tool_input = input_data.get("tool_input", {}) if isinstance(input_data, dict) else {}

            # Auto-approve read-only and internal tools
            if tool_name in _auto_approve_tools:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                }

            # Create the pause event for tools that need user approval.
            args = tool_input if isinstance(tool_input, dict) else {"input": tool_input}
            use_user_input = self.hitl_mode == "user_input"

            tool_exec = ToolExecution(
                tool_call_id=tool_use_id or str(uuid4()),
                tool_name=tool_name,
                tool_args=args,
                requires_confirmation=not use_user_input,
                requires_user_input=use_user_input,
                user_input_schema=[
                    UserInputField(name=k, field_type=type(v), description=k, value=v)
                    for k, v in args.items()
                ] if use_user_input else None,
            )
            pause_event = RunPausedEvent(
                run_id=run_id,
                agent_id=self.get_id(),
                agent_name=self.name or "",
                tools=[tool_exec],
            )

            # Signal the streaming loop to yield this pause event
            self._pending_permission = asyncio.Event()
            self._permission_decision = None
            self._permission_updated_args = None
            if self._permission_queue:
                await self._permission_queue.put(pause_event)

            # Block until the user responds via resolve_hitl()
            await self._pending_permission.wait()

            if self._permission_decision:
                result: Dict[str, Any] = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                }
                # Pass modified arguments back to the CLI if the user edited them
                if self._permission_updated_args is not None:
                    result["hookSpecificOutput"]["updatedInput"] = self._permission_updated_args
                return result
            else:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                    },
                    "reason": "User denied tool execution",
                }

        return {
            "PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[_hitl_hook])]
        }

    def resolve_hitl(self, confirmed: bool, updated_args: Optional[Dict[str, Any]] = None) -> None:
        """Resume a paused HITL permission request.

        Called by acontinue_run when the user approves/rejects a tool.
        """
        self._permission_decision = confirmed
        self._permission_updated_args = updated_args
        if self._pending_permission:
            self._pending_permission.set()

    def acontinue_run(
        self,
        *,
        updated_tools: Optional[List[ToolExecution]] = None,
        stream: Optional[bool] = None,
        **kwargs: Any,
    ) -> Any:
        """Continue a paused HITL run.

        Resumes the blocked can_use_tool callback and returns the remaining
        stream of events from the SDK query.
        """
        if not self._paused_event_queue or not self._paused_run_state:
            raise RuntimeError("No paused run to continue")

        # Extract confirmation and any modified args from updated_tools
        confirmed = True
        updated_args: Optional[Dict[str, Any]] = None
        if updated_tools:
            for tool in updated_tools:
                if tool.confirmed is not None:
                    confirmed = tool.confirmed
                # Check user_input_schema for edited values (FE sends these)
                if tool.user_input_schema:
                    updated_args = {
                        field.name: field.value
                        for field in tool.user_input_schema
                        if field.value is not None
                    }
                elif tool.tool_args:
                    updated_args = tool.tool_args
                break

        # Unblock the PreToolUse hook with the user's decision + modified args
        self.resolve_hitl(confirmed, updated_args=updated_args)

        # Return an async iterator that drains the remaining events
        if stream:
            return self._drain_paused_stream()
        else:
            # Non-streaming: collect and return RunOutput
            return self._drain_paused_non_stream()

    async def _drain_paused_stream(self) -> AsyncIterator[RunOutputEvent]:
        """Drain remaining events from a paused HITL run as a stream."""
        from agno.utils.log import logger

        sdk = _sdk()
        event_queue = self._paused_event_queue
        state = self._paused_run_state
        if not event_queue or not state:
            return

        run_id = state["run_id"]
        got_stream_events = state["got_stream_events"]
        emitted_tool_ids = state["emitted_tool_ids"]
        tool_info_map = state["tool_info_map"]
        agno_session_id = state["agno_session_id"]

        re_paused = False
        try:
            while True:
                kind, item = await event_queue.get()

                if kind == "done":
                    break
                if kind == "error":
                    raise item  # type: ignore[misc]
                if kind == "pause":
                    # Another HITL pause — keep state alive for next continue
                    re_paused = True
                    self._paused_run_state = state
                    self._paused_event_queue = event_queue
                    yield item
                    return

                message = item
                if isinstance(message, sdk.StreamEvent):
                    got_stream_events = True
                    event = message.event
                    event_type = event.get("type", "")
                    if event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield RunContentEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    content=text,
                                )

                elif isinstance(message, sdk.AssistantMessage):
                    for block in message.content:
                        if isinstance(block, sdk.TextBlock):
                            if not got_stream_events and block.text:
                                yield RunContentEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    content=block.text,
                                )
                        elif isinstance(block, sdk.ToolUseBlock):
                            tool_name = getattr(block, "name", "unknown")
                            tool_input = getattr(block, "input", {})
                            tool_id = getattr(block, "id", str(uuid4()))
                            if tool_id not in emitted_tool_ids:
                                emitted_tool_ids.add(tool_id)
                                tool_args = tool_input if isinstance(tool_input, dict) else {"input": tool_input}
                                tool_info_map[tool_id] = {"name": tool_name, "args": tool_args}
                                yield ToolCallStartedEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    tool=ToolExecution(
                                        tool_call_id=tool_id,
                                        tool_name=tool_name,
                                        tool_args=tool_args,
                                    ),
                                )

                elif isinstance(message, sdk.UserMessage):
                    content = message.content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, sdk.ToolResultBlock):
                                tool_use_id = getattr(block, "tool_use_id", str(uuid4()))
                                result_content = getattr(block, "content", "")
                                if isinstance(result_content, list):
                                    result_str = " ".join(
                                        getattr(i, "text", str(i)) for i in result_content
                                    )
                                else:
                                    result_str = str(result_content) if result_content else ""
                                info = tool_info_map.get(tool_use_id, {})
                                yield ToolCallCompletedEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    tool=ToolExecution(
                                        tool_call_id=tool_use_id,
                                        tool_name=info.get("name", ""),
                                        tool_args=info.get("args"),
                                        result=result_str,
                                    ),
                                )

                elif isinstance(message, sdk.ResultMessage):
                    self._check_result_message(sdk, message)
                    if hasattr(message, "session_id") and message.session_id and agno_session_id:
                        self._sdk_session_ids[agno_session_id] = message.session_id
        finally:
            # Only clean up if the run completed (not re-paused)
            if not re_paused:
                self._paused_event_queue = None
                self._paused_run_state = None
                if self._paused_perm_task:
                    self._paused_perm_task.cancel()
                    self._paused_perm_task = None
                if self._paused_query_task and not self._paused_query_task.done():
                    self._paused_query_task.cancel()
                    self._paused_query_task = None

    async def _drain_paused_non_stream(self) -> Any:
        """Drain remaining events from a paused HITL run and return final content."""
        content = ""
        async for event in self._drain_paused_stream():
            if isinstance(event, RunContentEvent) and event.content:
                content += event.content
        return content

    @staticmethod
    def _check_result_message(sdk: Any, message: Any) -> None:
        """Raise if the SDK reported an error result so the base class can surface it."""
        if not isinstance(message, sdk.ResultMessage):
            return
        is_error = bool(getattr(message, "is_error", False))
        subtype = getattr(message, "subtype", None)
        if is_error or (subtype and subtype != "success"):
            # `message.result` carries the human-readable error text in the
            # invalid-model case where subtype="success" but is_error=True.
            detail = (
                getattr(message, "errors", None)
                or getattr(message, "result", None)
                or getattr(message, "stop_reason", None)
            )
            raise RuntimeError(f"Claude SDK error (is_error={is_error}, subtype={subtype}): {detail}")

    async def _arun_adapter(self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> str:
        """Non-streaming: collect all messages and return final content."""
        sdk = _sdk()

        options = self._build_options(**kwargs)
        agno_session_id = kwargs.get("session_id")
        assistant_text = ""
        final_result = ""

        async for message in sdk.query(prompt=str(input), options=options):
            if isinstance(message, sdk.SystemMessage):
                if hasattr(message, "subtype") and message.subtype == "init":
                    data = getattr(message, "data", {}) or {}
                    sdk_session_id = data.get("session_id")
                    if sdk_session_id and agno_session_id:
                        self._sdk_session_ids[agno_session_id] = sdk_session_id

            elif isinstance(message, sdk.AssistantMessage):
                # Accumulate every text block; multiple blocks per message are valid
                for block in message.content:
                    if isinstance(block, sdk.TextBlock):
                        assistant_text += block.text

            elif isinstance(message, sdk.ResultMessage):
                self._check_result_message(sdk, message)
                if hasattr(message, "session_id") and message.session_id and agno_session_id:
                    self._sdk_session_ids[agno_session_id] = message.session_id
                if hasattr(message, "result") and message.result:
                    final_result = str(message.result)

        # Prefer ResultMessage.result, fall back to accumulated assistant text
        return final_result or assistant_text

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming: yield token-level events using include_partial_messages.

        With include_partial_messages=True, the SDK yields StreamEvent objects
        containing raw Anthropic API events (content_block_delta, etc.) alongside
        the normal complete messages. We use StreamEvent for token-level text
        streaming and tool call tracking, while still handling complete messages
        for tool results and session management.
        """
        sdk = _sdk()

        run_id = kwargs.pop("run_id", str(uuid4()))
        agno_session_id = kwargs.get("session_id")
        options = self._build_options(streaming=True, run_id=run_id, **kwargs)

        # Initialize HITL permission queue for this run
        if self.hitl_enabled:
            self._permission_queue = asyncio.Queue()

        # Track whether we got any StreamEvents (token-level streaming)
        got_stream_events = False
        # Track tool call IDs already emitted via AssistantMessage to avoid duplicates
        emitted_tool_ids: set = set()
        # Map tool_use_id -> (tool_name, tool_args) for carrying forward to ToolCallCompleted
        tool_info_map: Dict[str, Dict[str, Any]] = {}

        # When HITL is enabled, we run the query in a background task so we can
        # yield RunPausedEvent while can_use_tool is blocking. The task puts SDK
        # messages into a shared queue; the permission callback also puts pause
        # events into the same queue. We consume from the queue and yield events.
        _sentinel = object()
        event_queue: asyncio.Queue = asyncio.Queue()

        async def _run_query() -> None:
            """Consume the SDK query and forward messages to the event queue."""
            try:
                async for message in sdk.query(prompt=str(input), options=options):
                    await event_queue.put(("sdk", message))
            except Exception as e:
                await event_queue.put(("error", e))
            finally:
                await event_queue.put(("done", _sentinel))

        # If HITL is enabled, redirect permission pause events to the same queue
        if self.hitl_enabled and self._permission_queue:
            original_pq = self._permission_queue

            async def _forward_permissions() -> None:
                while True:
                    pause_event = await original_pq.get()
                    await event_queue.put(("pause", pause_event))

            perm_task = asyncio.create_task(_forward_permissions())
        else:
            perm_task = None

        query_task = asyncio.create_task(_run_query())

        try:
            while True:
                kind, item = await event_queue.get()

                if kind == "done":
                    break
                if kind == "error":
                    raise item  # type: ignore[misc]
                if kind == "pause":
                    # HITL pause — save state and yield pause event to SSE.
                    # The continue endpoint will call acontinue_run() to resume.
                    self._paused_event_queue = event_queue
                    self._paused_query_task = query_task
                    self._paused_perm_task = perm_task
                    self._paused_run_state = {
                        "run_id": run_id,
                        "got_stream_events": got_stream_events,
                        "emitted_tool_ids": emitted_tool_ids,
                        "tool_info_map": tool_info_map,
                        "agno_session_id": agno_session_id,
                    }
                    yield item
                    return  # End this stream — continue picks up via acontinue_run

                # kind == "sdk" — process the SDK message
                message = item
                if isinstance(message, sdk.StreamEvent):
                    got_stream_events = True
                    event = message.event
                    event_type = event.get("type", "")

                    if event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        delta_type = delta.get("type", "")

                        if delta_type == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield RunContentEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    content=text,
                                )

                elif isinstance(message, sdk.SystemMessage):
                    if hasattr(message, "subtype") and message.subtype == "init":
                        data = getattr(message, "data", {}) or {}
                        sdk_session_id = data.get("session_id")
                        if sdk_session_id and agno_session_id:
                            self._sdk_session_ids[agno_session_id] = sdk_session_id

                elif isinstance(message, sdk.AssistantMessage):
                    for block in message.content:
                        if isinstance(block, sdk.TextBlock):
                            if not got_stream_events and block.text:
                                yield RunContentEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    content=block.text,
                                )
                        elif isinstance(block, sdk.ToolUseBlock):
                            tool_name = getattr(block, "name", "unknown")
                            tool_input = getattr(block, "input", {})
                            tool_id = getattr(block, "id", str(uuid4()))
                            if tool_id not in emitted_tool_ids:
                                emitted_tool_ids.add(tool_id)
                                tool_args = tool_input if isinstance(tool_input, dict) else {"input": tool_input}
                                tool_info_map[tool_id] = {"name": tool_name, "args": tool_args}
                                yield ToolCallStartedEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    tool=ToolExecution(
                                        tool_call_id=tool_id,
                                        tool_name=tool_name,
                                        tool_args=tool_args,
                                    ),
                                )

                elif isinstance(message, sdk.UserMessage):
                    content = message.content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, sdk.ToolResultBlock):
                                tool_use_id = getattr(block, "tool_use_id", str(uuid4()))
                                result_content = getattr(block, "content", "")
                                if isinstance(result_content, list):
                                    result_str = " ".join(
                                        getattr(item, "text", str(item)) for item in result_content
                                    )
                                else:
                                    result_str = str(result_content) if result_content else ""
                                info = tool_info_map.get(tool_use_id, {})
                                yield ToolCallCompletedEvent(
                                    run_id=run_id,
                                    agent_id=self.get_id(),
                                    agent_name=self.name or "",
                                    tool=ToolExecution(
                                        tool_call_id=tool_use_id,
                                        tool_name=info.get("name", ""),
                                        tool_args=info.get("args"),
                                        result=result_str,
                                    ),
                                )

                elif isinstance(message, sdk.ResultMessage):
                    self._check_result_message(sdk, message)
                    if hasattr(message, "session_id") and message.session_id and agno_session_id:
                        self._sdk_session_ids[agno_session_id] = message.session_id
        finally:
            # Don't cancel tasks if we paused — they'll be resumed by acontinue_run
            if self._paused_event_queue is None:
                if perm_task:
                    perm_task.cancel()
                if not query_task.done():
                    query_task.cancel()
