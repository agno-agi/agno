"""
Session Context Store
=====================
Storage backend for Session Context learning type.

Unlike UserProfileStore which ACCUMULATES memories, SessionContextStore
REPLACES context on each extraction. It captures the current state of
a session: what's happened, what's the goal, what's the plan.

Key Features:
- Summary extraction from conversations
- Optional planning mode (goal, plan, progress tracking)
- Session-scoped storage (each session_id has one context)
- No agent tool (system-managed only)
"""

from copy import deepcopy
from dataclasses import dataclass, field
from os import getenv
from textwrap import dedent
from typing import Any, Callable, List, Optional, Union

from agno.learn.config import SessionContextConfig
from agno.learn.schemas import SessionContext
from agno.learn.stores.protocol import LearningStore, from_dict_safe, to_dict_safe
from agno.utils.log import (
    log_debug,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)

# Conditional imports for type checking
try:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.message import Message
    from agno.tools.function import Function
except ImportError:
    pass


@dataclass
class SessionContextStore(LearningStore):
    """Storage backend for Session Context learning type.

    Handles retrieval, storage, and extraction of session context.
    Context is stored per session_id and is REPLACED (not appended)
    on each extraction.

    Key difference from UserProfileStore:
    - UserProfile: accumulates memories over time
    - SessionContext: snapshot of current session state

    Usage:
        >>> store = SessionContextStore(config=SessionContextConfig(db=db, model=model))
        >>>
        >>> # Extract context from conversation
        >>> store.extract_and_save(messages, session_id="session123")
        >>>
        >>> # Get context
        >>> context = store.get("session123")
        >>> print(context.summary)
        >>>
        >>> # With planning enabled
        >>> store = SessionContextStore(config=SessionContextConfig(
        ...     db=db, model=model, enable_planning=True
        ... ))
        >>> store.extract_and_save(messages, session_id="session123")
        >>> context = store.get("session123")
        >>> print(context.goal, context.plan, context.progress)

    Args:
        config: SessionContextConfig with all settings including db and model.
        debug_mode: Enable debug logging.
    """

    config: SessionContextConfig = field(default_factory=SessionContextConfig)
    debug_mode: bool = False

    # State tracking (internal)
    context_updated: bool = field(default=False, init=False)
    _schema: Any = field(default=None, init=False)

    def __post_init__(self):
        self._schema = self.config.schema or SessionContext

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """Unique identifier for this learning type."""
        return "session_context"

    @property
    def schema(self) -> Any:
        """Schema class used for context."""
        return self._schema

    def recall(
        self,
        session_id: str,
        **kwargs,
    ) -> Optional[Any]:
        """Retrieve session context from storage.

        Args:
            session_id: The session to retrieve context for (required).
            **kwargs: Additional context (ignored).

        Returns:
            Session context, or None if not found.
        """
        if not session_id:
            return None
        return self.get(session_id=session_id)

    async def arecall(
        self,
        session_id: str,
        **kwargs,
    ) -> Optional[Any]:
        """Async version of recall."""
        if not session_id:
            return None
        return await self.aget(session_id=session_id)

    def process(
        self,
        messages: List[Any],
        session_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract session context from messages.

        Args:
            messages: Conversation messages to analyze.
            session_id: The session to update context for (required).
            user_id: Optional user context (stored in context).
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context (ignored).
        """
        if not session_id or not messages:
            return
        self.extract_and_save(
            messages=messages,
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    async def aprocess(
        self,
        messages: List[Any],
        session_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Async version of process."""
        if not session_id or not messages:
            return
        await self.aextract_and_save(
            messages=messages,
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Args:
            data: Session context data from recall().

        Returns:
            Context string to inject into the agent's system prompt, or empty string if no data.
        """
        if not data:
            return ""

        context_text = None
        if hasattr(data, "get_context_text"):
            context_text = data.get_context_text()
        elif hasattr(data, "summary") and data.summary:
            context_text = self._format_context(context=data)

        if not context_text:
            return ""

        return (
            dedent("""\
            <session_context>
            Earlier in this session:
            """)
            + context_text
            + dedent("""

            Use this for continuity. Current conversation takes precedence.
            </session_context>""")
        )

    def get_tools(self, **kwargs) -> List[Callable]:
        """Session context has no agent tools (system-managed only).

        Returns:
            Empty list - session context is managed by background extraction only.
        """
        return []

    async def aget_tools(self, **kwargs) -> List[Callable]:
        """Async version of get_tools."""
        return []

    @property
    def was_updated(self) -> bool:
        """Check if context was updated in last operation."""
        return self.context_updated

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def db(self) -> Optional[Union["BaseDb", "AsyncBaseDb"]]:
        """Database backend."""
        return self.config.db

    @property
    def model(self):
        """Model for extraction."""
        return self.config.model

    # =========================================================================
    # Debug/Logging
    # =========================================================================

    def set_log_level(self):
        """Set log level based on debug_mode or environment variable."""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get(self, session_id: str) -> Optional[Any]:
        """Retrieve session context by session_id.

        Args:
            session_id: The unique session identifier.

        Returns:
            Session context as schema instance, or None if not found.
        """
        if not self.db:
            return None

        try:
            result = self.db.get_learning(
                learning_type=self.learning_type,
                session_id=session_id,
            )

            if result and result.get("content"):
                return from_dict_safe(self.schema, result["content"])

            return None

        except Exception as e:
            log_debug(f"Error retrieving session context: {e}")
            return None

    async def aget(self, session_id: str) -> Optional[Any]:
        """Async version of get."""
        if not self.db:
            return None

        try:
            if hasattr(self.db, "aget_learning"):
                result = await self.db.aget_learning(
                    learning_type=self.learning_type,
                    session_id=session_id,
                )
            else:
                result = self.db.get_learning(
                    learning_type=self.learning_type,
                    session_id=session_id,
                )

            if result and result.get("content"):
                return from_dict_safe(self.schema, result["content"])

            return None

        except Exception as e:
            log_debug(f"Error retrieving session context: {e}")
            return None

    # =========================================================================
    # Write Operations
    # =========================================================================

    def save(
        self,
        session_id: str,
        context: Any,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Save or replace session context.

        Note: Session context is REPLACED, not appended.

        Args:
            session_id: The unique session identifier.
            context: The context data to save.
            user_id: Optional user context.
            agent_id: Optional agent context.
            team_id: Optional team context.
        """
        if not self.db or not context:
            return

        try:
            content = to_dict_safe(context)
            if not content:
                return

            self.db.upsert_learning(
                id=self._build_context_id(session_id=session_id),
                learning_type=self.learning_type,
                session_id=session_id,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                content=content,
            )
            log_debug(f"Saved session context for session_id: {session_id}")

        except Exception as e:
            log_debug(f"Error saving session context: {e}")

    async def asave(
        self,
        session_id: str,
        context: Any,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Async version of save."""
        if not self.db or not context:
            return

        try:
            content = to_dict_safe(context)
            if not content:
                return

            if hasattr(self.db, "aupsert_learning"):
                await self.db.aupsert_learning(
                    id=self._build_context_id(session_id=session_id),
                    learning_type=self.learning_type,
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=self._build_context_id(session_id=session_id),
                    learning_type=self.learning_type,
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            log_debug(f"Saved session context for session_id: {session_id}")

        except Exception as e:
            log_debug(f"Error saving session context: {e}")

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete(self, session_id: str) -> bool:
        """Delete session context.

        Args:
            session_id: The unique session identifier.

        Returns:
            True if deleted, False otherwise.
        """
        if not self.db:
            return False

        try:
            context_id = self._build_context_id(session_id=session_id)
            return self.db.delete_learning(id=context_id)
        except Exception as e:
            log_debug(f"Error deleting session context: {e}")
            return False

    async def adelete(self, session_id: str) -> bool:
        """Async version of delete."""
        if not self.db:
            return False

        try:
            context_id = self._build_context_id(session_id=session_id)
            if hasattr(self.db, "adelete_learning"):
                return await self.db.adelete_learning(id=context_id)
            else:
                return self.db.delete_learning(id=context_id)
        except Exception as e:
            log_debug(f"Error deleting session context: {e}")
            return False

    def clear(self, session_id: str) -> None:
        """Clear session context (reset to empty).

        Args:
            session_id: The unique session identifier.
        """
        if not self.db:
            return

        try:
            empty_context = self.schema(session_id=session_id)
            self.save(session_id=session_id, context=empty_context)
            log_debug(f"Cleared session context for session_id: {session_id}")
        except Exception as e:
            log_debug(f"Error clearing session context: {e}")

    async def aclear(self, session_id: str) -> None:
        """Async version of clear."""
        if not self.db:
            return

        try:
            empty_context = self.schema(session_id=session_id)
            await self.asave(session_id=session_id, context=empty_context)
            log_debug(f"Cleared session context for session_id: {session_id}")
        except Exception as e:
            log_debug(f"Error clearing session context: {e}")

    # =========================================================================
    # Extraction Operations
    # =========================================================================

    def extract_and_save(
        self,
        messages: List["Message"],
        session_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Extract session context from messages and save.

        Unlike UserProfileStore which accumulates, this REPLACES the context.

        Args:
            messages: Conversation messages to analyze.
            session_id: The unique session identifier.
            user_id: Optional user context.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            Response from model.
        """
        if self.model is None:
            log_warning("No model provided for session context extraction")
            return "No model provided for session context extraction"

        if not self.db:
            log_warning("No DB provided for session context store")
            return "No DB provided for session context store"

        # Skip if no meaningful messages
        if not self._has_meaningful_messages(messages=messages):
            log_debug("No meaningful messages to summarize")
            return "No meaningful messages to summarize"

        log_debug("SessionContextStore: Extracting session context", center=True)

        # Reset state
        self.context_updated = False

        # Get tools
        tools = self._get_extraction_tools(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )
        tool_map = {func.__name__: func for func in tools}

        # Convert to Function objects for model
        functions = self._build_functions_for_model(tools=tools)

        # Build prompt
        messages_for_model = self._build_extraction_messages(messages=messages)

        # Generate response (model will call tool)
        model_copy = deepcopy(self.model)
        response = model_copy.response(
            messages=messages_for_model,
            tools=functions,
        )

        # Execute tool calls
        if response.tool_executions:
            for tool_exec in response.tool_executions:
                tool_name = tool_exec.tool_name
                tool_args = tool_exec.tool_args
                if tool_name in tool_map:
                    try:
                        tool_map[tool_name](**tool_args)
                        self.context_updated = True
                    except Exception as e:
                        log_warning(f"Error executing {tool_name}: {e}")

        log_debug("SessionContextStore: Extraction complete", center=True)

        return response.content or ("Context updated" if self.context_updated else "No updates needed")

    async def aextract_and_save(
        self,
        messages: List["Message"],
        session_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Async version of extract_and_save."""
        if self.model is None:
            log_warning("No model provided for session context extraction")
            return "No model provided for session context extraction"

        if not self.db:
            log_warning("No DB provided for session context store")
            return "No DB provided for session context store"

        if not self._has_meaningful_messages(messages=messages):
            log_debug("No meaningful messages to summarize")
            return "No meaningful messages to summarize"

        log_debug("SessionContextStore: Extracting session context (async)", center=True)

        # Reset state
        self.context_updated = False

        # Get tools
        tools = await self._aget_extraction_tools(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )
        tool_map = {func.__name__: func for func in tools}

        # Convert to Function objects for model
        functions = self._build_functions_for_model(tools=tools)

        # Build prompt
        messages_for_model = self._build_extraction_messages(messages=messages)

        # Generate response (model will call tool)
        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=functions,
        )

        # Execute tool calls
        if response.tool_executions:
            import asyncio

            for tool_exec in response.tool_executions:
                tool_name = tool_exec.tool_name
                tool_args = tool_exec.tool_args
                if tool_name in tool_map:
                    try:
                        if asyncio.iscoroutinefunction(tool_map[tool_name]):
                            await tool_map[tool_name](**tool_args)
                        else:
                            tool_map[tool_name](**tool_args)
                        self.context_updated = True
                    except Exception as e:
                        log_warning(f"Error executing {tool_name}: {e}")

        log_debug("SessionContextStore: Extraction complete", center=True)

        return response.content or ("Context updated" if self.context_updated else "No updates needed")

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_context_text(self, session_id: str) -> str:
        """Get formatted context text for injection into prompts.

        Args:
            session_id: The session to get context for.

        Returns:
            Formatted string suitable for system prompts.
        """
        context = self.get(session_id=session_id)
        return self._format_context(context=context) if context else ""

    async def aget_context_text(self, session_id: str) -> str:
        """Async version of get_context_text."""
        context = await self.aget(session_id=session_id)
        return self._format_context(context=context) if context else ""

    def _format_context(self, context: Any) -> str:
        """Format a context object to text."""
        parts = []

        if hasattr(context, "summary") and context.summary:
            parts.append(f"Session Summary: {context.summary}")

        if hasattr(context, "goal") and context.goal:
            parts.append(f"Current Goal: {context.goal}")

        if hasattr(context, "plan") and context.plan:
            plan_text = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(context.plan))
            parts.append(f"Plan:\n{plan_text}")

        if hasattr(context, "progress") and context.progress:
            progress_text = "\n".join(f"  ✓ {step}" for step in context.progress)
            parts.append(f"Completed:\n{progress_text}")

        return "\n\n".join(parts)

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _build_context_id(self, session_id: str) -> str:
        """Build a unique context ID."""
        return f"session_context_{session_id}"

    def _has_meaningful_messages(self, messages: List["Message"]) -> bool:
        """Check if there are meaningful messages to summarize."""
        for msg in messages:
            if msg.role in ["user", "assistant"]:
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    return True
        return False

    def _messages_to_conversation_text(self, messages: List["Message"]) -> str:
        """Convert messages to conversation text for the prompt."""
        parts = []
        for msg in messages:
            if msg.role == "user":
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    parts.append(f"User: {content}")
                else:
                    # Handle media-only messages
                    media_types = []
                    if hasattr(msg, "images") and msg.images:
                        media_types.append(f"{len(msg.images)} image(s)")
                    if hasattr(msg, "videos") and msg.videos:
                        media_types.append(f"{len(msg.videos)} video(s)")
                    if hasattr(msg, "audio") and msg.audio:
                        media_types.append(f"{len(msg.audio)} audio file(s)")
                    if hasattr(msg, "files") and msg.files:
                        media_types.append(f"{len(msg.files)} file(s)")
                    if media_types:
                        parts.append(f"User: [Provided {', '.join(media_types)}]")
            elif msg.role in ["assistant", "model"]:
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    parts.append(f"Assistant: {content}")
        return "\n".join(parts)

    def _build_extraction_messages(self, messages: List["Message"]) -> List["Message"]:
        """Build the extraction prompt for the LLM."""
        from agno.models.message import Message

        conversation_text = self._messages_to_conversation_text(messages=messages)

        return [
            self._get_system_message(conversation_text=conversation_text),
            Message(role="user", content="Analyze the conversation and save the session context."),
        ]

    def _get_system_message(self, conversation_text: str) -> "Message":
        """Build system message for extraction."""
        from agno.models.message import Message

        # Full override from config
        if self.config.system_message is not None:
            return Message(role="system", content=self.config.system_message)

        enable_planning = self.config.enable_planning
        custom_instructions = self.config.instructions or ""

        if enable_planning:
            system_prompt = (
                dedent("""\
                You are a Session Context Manager. Your job is to capture the current state of this conversation.

                ## Your Task
                Analyze the conversation and extract:
                1. **Summary**: What's been discussed? Key decisions, conclusions, important points.
                2. **Goal**: What is the user trying to accomplish? (if apparent)
                3. **Plan**: What steps have been outlined to achieve the goal? (if any)
                4. **Progress**: Which steps have been completed? (if any)

                ## Conversation
                <conversation>
            """)
                + conversation_text
                + dedent("""
                </conversation>

                ## Guidelines
                - Be concise but capture what matters
                - Focus on information needed to continue the conversation later
                - The summary should stand alone - someone reading it should understand the session
                - Only include goal/plan/progress if they're actually present in the conversation
                - Don't invent or assume - capture what's actually there

            """)
                + custom_instructions
                + dedent("""
                Use the save_session_context tool to save your analysis.\
            """)
            )
        else:
            system_prompt = (
                dedent("""\
                You are a Session Context Manager. Your job is to summarize this conversation.

                ## Your Task
                Create a concise summary capturing:
                - Key topics discussed
                - Important decisions or conclusions
                - Outstanding questions or next steps
                - Any context needed to continue the conversation

                ## Conversation
                <conversation>
            """)
                + conversation_text
                + dedent("""
                </conversation>

                ## Guidelines
                - Be concise but complete
                - Focus on what would help someone pick up where this left off
                - Don't include trivial details
                - Capture the essence, not every exchange

            """)
                + custom_instructions
                + dedent("""
                Use the save_session_context tool to save your summary.\
            """)
            )

        if self.config.additional_instructions:
            system_prompt += f"\n\n{self.config.additional_instructions}"

        return Message(role="system", content=system_prompt)

    def _build_functions_for_model(self, tools: List[Callable]) -> List["Function"]:
        """Convert callables to Functions for model."""
        from agno.tools.function import Function

        functions = []
        seen_names = set()

        for tool in tools:
            try:
                name = tool.__name__
                if name in seen_names:
                    continue
                seen_names.add(name)

                func = Function.from_callable(tool, strict=True)
                func.strict = True
                functions.append(func)
                log_debug(f"Added function {func.name}")
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

        return functions

    def _get_extraction_tools(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get sync extraction tools for the model."""
        enable_planning = self.config.enable_planning

        def save_session_context(
            summary: str,
            goal: Optional[str] = None,
            plan: Optional[List[str]] = None,
            progress: Optional[List[str]] = None,
        ) -> str:
            """Save the session context.

            Args:
                summary: Brief summary of what's been discussed in this session.
                goal: The user's main objective (if apparent from conversation).
                plan: Steps to achieve the goal (if discussed).
                progress: Which steps have been completed (if any).

            Returns:
                Confirmation message.
            """
            try:
                context_data = {
                    "session_id": session_id,
                    "summary": summary,
                }

                if user_id:
                    context_data["user_id"] = user_id
                if agent_id:
                    context_data["agent_id"] = agent_id
                if team_id:
                    context_data["team_id"] = team_id

                if enable_planning:
                    context_data["goal"] = goal
                    context_data["plan"] = plan or []
                    context_data["progress"] = progress or []

                context = from_dict_safe(self.schema, context_data)
                self.save(
                    session_id=session_id,
                    context=context,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
                log_debug(f"Session context saved: {summary[:50]}...")
                return "Session context saved"
            except Exception as e:
                log_warning(f"Error saving session context: {e}")
                return f"Error: {e}"

        return [save_session_context]

    async def _aget_extraction_tools(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get async extraction tools for the model."""
        enable_planning = self.config.enable_planning

        async def save_session_context(
            summary: str,
            goal: Optional[str] = None,
            plan: Optional[List[str]] = None,
            progress: Optional[List[str]] = None,
        ) -> str:
            """Save the session context.

            Args:
                summary: Brief summary of what's been discussed in this session.
                goal: The user's main objective (if apparent from conversation).
                plan: Steps to achieve the goal (if discussed).
                progress: Which steps have been completed (if any).

            Returns:
                Confirmation message.
            """
            try:
                context_data = {
                    "session_id": session_id,
                    "summary": summary,
                }

                if user_id:
                    context_data["user_id"] = user_id
                if agent_id:
                    context_data["agent_id"] = agent_id
                if team_id:
                    context_data["team_id"] = team_id

                if enable_planning:
                    context_data["goal"] = goal
                    context_data["plan"] = plan or []
                    context_data["progress"] = progress or []

                context = from_dict_safe(self.schema, context_data)
                await self.asave(
                    session_id=session_id,
                    context=context,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
                log_debug(f"Session context saved: {summary[:50]}...")
                return "Session context saved"
            except Exception as e:
                log_warning(f"Error saving session context: {e}")
                return f"Error: {e}"

        return [save_session_context]
