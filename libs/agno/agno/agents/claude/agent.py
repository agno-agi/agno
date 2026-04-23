from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.agents.base import BaseExternalAgent
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
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
    options_kwargs: Dict[str, Any] = field(default_factory=dict)
    framework: str = "claude-agent-sdk"

    # Maps Agno session_id -> SDK session id. Keyed per session to avoid cross-session bleed.
    _sdk_session_ids: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

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

        run_id = kwargs.get("run_id", str(uuid4()))
        agno_session_id = kwargs.get("session_id")
        options = self._build_options(streaming=True, **kwargs)

        # Track whether we got any StreamEvents (token-level streaming)
        got_stream_events = False
        # Track tool call IDs already emitted via AssistantMessage to avoid duplicates
        emitted_tool_ids: set = set()
        # Map tool_use_id -> (tool_name, tool_args) for carrying forward to ToolCallCompleted
        tool_info_map: Dict[str, Dict[str, Any]] = {}

        async for message in sdk.query(prompt=str(input), options=options):
            if isinstance(message, sdk.StreamEvent):
                got_stream_events = True
                event = message.event
                event_type = event.get("type", "")

                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    delta_type = delta.get("type", "")

                    if delta_type == "text_delta":
                        # Token-level text streaming
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
                # Always extract tool calls from complete AssistantMessage
                # (has full name + args). For text, only use if no StreamEvents.
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
                # Tool results arrive as ToolResultBlock inside UserMessage
                content = message.content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, sdk.ToolResultBlock):
                            tool_use_id = getattr(block, "tool_use_id", str(uuid4()))
                            result_content = getattr(block, "content", "")
                            if isinstance(result_content, list):
                                result_str = " ".join(getattr(item, "text", str(item)) for item in result_content)
                            else:
                                result_str = str(result_content) if result_content else ""
                            # Look up tool name from the corresponding ToolCallStarted
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
