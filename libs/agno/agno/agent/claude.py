"""ClaudeAgent — Agno-compatible wrapper around the Claude Agent SDK.

Usage::

    from agno.agent.claude import ClaudeAgent

    agent = ClaudeAgent(
        agent_id="code-reviewer",
        name="Code Reviewer",
        system_prompt="You are a code reviewer. Review code for bugs and suggest fixes.",
        allowed_tools=["Read", "Glob", "Grep"],
    )

    # Use standalone
    response = await agent.arun("Review the auth module")

    # Use with AgentOS (with db for session persistence)
    from agno.os import AgentOS
    from agno.db.postgres import PostgresDb

    db = PostgresDb(table_name="agent_sessions", db_url="postgresql+psycopg://...")
    agent = ClaudeAgent(agent_id="code-reviewer", db=db, ...)
    app = AgentOS(agents=[agent], db=db)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from time import time
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Union,
    overload,
)

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunEvent,
    RunInput,
    RunOutput,
    RunOutputEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus
from agno.utils.log import logger


@dataclass
class ClaudeAgent:
    """Agno-compatible wrapper around the Claude Agent SDK.

    This allows Claude Agent SDK agents to be used with AgentOS alongside
    native Agno agents and remote agents.

    Args:
        agent_id: Unique identifier for this agent.
        name: Human-readable name.
        description: Description of what this agent does.
        system_prompt: System prompt for the Claude agent.
        allowed_tools: Tools to auto-approve (e.g. ``["Read", "Edit", "Bash"]``).
        disallowed_tools: Tools to always deny.
        permission_mode: One of ``"default"``, ``"acceptEdits"``, ``"plan"``, ``"bypassPermissions"``.
        max_turns: Maximum agentic turns (tool-use round trips).
        max_budget_usd: Budget cap in USD.
        model: Model to use (e.g. ``"claude-sonnet-4-5"``).
        cwd: Working directory for the agent.
        mcp_servers: MCP server configurations dict.
        output_format: Structured output format (``{"type": "json_schema", "schema": {...}}``).
        db: Optional database for session persistence. When set, sessions and runs
            are stored and can be retrieved via AgentOS APIs.
        include_partial_messages: When True, enables token-level streaming via
            the Claude Agent SDK ``StreamEvent`` messages. Default True.
    """

    # --- Identity ---
    agent_id: str = ""
    name: Optional[str] = "Claude Agent"
    description: Optional[str] = ""

    # --- Claude Agent SDK options ---
    system_prompt: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    disallowed_tools: Optional[List[str]] = None
    permission_mode: Optional[str] = None
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    model: Optional[str] = None
    cwd: Optional[str] = None
    mcp_servers: Optional[Dict[str, Any]] = None
    output_format: Optional[Dict[str, Any]] = None
    include_partial_messages: bool = True

    # --- Database for session persistence ---
    db: Any = None

    # --- Compatibility attributes for AgentOS ---
    knowledge: Any = None

    # --- Internal state ---
    _sessions: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.agent_id:
            self.agent_id = str(uuid.uuid4())

    @property
    def id(self) -> str:
        return self.agent_id

    def _build_options(self, session_id: Optional[str] = None) -> Any:
        """Build ClaudeAgentOptions from this agent's configuration."""
        from claude_agent_sdk import ClaudeAgentOptions

        kwargs: Dict[str, Any] = {}
        if self.system_prompt is not None:
            kwargs["system_prompt"] = self.system_prompt
        if self.allowed_tools is not None:
            kwargs["allowed_tools"] = self.allowed_tools
        if self.disallowed_tools is not None:
            kwargs["disallowed_tools"] = self.disallowed_tools
        if self.permission_mode is not None:
            kwargs["permission_mode"] = self.permission_mode
        if self.max_turns is not None:
            kwargs["max_turns"] = self.max_turns
        if self.max_budget_usd is not None:
            kwargs["max_budget_usd"] = self.max_budget_usd
        if self.model is not None:
            kwargs["model"] = self.model
        if self.cwd is not None:
            kwargs["cwd"] = self.cwd
        if self.mcp_servers is not None:
            kwargs["mcp_servers"] = self.mcp_servers
        if self.output_format is not None:
            kwargs["output_format"] = self.output_format
        if self.include_partial_messages:
            kwargs["include_partial_messages"] = True

        # Resume existing session if available
        if session_id and session_id in self._sessions:
            kwargs["resume"] = self._sessions[session_id]

        return ClaudeAgentOptions(**kwargs)

    # ------------------------------------------------------------------
    # Session persistence helpers
    # ------------------------------------------------------------------

    async def _persist_run(
        self,
        run_output: RunOutput,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Save the run to an AgentSession in the database."""
        if self.db is None:
            return

        from agno.db.base import AsyncBaseDb, BaseDb
        from agno.session import AgentSession

        try:
            # Load or create session
            session: Optional[AgentSession] = None
            if isinstance(self.db, AsyncBaseDb):
                existing = await self.db.aget_session(
                    session_id=session_id,
                    session_type="AGENT",
                    user_id=user_id,
                )
                if existing and isinstance(existing, AgentSession):
                    session = existing
            elif isinstance(self.db, BaseDb):
                existing = self.db.get_session(
                    session_id=session_id,
                    session_type="AGENT",
                    user_id=user_id,
                )
                if existing and isinstance(existing, AgentSession):
                    session = existing

            if session is None:
                session = AgentSession(
                    session_id=session_id,
                    agent_id=self.agent_id,
                    user_id=user_id,
                    agent_data={
                        "agent_id": self.agent_id,
                        "name": self.name,
                        "model": {"provider": "Anthropic", "model": self.model or "claude-sonnet-4-5"},
                    },
                    created_at=int(time()),
                )

            # Add run to session
            session.upsert_run(run=run_output)
            session.updated_at = int(time())

            # Persist
            if isinstance(self.db, AsyncBaseDb):
                await self.db.aupsert_session(session)
            elif isinstance(self.db, BaseDb):
                self.db.upsert_session(session)

        except Exception as e:
            logger.warning(f"Failed to persist ClaudeAgent run: {e}")

    async def aget_run_output(
        self,
        run_id: str,
        session_id: Optional[str] = None,
    ) -> Optional[RunOutput]:
        """Retrieve a specific run from the database."""
        if self.db is None or session_id is None:
            return None

        from agno.db.base import AsyncBaseDb, BaseDb
        from agno.session import AgentSession

        try:
            session: Optional[AgentSession] = None
            if isinstance(self.db, AsyncBaseDb):
                session = await self.db.aget_session(session_id=session_id, session_type="AGENT")  # type: ignore
            elif isinstance(self.db, BaseDb):
                session = self.db.get_session(session_id=session_id, session_type="AGENT")  # type: ignore

            if session and session.runs:
                for run in session.runs:
                    if isinstance(run, RunOutput) and run.run_id == run_id:
                        return run
        except Exception as e:
            logger.warning(f"Failed to get run output: {e}")

        return None

    # ------------------------------------------------------------------
    # arun — async execution (matches Agent / RemoteAgent interface)
    # ------------------------------------------------------------------

    @overload
    async def arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[False] = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        **kwargs: Any,
    ) -> RunOutput: ...

    @overload
    def arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[True] = True,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[RunOutputEvent]: ...

    def arun(  # type: ignore[misc]
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Optional[bool] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
        prompt = _resolve_prompt(input)

        if stream:
            return self._stream_impl(
                prompt=prompt,
                session_id=session_id,
                user_id=user_id,
            )
        else:
            return self._arun_non_stream(
                prompt=prompt,
                session_id=session_id,
                user_id=user_id,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _arun_non_stream(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> RunOutput:
        from claude_agent_sdk import query

        run_id = str(uuid.uuid4())
        _session_id = session_id or str(uuid.uuid4())
        options = self._build_options(session_id=session_id)
        content_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        sdk_session_id: Optional[str] = None

        async for message in query(prompt=prompt, options=options):
            msg_type = type(message).__name__

            if msg_type == "SystemMessage":
                if hasattr(message, "session_id") and message.session_id:
                    sdk_session_id = message.session_id
                elif hasattr(message, "content") and isinstance(message.content, dict):
                    sdk_session_id = message.content.get("session_id")

            elif msg_type == "AssistantMessage":
                if hasattr(message, "content") and isinstance(message.content, list):
                    for block in message.content:
                        if hasattr(block, "text") and block.text:
                            content_parts.append(block.text)
                        elif hasattr(block, "name") and block.name:
                            tool_calls.append({"name": block.name, "input": getattr(block, "input", {})})

            elif msg_type == "ResultMessage":
                if hasattr(message, "result") and message.result:
                    content_parts.append(message.result)

        # Track SDK session for future resumption
        if sdk_session_id and session_id:
            self._sessions[session_id] = sdk_session_id

        content = "\n".join(content_parts) if content_parts else ""

        run_output = RunOutput(
            run_id=run_id,
            agent_id=self.agent_id,
            agent_name=self.name,
            session_id=_session_id,
            user_id=user_id,
            content=content,
            content_type="str",
            input=RunInput(input_content=prompt),
            model=self.model or "claude-sonnet-4-5",
            model_provider="anthropic",
            created_at=int(time()),
            status=RunStatus.completed,
        )

        # Persist to database
        await self._persist_run(run_output, session_id=_session_id, user_id=user_id)

        return run_output

    async def _stream_impl(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[RunOutputEvent]:
        from claude_agent_sdk import query

        run_id = str(uuid.uuid4())
        _session_id = session_id or str(uuid.uuid4())
        options = self._build_options(session_id=session_id)
        sdk_session_id: Optional[str] = None

        # Emit RunStarted
        yield RunStartedEvent(
            event=RunEvent.run_started.value,
            agent_id=self.agent_id,
            agent_name=self.name or "",
            run_id=run_id,
            session_id=_session_id,
            model=self.model or "claude-sonnet-4-5",
            model_provider="anthropic",
        )

        full_content: List[str] = []

        async for message in query(prompt=prompt, options=options):
            msg_type = type(message).__name__

            if msg_type == "SystemMessage":
                if hasattr(message, "session_id") and message.session_id:
                    sdk_session_id = message.session_id
                elif hasattr(message, "content") and isinstance(message.content, dict):
                    sdk_session_id = message.content.get("session_id")

            elif msg_type == "StreamEvent":
                # Token-level streaming: partial text deltas from include_partial_messages
                if hasattr(message, "content") and message.content:
                    delta = message.content if isinstance(message.content, str) else str(message.content)
                    if delta:
                        yield RunContentEvent(
                            event=RunEvent.run_content.value,
                            agent_id=self.agent_id,
                            agent_name=self.name or "",
                            run_id=run_id,
                            session_id=_session_id,
                            content=delta,
                            content_type="str",
                        )

            elif msg_type == "AssistantMessage":
                if hasattr(message, "content") and isinstance(message.content, list):
                    for block in message.content:
                        if hasattr(block, "text") and block.text:
                            full_content.append(block.text)
                            # Only emit full message if partial streaming is disabled
                            if not self.include_partial_messages:
                                yield RunContentEvent(
                                    event=RunEvent.run_content.value,
                                    agent_id=self.agent_id,
                                    agent_name=self.name or "",
                                    run_id=run_id,
                                    session_id=_session_id,
                                    content=block.text,
                                    content_type="str",
                                )
                        elif hasattr(block, "name") and block.name:
                            from agno.models.response import ToolExecution

                            tool_exec = ToolExecution(
                                tool_name=block.name,
                                tool_args=getattr(block, "input", {}),
                            )
                            yield ToolCallStartedEvent(
                                event=RunEvent.tool_call_started.value,
                                agent_id=self.agent_id,
                                agent_name=self.name or "",
                                run_id=run_id,
                                session_id=_session_id,
                                tool=tool_exec,
                            )
                            yield ToolCallCompletedEvent(
                                event=RunEvent.tool_call_completed.value,
                                agent_id=self.agent_id,
                                agent_name=self.name or "",
                                run_id=run_id,
                                session_id=_session_id,
                                tool=tool_exec,
                            )

            elif msg_type == "ResultMessage":
                result_text = getattr(message, "result", None)
                if result_text:
                    full_content.append(result_text)
                    if not self.include_partial_messages:
                        yield RunContentEvent(
                            event=RunEvent.run_content.value,
                            agent_id=self.agent_id,
                            agent_name=self.name or "",
                            run_id=run_id,
                            session_id=_session_id,
                            content=result_text,
                            content_type="str",
                        )

        # Track SDK session for future resumption
        if sdk_session_id and session_id:
            self._sessions[session_id] = sdk_session_id

        # Build and persist RunOutput
        run_output = RunOutput(
            run_id=run_id,
            agent_id=self.agent_id,
            agent_name=self.name,
            session_id=_session_id,
            user_id=user_id,
            content="\n".join(full_content) if full_content else "",
            content_type="str",
            input=RunInput(input_content=prompt),
            model=self.model or "claude-sonnet-4-5",
            model_provider="anthropic",
            created_at=int(time()),
            status=RunStatus.completed,
        )
        await self._persist_run(run_output, session_id=_session_id, user_id=user_id)

        # Emit RunCompleted
        yield RunCompletedEvent(
            event=RunEvent.run_completed.value,
            agent_id=self.agent_id,
            agent_name=self.name or "",
            run_id=run_id,
            session_id=_session_id,
            content=run_output.content,
            content_type="str",
        )


def _resolve_prompt(
    input: Union[str, List, Dict, Message, BaseModel, List[Message]],
) -> str:
    """Convert various input types to a plain string prompt for the Claude Agent SDK."""
    if isinstance(input, str):
        return input
    elif isinstance(input, Message):
        return input.content or ""
    elif isinstance(input, BaseModel):
        return input.model_dump_json(exclude_none=True)
    elif isinstance(input, dict):
        import json

        return json.dumps(input)
    elif isinstance(input, list):
        parts: List[str] = []
        for item in input:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Message):
                parts.append(item.content or "")
            elif isinstance(item, BaseModel):
                parts.append(item.model_dump_json(exclude_none=True))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    else:
        return str(input)
