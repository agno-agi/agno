from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.frameworks.base import BaseExternalAgent
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)


@dataclass
class ClaudeAgentSDK(BaseExternalAgent):
    """Adapter for the Claude Agent SDK (claude-agent-sdk).

    Wraps the Claude Agent SDK's query() function so it can be used with AgentOS
    endpoints or standalone via .run() / .print_response().

    The Claude Agent SDK runs Claude Code as a subprocess. Tool execution is handled
    internally by the SDK — you configure tools via allowed_tools and MCP servers.

    Args:
        agent_id: Unique identifier for this agent.
        agent_name: Display name for this agent.
        prompt: Optional system prompt for the agent.
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
        from agno.frameworks.claude import ClaudeAgentSDK

        agent = ClaudeAgentSDK(
            agent_id="claude-coder",
            agent_name="Claude Coder",
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

    prompt: Optional[str] = None
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

    # Session tracking: last session_id from the SDK
    _last_session_id: Optional[str] = field(default=None, init=False, repr=False)

    def _build_options(self, *, streaming: bool = False, **kwargs: Any) -> Any:
        """Build ClaudeAgentOptions from agent config."""
        try:
            from claude_agent_sdk import ClaudeAgentOptions
        except ImportError:
            raise ImportError("claude-agent-sdk is required: pip install claude-agent-sdk")

        opts: Dict[str, Any] = {}

        if self.prompt:
            opts["system_prompt"] = self.prompt
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

        # Resume session if session_id provided
        session_id = kwargs.get("session_id")
        if session_id and self._last_session_id:
            opts["resume"] = self._last_session_id

        opts.update(self.options_kwargs)
        return ClaudeAgentOptions(**opts)

    async def _arun_impl(self, input: Any, **kwargs: Any) -> str:
        """Non-streaming: collect all messages and return final content."""
        try:
            from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock, query
        except ImportError:
            raise ImportError("claude-agent-sdk is required: pip install claude-agent-sdk")

        options = self._build_options(**kwargs)
        result_text = ""

        async for message in query(prompt=str(input), options=options):
            if isinstance(message, SystemMessage):
                if hasattr(message, "subtype") and message.subtype == "init":
                    data = getattr(message, "data", {}) or {}
                    if "session_id" in data:
                        self._last_session_id = data["session_id"]

            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_text = block.text

            elif isinstance(message, ResultMessage):
                if hasattr(message, "session_id") and message.session_id:
                    self._last_session_id = message.session_id
                # Use result text if available
                if hasattr(message, "result") and message.result:
                    result_text = str(message.result)

        return result_text

    async def _arun_stream_impl(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        """Streaming: yield token-level events using include_partial_messages.

        With include_partial_messages=True, the SDK yields StreamEvent objects
        containing raw Anthropic API events (content_block_delta, etc.) alongside
        the normal complete messages. We use StreamEvent for token-level text
        streaming and tool call tracking, while still handling complete messages
        for tool results and session management.
        """
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ResultMessage,
                StreamEvent,
                SystemMessage,
                TextBlock,
                ToolResultBlock,
                ToolUseBlock,
                UserMessage,
                query,
            )
        except ImportError:
            raise ImportError("claude-agent-sdk is required: pip install claude-agent-sdk")

        run_id = kwargs.get("run_id", str(uuid4()))
        options = self._build_options(streaming=True, **kwargs)

        # Track whether we got any StreamEvents (token-level streaming)
        got_stream_events = False
        # Track tool call IDs already emitted via AssistantMessage to avoid duplicates
        emitted_tool_ids: set = set()

        async for message in query(prompt=str(input), options=options):
            if isinstance(message, StreamEvent):
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
                                agent_id=self.id,
                                agent_name=self.name or "",
                                content=text,
                            )

            elif isinstance(message, SystemMessage):
                if hasattr(message, "subtype") and message.subtype == "init":
                    data = getattr(message, "data", {}) or {}
                    if "session_id" in data:
                        self._last_session_id = data["session_id"]

            elif isinstance(message, AssistantMessage):
                # Always extract tool calls from complete AssistantMessage
                # (has full name + args). For text, only use if no StreamEvents.
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if not got_stream_events and block.text:
                            yield RunContentEvent(
                                run_id=run_id,
                                agent_id=self.id,
                                agent_name=self.name or "",
                                content=block.text,
                            )
                    elif isinstance(block, ToolUseBlock):
                        tool_name = getattr(block, "name", "unknown")
                        tool_input = getattr(block, "input", {})
                        tool_id = getattr(block, "id", str(uuid4()))
                        if tool_id not in emitted_tool_ids:
                            emitted_tool_ids.add(tool_id)
                            yield ToolCallStartedEvent(
                                run_id=run_id,
                                agent_id=self.id,
                                agent_name=self.name or "",
                                tool=ToolExecution(
                                    tool_call_id=tool_id,
                                    tool_name=tool_name,
                                    tool_args=tool_input if isinstance(tool_input, dict) else {"input": tool_input},
                                ),
                            )

            elif isinstance(message, UserMessage):
                # Tool results arrive as ToolResultBlock inside UserMessage
                content = message.content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, ToolResultBlock):
                            tool_use_id = getattr(block, "tool_use_id", str(uuid4()))
                            result_content = getattr(block, "content", "")
                            if isinstance(result_content, list):
                                result_str = " ".join(getattr(item, "text", str(item)) for item in result_content)
                            else:
                                result_str = str(result_content) if result_content else ""
                            yield ToolCallCompletedEvent(
                                run_id=run_id,
                                agent_id=self.id,
                                agent_name=self.name or "",
                                tool=ToolExecution(
                                    tool_call_id=tool_use_id,
                                    tool_name="",
                                    result=result_str,
                                ),
                            )

            elif isinstance(message, ResultMessage):
                if hasattr(message, "session_id") and message.session_id:
                    self._last_session_id = message.session_id
