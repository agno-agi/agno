"""
Session Context Store
=====================
Storage backend for Session Context learning type.

Unlike UserProfileStore which accumulates memories, SessionContextStore
REPLACES context on each extraction. It captures the current state of
a session: what's happened, what's the goal, what's the plan.
"""

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.learn.config import SessionContextConfig
from agno.learn.schemas import BaseSessionContext
from agno.learn.stores.base import BaseLearningStore, from_dict_safe, to_dict_safe
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning


@dataclass
class SessionContextStore(BaseLearningStore):
    """Storage backend for Session Context learning type.

    Handles retrieval, storage, and extraction of session context.
    Context is stored per session_id and is REPLACED (not appended)
    on each extraction.

    Key difference from UserProfileStore:
    - UserProfile: accumulates memories over time
    - SessionContext: snapshot of current session state

    Args:
        config: SessionContextConfig with all settings including db and model.
    """

    config: SessionContextConfig = field(default_factory=SessionContextConfig)

    # State tracking (internal)
    context_updated: bool = False

    def __post_init__(self):
        self.schema = self.config.schema or BaseSessionContext

    # --- Properties for cleaner access ---

    @property
    def db(self) -> Optional[Union[BaseDb, AsyncBaseDb]]:
        return self.config.db

    @property
    def model(self):
        return self.config.model

    # --- Read Operations ---

    def get(self, session_id: str) -> Optional[Any]:
        """Retrieve session context by session_id.

        Args:
            session_id: The unique session identifier.

        Returns:
            Session context as schema instance, or None if not found.
        """
        if not self.db:
            return None

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "get() is not supported with an async DB. Please use aget() instead."
            )

        try:
            result = self.db.get_learning(
                learning_type="session_context",
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
            if isinstance(self.db, AsyncBaseDb):
                result = await self.db.aget_learning(
                    learning_type="session_context",
                    session_id=session_id,
                )
            else:
                result = self.db.get_learning(
                    learning_type="session_context",
                    session_id=session_id,
                )

            if result and result.get("content"):
                return from_dict_safe(self.schema, result["content"])

            return None

        except Exception as e:
            log_debug(f"Error retrieving session context: {e}")
            return None

    # --- Write Operations ---

    def save(self, session_id: str, context: Any) -> None:
        """Save or replace session context.

        Note: Session context is REPLACED, not appended.

        Args:
            session_id: The unique session identifier.
            context: The context data to save.
        """
        if not self.db or not context:
            return

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "save() is not supported with an async DB. Please use asave() instead."
            )

        try:
            content = to_dict_safe(context)
            if not content:
                return

            self.db.upsert_learning(
                id=f"session_context_{session_id}",
                learning_type="session_context",
                session_id=session_id,
                content=content,
            )
            log_debug(f"Saved session context for session_id: {session_id}")

        except Exception as e:
            log_debug(f"Error saving session context: {e}")

    async def asave(self, session_id: str, context: Any) -> None:
        """Async version of save."""
        if not self.db or not context:
            return

        try:
            content = to_dict_safe(context)
            if not content:
                return

            if isinstance(self.db, AsyncBaseDb):
                await self.db.aupsert_learning(
                    id=f"session_context_{session_id}",
                    learning_type="session_context",
                    session_id=session_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=f"session_context_{session_id}",
                    learning_type="session_context",
                    session_id=session_id,
                    content=content,
                )
            log_debug(f"Saved session context for session_id: {session_id}")

        except Exception as e:
            log_debug(f"Error saving session context: {e}")

    # --- Delete Operations ---

    def delete(self, session_id: str) -> bool:
        """Delete session context.

        Args:
            session_id: The unique session identifier.

        Returns:
            True if deleted, False otherwise.
        """
        if not self.db:
            return False

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "delete() is not supported with an async DB. Please use adelete() instead."
            )

        try:
            return self.db.delete_learning(id=f"session_context_{session_id}")
        except Exception as e:
            log_debug(f"Error deleting session context: {e}")
            return False

    async def adelete(self, session_id: str) -> bool:
        """Async version of delete."""
        if not self.db:
            return False

        try:
            if isinstance(self.db, AsyncBaseDb):
                return await self.db.adelete_learning(id=f"session_context_{session_id}")
            else:
                return self.db.delete_learning(id=f"session_context_{session_id}")
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

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "clear() is not supported with an async DB. Please use aclear() instead."
            )

        try:
            empty_context = self.schema(session_id=session_id)
            self.save(session_id, empty_context)
            log_debug(f"Cleared session context for session_id: {session_id}")
        except Exception as e:
            log_debug(f"Error clearing session context: {e}")

    async def aclear(self, session_id: str) -> None:
        """Async version of clear."""
        if not self.db:
            return

        try:
            empty_context = self.schema(session_id=session_id)
            await self.asave(session_id, empty_context)
            log_debug(f"Cleared session context for session_id: {session_id}")
        except Exception as e:
            log_debug(f"Error clearing session context: {e}")

    # --- Extraction Operations ---

    def extract_and_save(
        self,
        messages: List[Message],
        session_id: str,
    ) -> str:
        """Extract session context from messages and save.

        Unlike UserProfileStore which accumulates, this REPLACES the context.

        Args:
            messages: Conversation messages to analyze.
            session_id: The unique session identifier.

        Returns:
            Response from model.
        """
        if self.model is None:
            log_warning("No model provided for session context extraction")
            return "No model provided for session context extraction"

        if not self.db:
            log_warning("No DB provided for session context store")
            return "No DB provided for session context store"

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "extract_and_save() is not supported with an async DB. "
                "Please use aextract_and_save() instead."
            )

        # Skip if no meaningful messages
        if not self._has_meaningful_messages(messages):
            log_debug("No meaningful messages to summarize")
            return "No meaningful messages to summarize"

        log_debug("SessionContextStore: Extracting session context", center=True)

        # Reset state
        self.context_updated = False

        # Get tools
        tools = self._get_extraction_tools(session_id=session_id)
        tool_map = {func.__name__: func for func in tools}

        # Convert to Function objects for model
        functions = self._determine_tools_for_model(tools)

        # Build prompt
        messages_for_model = self._build_extraction_messages(messages)

        # Generate response (model will call tool)
        model_copy = deepcopy(self.model)
        response = model_copy.response(
            messages=messages_for_model,
            tools=functions,
        )

        # Execute tool calls
        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.arguments
                if tool_name in tool_map:
                    try:
                        tool_map[tool_name](**tool_args)
                        self.context_updated = True
                    except Exception as e:
                        log_warning(f"Error executing {tool_name}: {e}")

        log_debug("SessionContextStore: Extraction complete", center=True)

        return response.content or "Context updated" if self.context_updated else "No updates needed"

    async def aextract_and_save(
        self,
        messages: List[Message],
        session_id: str,
    ) -> str:
        """Async version of extract_and_save."""
        if self.model is None:
            log_warning("No model provided for session context extraction")
            return "No model provided for session context extraction"

        if not self.db:
            log_warning("No DB provided for session context store")
            return "No DB provided for session context store"

        if not self._has_meaningful_messages(messages):
            log_debug("No meaningful messages to summarize")
            return "No meaningful messages to summarize"

        log_debug("SessionContextStore: Extracting session context (async)", center=True)

        # Reset state
        self.context_updated = False

        # Get tools
        if isinstance(self.db, AsyncBaseDb):
            tools = await self._aget_extraction_tools(session_id=session_id)
        else:
            tools = self._get_extraction_tools(session_id=session_id)
        tool_map = {func.__name__: func for func in tools}

        # Convert to Function objects for model
        functions = self._determine_tools_for_model(tools)

        # Build prompt
        messages_for_model = self._build_extraction_messages(messages)

        # Generate response (model will call tool)
        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=functions,
        )

        # Execute tool calls
        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.arguments
                if tool_name in tool_map:
                    try:
                        import asyncio
                        if asyncio.iscoroutinefunction(tool_map[tool_name]):
                            await tool_map[tool_name](**tool_args)
                        else:
                            tool_map[tool_name](**tool_args)
                        self.context_updated = True
                    except Exception as e:
                        log_warning(f"Error executing {tool_name}: {e}")

        log_debug("SessionContextStore: Extraction complete", center=True)

        return response.content or "Context updated" if self.context_updated else "No updates needed"

    # --- Private Helpers ---

    def _has_meaningful_messages(self, messages: List[Message]) -> bool:
        """Check if there are meaningful messages to summarize."""
        for msg in messages:
            if msg.role in ["user", "assistant"]:
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    return True
        return False

    def _messages_to_conversation_text(self, messages: List[Message]) -> str:
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

    def _build_extraction_messages(self, messages: List[Message]) -> List[Message]:
        """Build the extraction prompt for the LLM."""
        conversation_text = self._messages_to_conversation_text(messages)

        return [
            self._get_system_message(conversation_text),
            Message(role="user", content="Analyze the conversation and save the session context."),
        ]

    def _get_system_message(self, conversation_text: str) -> Message:
        """Build system message for extraction."""
        # Full override from config
        if self.config.system_message is not None:
            return Message(role="system", content=self.config.system_message)

        enable_planning = self.config.enable_planning

        # Use config instructions or build default
        custom_instructions = self.config.instructions or ""

        if enable_planning:
            system_prompt = dedent(f"""\
                You are a Session Context Manager. Your job is to capture the current state of this conversation.

                ## Your Task
                Analyze the conversation and extract:
                1. **Summary**: What's been discussed? Key decisions, conclusions, important points.
                2. **Goal**: What is the user trying to accomplish? (if apparent)
                3. **Plan**: What steps have been outlined to achieve the goal? (if any)
                4. **Progress**: Which steps have been completed? (if any)

                ## Conversation
                <conversation>
                {conversation_text}
                </conversation>

                ## Guidelines
                - Be concise but capture what matters
                - Focus on information needed to continue the conversation later
                - The summary should stand alone - someone reading it should understand the session
                - Only include goal/plan/progress if they're actually present in the conversation
                - Don't invent or assume - capture what's actually there

                {custom_instructions}

                Use the save_session_context tool to save your analysis.
            """)
        else:
            system_prompt = dedent(f"""\
                You are a Session Context Manager. Your job is to summarize this conversation.

                ## Your Task
                Create a concise summary capturing:
                - Key topics discussed
                - Important decisions or conclusions
                - Outstanding questions or next steps
                - Any context needed to continue the conversation

                ## Conversation
                <conversation>
                {conversation_text}
                </conversation>

                ## Guidelines
                - Be concise but complete
                - Focus on what would help someone pick up where this left off
                - Don't include trivial details
                - Capture the essence, not every exchange

                {custom_instructions}

                Use the save_session_context tool to save your summary.
            """)

        if self.config.additional_instructions:
            system_prompt += f"\n{self.config.additional_instructions}"

        return Message(role="system", content=system_prompt)

    def _determine_tools_for_model(self, tools: List[Callable]) -> List[Union[Function, dict]]:
        """Convert callables to Functions for model."""
        _function_names: List[str] = []
        _functions: List[Union[Function, dict]] = []

        for tool in tools:
            try:
                function_name = tool.__name__
                if function_name in _function_names:
                    continue
                _function_names.append(function_name)
                func = Function.from_callable(tool, strict=True)
                func.strict = True
                _functions.append(func)
                log_debug(f"Added function {func.name}")
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

        return _functions

    def _get_extraction_tools(self, session_id: str) -> List[Callable]:
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

                if enable_planning:
                    context_data["goal"] = goal
                    context_data["plan"] = plan or []
                    context_data["progress"] = progress or []

                context = from_dict_safe(self.schema, context_data)
                self.save(session_id, context)
                log_debug(f"Session context saved: {summary[:50]}...")
                return f"Session context saved"
            except Exception as e:
                log_warning(f"Error saving session context: {e}")
                return f"Error: {e}"

        return [save_session_context]

    async def _aget_extraction_tools(self, session_id: str) -> List[Callable]:
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

                if enable_planning:
                    context_data["goal"] = goal
                    context_data["plan"] = plan or []
                    context_data["progress"] = progress or []

                context = from_dict_safe(self.schema, context_data)
                await self.asave(session_id, context)
                log_debug(f"Session context saved: {summary[:50]}...")
                return f"Session context saved"
            except Exception as e:
                log_warning(f"Error saving session context: {e}")
                return f"Error: {e}"

        return [save_session_context]

    # --- Utility Methods ---

    def get_context_text(self, session_id: str) -> str:
        """Get formatted context text for injection into prompts.

        Args:
            session_id: The session to get context for.

        Returns:
            Formatted string suitable for system prompts.
        """
        context = self.get(session_id)
        if not context:
            return ""

        parts = []

        if hasattr(context, "summary") and context.summary:
            parts.append(f"Session Summary: {context.summary}")

        if hasattr(context, "goal") and context.goal:
            parts.append(f"Current Goal: {context.goal}")

        if hasattr(context, "plan") and context.plan:
            plan_text = "\n".join(f"  {i+1}. {step}" for i, step in enumerate(context.plan))
            parts.append(f"Plan:\n{plan_text}")

        if hasattr(context, "progress") and context.progress:
            progress_text = "\n".join(f"  ✓ {step}" for step in context.progress)
            parts.append(f"Completed:\n{progress_text}")

        return "\n\n".join(parts)

    async def aget_context_text(self, session_id: str) -> str:
        """Async version of get_context_text."""
        context = await self.aget(session_id)
        if not context:
            return ""

        parts = []

        if hasattr(context, "summary") and context.summary:
            parts.append(f"Session Summary: {context.summary}")

        if hasattr(context, "goal") and context.goal:
            parts.append(f"Current Goal: {context.goal}")

        if hasattr(context, "plan") and context.plan:
            plan_text = "\n".join(f"  {i+1}. {step}" for i, step in enumerate(context.plan))
            parts.append(f"Plan:\n{plan_text}")

        if hasattr(context, "progress") and context.progress:
            progress_text = "\n".join(f"  ✓ {step}" for step in context.progress)
            parts.append(f"Completed:\n{progress_text}")

        return "\n\n".join(parts)
