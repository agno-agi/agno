"""
Session Context Store
=====================
Storage backend for Session Context learning type.

Stores the current state of a session: what's happened, what's the goal, what's the plan.

Key Features:
- Summary extraction from conversations
- Optional planning mode (goal, plan, progress tracking)
- Session-scoped storage (each session_id has one context)
- Builds on previous context (doesn't start from scratch each time)
- No agent tool (system-managed only)

Scope:
- Context is retrieved by session_id only
- agent_id/team_id stored in DB columns for audit trail

Key Behavior:
- Extraction receives the previous context and updates it
- This ensures continuity even when message history is truncated
- Previous context + new messages → Updated context

Supported Modes:
- ALWAYS only. SessionContextStore does not support AGENTIC, PROPOSE, or HITL modes.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from agno.learn.config import LearningMode, SessionContextConfig
from agno.learn.schemas import SessionContext
from agno.learn.stores.protocol import LearningStore
from agno.learn.utils import from_dict_safe, to_dict_safe
from agno.utils.log import (
    log_debug,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)

try:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.message import Message
    from agno.tools.function import Function
except ImportError:
    pass


@dataclass
class SessionContextStore(LearningStore):
    """Storage backend for Session Context learning type.

    Context is retrieved by session_id only — all agents sharing the same DB
    will see the same context for a given session. agent_id and team_id are
    stored in DB columns for audit purposes.

    Key difference from UserProfileStore:
    - UserProfile: accumulates memories over time
    - SessionContext: snapshot of current session state (updated on each extraction)

    Key behavior:
    - Extraction builds on previous context rather than starting fresh
    - This ensures continuity even when message history is truncated
    - Previous summary, goal, plan, progress are preserved and updated

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

        if self.config.mode != LearningMode.ALWAYS:
            log_warning(
                f"SessionContextStore only supports ALWAYS mode, got {self.config.mode}. Ignoring mode setting."
            )

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

    def recall(self, session_id: str, **kwargs) -> Optional[Any]:
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

    async def arecall(self, session_id: str, **kwargs) -> Optional[Any]:
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
            user_id: User context (stored for audit).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            **kwargs: Additional context (ignored).
        """
        # process only supported in ALWAYS mode
        # for programmatic extraction, use extract_and_save directly
        if self.config.mode != LearningMode.ALWAYS:
            return

        if not session_id or not messages:
            return

        self.extract_and_save(
            messages=messages,
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            run_response=kwargs.get("run_response"),
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
        if self.config.mode != LearningMode.ALWAYS:
            return

        if not session_id or not messages:
            return

        await self.aextract_and_save(
            messages=messages,
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            run_response=kwargs.get("run_response"),
        )

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Formats session context for injection into the agent's system prompt.
        Session context provides continuity within a single conversation,
        especially useful when message history gets truncated.

        Args:
            data: Session context data from recall().

        Returns:
            Context string to inject into the agent's system prompt.
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

        return dedent(f"""\
            <session_context>
            This is a continuation of an ongoing session. Here's where things stand:

            {context_text}

            <session_context_guidelines>
            Use this context to maintain continuity:
            - Reference earlier decisions and conclusions naturally
            - Don't re-ask questions that have already been answered
            - Build on established understanding rather than starting fresh
            - If the user references something from "earlier," this context has the details

            Current messages take precedence if there's any conflict with this summary.
            </session_context_guidelines>
            </session_context>\
        """)

    def get_tools(self, **kwargs) -> List[Callable]:
        """Session context has no agent tools (system-managed only)."""
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

            if result and result.get("content"):  # type: ignore[union-attr]
                return from_dict_safe(self.schema, result["content"])  # type: ignore[index]

            return None

        except Exception as e:
            log_debug(f"SessionContextStore.get failed for session_id={session_id}: {e}")
            return None

    async def aget(self, session_id: str) -> Optional[Any]:
        """Async version of get."""
        if not self.db:
            return None

        try:
            if isinstance(self.db, AsyncBaseDb):
                result = await self.db.get_learning(
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
            log_debug(f"SessionContextStore.aget failed for session_id={session_id}: {e}")
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

        Args:
            session_id: The unique session identifier.
            context: The context data to save.
            user_id: User context (stored in DB column for audit).
            agent_id: Agent context (stored in DB column for audit).
            team_id: Team context (stored in DB column for audit).
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
            log_debug(f"SessionContextStore.save: saved context for session_id={session_id}")

        except Exception as e:
            log_debug(f"SessionContextStore.save failed for session_id={session_id}: {e}")

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

            if isinstance(self.db, AsyncBaseDb):
                await self.db.upsert_learning(
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
            log_debug(f"SessionContextStore.asave: saved context for session_id={session_id}")

        except Exception as e:
            log_debug(f"SessionContextStore.asave failed for session_id={session_id}: {e}")

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
            return self.db.delete_learning(id=context_id)  # type: ignore[return-value]
        except Exception as e:
            log_debug(f"SessionContextStore.delete failed for session_id={session_id}: {e}")
            return False

    async def adelete(self, session_id: str) -> bool:
        """Async version of delete."""
        if not self.db:
            return False

        try:
            context_id = self._build_context_id(session_id=session_id)
            if isinstance(self.db, AsyncBaseDb):
                return await self.db.delete_learning(id=context_id)
            else:
                return self.db.delete_learning(id=context_id)
        except Exception as e:
            log_debug(f"SessionContextStore.adelete failed for session_id={session_id}: {e}")
            return False

    def clear(
        self,
        session_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Clear session context (reset to empty).

        Args:
            session_id: The unique session identifier.
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
        """
        if not self.db:
            return

        try:
            empty_context = self.schema(session_id=session_id)
            self.save(session_id=session_id, context=empty_context, agent_id=agent_id, team_id=team_id)
            log_debug(f"SessionContextStore.clear: cleared context for session_id={session_id}")
        except Exception as e:
            log_debug(f"SessionContextStore.clear failed for session_id={session_id}: {e}")

    async def aclear(
        self,
        session_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Async version of clear."""
        if not self.db:
            return

        try:
            empty_context = self.schema(session_id=session_id)
            await self.asave(session_id=session_id, context=empty_context, agent_id=agent_id, team_id=team_id)
            log_debug(f"SessionContextStore.aclear: cleared context for session_id={session_id}")
        except Exception as e:
            log_debug(f"SessionContextStore.aclear failed for session_id={session_id}: {e}")

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
        run_response: Optional[Any] = None,
    ) -> str:
        """Extract session context from messages and save.

        Builds on previous context rather than starting from scratch.

        Args:
            messages: Conversation messages to analyze.
            session_id: The unique session identifier.
            user_id: User context (stored for audit).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).

        Returns:
            Response from model.
        """
        if self.model is None:
            log_warning("SessionContextStore.extract_and_save: no model provided")
            return "No model provided for session context extraction"

        if not self.db:
            log_warning("SessionContextStore.extract_and_save: no database provided")
            return "No DB provided for session context store"

        log_debug("SessionContextStore: Extracting session context", center=True)

        self.context_updated = False

        # Get existing context to build upon
        existing_context = self.get(session_id=session_id)

        conversation_text = self._messages_to_text(messages=messages)

        tools = self._get_extraction_tools(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            existing_context=existing_context,
        )

        functions = self._build_functions_for_model(tools=tools)

        system_message = self._get_system_message(
            conversation_text=conversation_text,
            existing_context=existing_context,
        )

        messages_for_model = [
            system_message,
            # For models that require a non-system message
            Message(
                role="user",
                content="Please analyze the conversation and update the session context using the available tools.",
            ),
        ]

        model_copy = deepcopy(self.model)
        response = model_copy.response(
            messages=messages_for_model,
            tools=functions,
        )

        if run_response is not None and response.response_usage is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model_copy, ModelType.LEARNING_MODEL, run_response)

        if response.tool_executions:
            self.context_updated = True

        log_debug("SessionContextStore: Extraction complete", center=True)

        return response.content or ("Context updated" if self.context_updated else "No updates needed")

    async def aextract_and_save(
        self,
        messages: List["Message"],
        session_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        run_response: Optional[Any] = None,
    ) -> str:
        """Async version of extract_and_save."""
        if self.model is None:
            log_warning("SessionContextStore.aextract_and_save: no model provided")
            return "No model provided for session context extraction"

        if not self.db:
            log_warning("SessionContextStore.aextract_and_save: no database provided")
            return "No DB provided for session context store"

        log_debug("SessionContextStore: Extracting session context (async)", center=True)

        self.context_updated = False

        # Get existing context to build upon
        existing_context = await self.aget(session_id=session_id)

        conversation_text = self._messages_to_text(messages=messages)

        tools = await self._aget_extraction_tools(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            existing_context=existing_context,
        )

        functions = self._build_functions_for_model(tools=tools)

        system_message = self._get_system_message(
            conversation_text=conversation_text,
            existing_context=existing_context,
        )

        messages_for_model = [
            system_message,
            # For models that require a non-system message
            Message(
                role="user",
                content="Please analyze the conversation and update the session context using the available tools.",
            ),
        ]

        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=functions,
        )

        if run_response is not None and response.response_usage is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model_copy, ModelType.LEARNING_MODEL, run_response)

        if response.tool_executions:
            self.context_updated = True

        log_debug("SessionContextStore: Extraction complete", center=True)

        return response.content or ("Context updated" if self.context_updated else "No updates needed")

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _build_context_id(self, session_id: str) -> str:
        """Build a unique context ID."""
        return f"session_context_{session_id}"

    def _format_context(self, context: Any) -> str:
        """Format context data for display in agent prompt."""
        parts = []

        if hasattr(context, "summary") and context.summary:
            parts.append(f"**Summary:** {context.summary}")

        if hasattr(context, "goal") and context.goal:
            parts.append(f"**Current Goal:** {context.goal}")

        if hasattr(context, "plan") and context.plan:
            plan_items = "\n  - ".join(context.plan)
            parts.append(f"**Plan:**\n  - {plan_items}")

        if hasattr(context, "progress") and context.progress:
            progress_items = "\n  - ".join(f"✓ {item}" for item in context.progress)
            parts.append(f"**Completed:**\n  - {progress_items}")

        return "\n\n".join(parts)

    def _messages_to_text(self, messages: List["Message"]) -> str:
        """Convert messages to text for extraction."""
        parts = []
        for msg in messages:
            if msg.role == "user":
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    parts.append(f"User: {content}")
            elif msg.role in ["assistant", "model"]:
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    parts.append(f"Assistant: {content}")
        return "\n".join(parts)

    def _get_system_message(
        self,
        conversation_text: str,
        existing_context: Optional[Any] = None,
    ) -> "Message":
        """Build system message for extraction.

        Creates a prompt that guides the model to extract and update session context,
        building on previous context rather than starting fresh each time.
        """
        from agno.models.message import Message

        if self.config.system_message is not None:
            return Message(role="system", content=self.config.system_message)

        enable_planning = self.config.enable_planning
        custom_instructions = self.config.instructions or ""

        # Build previous context section
        previous_context_section = ""
        if existing_context:
            previous_context_section = dedent("""\
                ## Previous Context

                This session already has context from earlier exchanges. Your job is to UPDATE it,
                not replace it. Integrate new information while preserving what's still relevant.

            """)
            if hasattr(existing_context, "summary") and existing_context.summary:
                previous_context_section += f"**Previous summary:**\n{existing_context.summary}\n\n"
            if enable_planning:
                if hasattr(existing_context, "goal") and existing_context.goal:
                    previous_context_section += f"**Established goal:** {existing_context.goal}\n"
                if hasattr(existing_context, "plan") and existing_context.plan:
                    previous_context_section += f"**Current plan:** {', '.join(existing_context.plan)}\n"
                if hasattr(existing_context, "progress") and existing_context.progress:
                    previous_context_section += f"**Completed so far:** {', '.join(existing_context.progress)}\n"
            previous_context_section += "\n"

        if enable_planning:
            system_prompt = (
                dedent("""\
                You are a Session Context Manager. Your job is to maintain a living summary of this
                conversation that enables continuity - especially important when message history
                gets truncated.

                ## Philosophy

                Think of session context like notes a colleague would take during a working session:
                - Not a transcript, but the current STATE of the work
                - What's been decided, what's still open
                - Where things stand, not every step of how we got here
                - What someone would need to pick up exactly where we left off

                ## What to Capture

                1. **Summary**: The essential narrative of this session
                   - Key topics and how they were resolved
                   - Important decisions and their rationale
                   - Current state of any work in progress
                   - Open questions or unresolved items

                2. **Goal**: What the user is ultimately trying to accomplish
                   - May evolve as the conversation progresses
                   - Keep updating if the user clarifies or pivots

                3. **Plan**: The approach being taken (if one has emerged)
                   - Steps that have been outlined
                   - Update if the plan changes

                4. **Progress**: What's been completed
                   - Helps track where we are in multi-step work
                   - Mark items done as they're completed

            """)
                + previous_context_section
                + dedent("""\
                ## New Conversation to Integrate

                <conversation>
            """)
                + conversation_text
                + dedent("""
                </conversation>

                ## Guidelines

                **Integration, not replacement:**
                - BUILD ON previous context - don't lose earlier information
                - If previous summary mentioned topic X and it's still relevant, keep it
                - If something was resolved or superseded, update accordingly

                **Quality of summary:**
                - Should stand alone - reader should understand the full session
                - Capture conclusions and current state, not conversation flow
                - Be concise but complete - aim for density of useful information
                - Include enough detail that work could continue seamlessly

                **Good summary characteristics:**
                - "User is building a REST API for inventory management. Decided on FastAPI over Flask
                  for async support. Schema design complete with Products, Categories, and Suppliers tables.
                  Currently implementing the Products endpoint with pagination."

                **Poor summary characteristics:**
                - "User asked about APIs. We discussed some options. Made some decisions."
                  (Too vague - doesn't capture what was actually decided)\
            """)
                + custom_instructions
                + dedent("""

                Save your updated context using the save_session_context tool.\
            """)
            )
        else:
            system_prompt = (
                dedent("""\
                You are a Session Context Manager. Your job is to maintain a living summary of this
                conversation that enables continuity - especially important when message history
                gets truncated.

                ## Philosophy

                Think of session context like meeting notes:
                - Not a transcript, but what matters for continuity
                - What was discussed, decided, and concluded
                - Current state of any ongoing work
                - What someone would need to pick up where we left off

                ## What to Capture

                Create a summary that includes:
                - **Topics covered** and how they were addressed
                - **Decisions made** and key conclusions
                - **Current state** of any work in progress
                - **Open items** - questions pending, next steps discussed
                - **Important details** that would be awkward to re-establish

            """)
                + previous_context_section
                + dedent("""\
                ## New Conversation to Integrate

                <conversation>
            """)
                + conversation_text
                + dedent("""
                </conversation>

                ## Guidelines

                **Integration, not replacement:**
                - BUILD ON previous summary - don't lose earlier context
                - Weave new information into existing narrative
                - If something is superseded, update it; if still relevant, preserve it

                **Quality standards:**

                *Good summary:*
                "Helping user debug a memory leak in their Node.js application. Identified that the
                issue occurs in the WebSocket handler - connections aren't being cleaned up on
                disconnect. Reviewed the connection management code and found missing event listener
                removal. User is implementing the fix with a connection registry pattern. Next step:
                test under load to verify the leak is resolved."

                *Poor summary:*
                "User had a bug. We looked at code. Found some issues. Working on fixing it."
                (Missing: what bug, what code, what issues, what fix)

                **Aim for:**
                - Density of useful information
                - Standalone comprehensibility
                - Enough detail to continue seamlessly
                - Focus on state over story
            """)
                + custom_instructions
                + dedent("""
                Save your updated summary using the save_session_context tool.\
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
        existing_context: Optional[Any] = None,
    ) -> List[Callable]:
        """Get sync extraction tools for the model."""
        enable_planning = self.config.enable_planning

        if enable_planning:
            # Full planning mode: include goal, plan, progress parameters
            def save_session_context(
                summary: str,
                goal: Optional[str] = None,
                plan: Optional[List[str]] = None,
                progress: Optional[List[str]] = None,
            ) -> str:
                """Save the updated session context.

                The summary should capture the current state of the conversation in a way that
                enables seamless continuation. Think: "What would someone need to know to pick
                up exactly where we left off?"

                Args:
                    summary: A comprehensive summary that integrates previous context with new
                            developments. Should be standalone - readable without seeing the
                            actual messages. Capture:
                            - What's being worked on and why
                            - Key decisions made and their rationale
                            - Current state of any work in progress
                            - Open questions or pending items

                            Good: "Debugging a React performance issue in the user's dashboard.
                            Identified unnecessary re-renders in the DataTable component caused by
                            inline object creation in props. Implemented useMemo for the column
                            definitions. Testing shows 60% render reduction. Next: profile the
                            filtering logic which may have similar issues."

                            Bad: "Looked at React code. Found some performance issues. Made changes."

                    goal: The user's primary objective for this session (if one is apparent).
                          Update if the goal has evolved or been clarified.

                    plan: Current plan of action as a list of steps (if a structured approach
                          has emerged). Update as the plan evolves.

                    progress: Steps from the plan that have been completed. Add items as work
                             is finished to track advancement through the plan.

                Returns:
                    Confirmation message.
                """
                try:
                    context_data: Dict[str, Any] = {
                        "session_id": session_id,
                        "summary": summary,
                    }

                    # Preserve previous values if not updated
                    if goal is not None:
                        context_data["goal"] = goal
                    elif existing_context and hasattr(existing_context, "goal"):
                        context_data["goal"] = existing_context.goal

                    if plan is not None:
                        context_data["plan"] = plan
                    elif existing_context and hasattr(existing_context, "plan"):
                        context_data["plan"] = existing_context.plan or []

                    if progress is not None:
                        context_data["progress"] = progress
                    elif existing_context and hasattr(existing_context, "progress"):
                        context_data["progress"] = existing_context.progress or []

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

        else:
            # Summary-only mode: only summary parameter
            def save_session_context(summary: str) -> str:  # type: ignore[misc]
                """Save the updated session summary.

                The summary should capture the current state of the conversation in a way that
                enables seamless continuation. Think: "What would someone need to know to pick
                up exactly where we left off?"

                Args:
                    summary: A comprehensive summary that integrates previous context with new
                            developments. Should be standalone - readable without seeing the
                            actual messages. Capture:
                            - What's being worked on and why
                            - Key decisions made and their rationale
                            - Current state of any work in progress
                            - Open questions or pending items

                            Good: "Helping user debug a memory leak in their Node.js application.
                            Identified that the issue occurs in the WebSocket handler - connections
                            aren't being cleaned up on disconnect. Reviewed the connection management
                            code and found missing event listener removal. User is implementing the
                            fix with a connection registry pattern. Next step: test under load."

                            Bad: "User had a bug. We looked at code. Found some issues. Working on fixing it."

                Returns:
                    Confirmation message.
                """
                try:
                    context_data = {
                        "session_id": session_id,
                        "summary": summary,
                    }

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
        existing_context: Optional[Any] = None,
    ) -> List[Callable]:
        """Get async extraction tools for the model."""
        enable_planning = self.config.enable_planning

        if enable_planning:
            # Full planning mode: include goal, plan, progress parameters
            async def save_session_context(
                summary: str,
                goal: Optional[str] = None,
                plan: Optional[List[str]] = None,
                progress: Optional[List[str]] = None,
            ) -> str:
                """Save the updated session context.

                The summary should capture the current state of the conversation in a way that
                enables seamless continuation. Think: "What would someone need to know to pick
                up exactly where we left off?"

                Args:
                    summary: A comprehensive summary that integrates previous context with new
                            developments. Should be standalone - readable without seeing the
                            actual messages. Capture:
                            - What's being worked on and why
                            - Key decisions made and their rationale
                            - Current state of any work in progress
                            - Open questions or pending items

                            Good: "Debugging a React performance issue in the user's dashboard.
                            Identified unnecessary re-renders in the DataTable component caused by
                            inline object creation in props. Implemented useMemo for the column
                            definitions. Testing shows 60% render reduction. Next: profile the
                            filtering logic which may have similar issues."

                            Bad: "Looked at React code. Found some performance issues. Made changes."

                    goal: The user's primary objective for this session (if one is apparent).
                          Update if the goal has evolved or been clarified.

                    plan: Current plan of action as a list of steps (if a structured approach
                          has emerged). Update as the plan evolves.

                    progress: Steps from the plan that have been completed. Add items as work
                             is finished to track advancement through the plan.

                Returns:
                    Confirmation message.
                """
                try:
                    context_data: Dict[str, Any] = {
                        "session_id": session_id,
                        "summary": summary,
                    }

                    # Preserve previous values if not updated
                    if goal is not None:
                        context_data["goal"] = goal
                    elif existing_context and hasattr(existing_context, "goal"):
                        context_data["goal"] = existing_context.goal

                    if plan is not None:
                        context_data["plan"] = plan
                    elif existing_context and hasattr(existing_context, "plan"):
                        context_data["plan"] = existing_context.plan or []

                    if progress is not None:
                        context_data["progress"] = progress
                    elif existing_context and hasattr(existing_context, "progress"):
                        context_data["progress"] = existing_context.progress or []

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

        else:
            # Summary-only mode: only summary parameter
            async def save_session_context(summary: str) -> str:  # type: ignore[misc]
                """Save the updated session summary.

                The summary should capture the current state of the conversation in a way that
                enables seamless continuation. Think: "What would someone need to know to pick
                up exactly where we left off?"

                Args:
                    summary: A comprehensive summary that integrates previous context with new
                            developments. Should be standalone - readable without seeing the
                            actual messages. Capture:
                            - What's being worked on and why
                            - Key decisions made and their rationale
                            - Current state of any work in progress
                            - Open questions or pending items

                            Good: "Helping user debug a memory leak in their Node.js application.
                            Identified that the issue occurs in the WebSocket handler - connections
                            aren't being cleaned up on disconnect. Reviewed the connection management
                            code and found missing event listener removal. User is implementing the
                            fix with a connection registry pattern. Next step: test under load."

                            Bad: "User had a bug. We looked at code. Found some issues. Working on fixing it."

                Returns:
                    Confirmation message.
                """
                try:
                    context_data = {
                        "session_id": session_id,
                        "summary": summary,
                    }

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

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation for debugging."""
        has_db = self.db is not None
        has_model = self.model is not None
        return (
            f"SessionContextStore("
            f"mode={self.config.mode.value}, "
            f"db={has_db}, "
            f"model={has_model}, "
            f"enable_planning={self.config.enable_planning})"
        )

    def print(self, session_id: str, *, raw: bool = False) -> None:
        """Print formatted session context.

        Args:
            session_id: The session to print context for.
            raw: If True, print raw dict using pprint instead of formatted panel.

        Example:
            >>> store.print(session_id="sess_123")
            ╭─────────────── Session Context ───────────────╮
            │ Summary: Debugging React performance issue... │
            │ Goal: Fix DataTable re-renders                │
            │ Plan:                                         │
            │   1. Profile component renders                │
            │   2. Identify unnecessary re-renders          │
            │ Progress:                                     │
            │   ✓ Profile component renders                 │
            ╰──────────────── sess_123 ─────────────────────╯
        """
        from agno.learn.utils import print_panel

        context = self.get(session_id=session_id)

        lines = []

        if context:
            if hasattr(context, "summary") and context.summary:
                lines.append(f"Summary: {context.summary}")

            if hasattr(context, "goal") and context.goal:
                if lines:
                    lines.append("")
                lines.append(f"Goal: {context.goal}")

            if hasattr(context, "plan") and context.plan:
                if lines:
                    lines.append("")
                lines.append("Plan:")
                for i, step in enumerate(context.plan, 1):
                    lines.append(f"  {i}. {step}")

            if hasattr(context, "progress") and context.progress:
                if lines:
                    lines.append("")
                lines.append("Progress:")
                for step in context.progress:
                    lines.append(f"  [green]✓[/green] {step}")

        print_panel(
            title="Session Context",
            subtitle=session_id,
            lines=lines,
            empty_message="No session context",
            raw_data=context,
            raw=raw,
        )
