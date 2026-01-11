"""
User Memory Store
=================
Storage backend for User Memory learning type.

Stores unstructured observations about users that don't fit into
structured profile fields. These are long-term memories that persist
across sessions.

Key Features:
- Background extraction from conversations
- Agent tools for in-conversation updates
- Multi-user isolation (each user has their own memories)
- Add, update, delete memory operations

Scope:
- Memories are retrieved by user_id only
- agent_id/team_id stored in DB columns for audit trail
- agent_id/team_id stored on individual memories for granular audit

Supported Modes:
- ALWAYS: Automatic extraction after conversations
- AGENTIC: Agent calls update_user_memory tool directly
"""

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from os import getenv
from textwrap import dedent
from typing import Any, Callable, List, Optional, Union

from agno.learn.config import LearningMode, UserMemoryConfig
from agno.learn.schemas import Memories
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
class UserMemoryStore(LearningStore):
    """Storage backend for User Memory learning type.

    Memories are retrieved by user_id only - all agents sharing the same DB
    will see the same memories for a given user. agent_id and team_id are
    stored for audit purposes (both at DB column level and on individual memories).

    Args:
        config: UserMemoryConfig with all settings including db and model.
        debug_mode: Enable debug logging.
    """

    config: UserMemoryConfig = field(default_factory=UserMemoryConfig)
    debug_mode: bool = False

    # State tracking (internal)
    memories_updated: bool = field(default=False, init=False)
    _schema: Any = field(default=None, init=False)

    def __post_init__(self):
        self._schema = self.config.schema or Memories

        if self.config.mode == LearningMode.PROPOSE:
            log_warning("UserMemoryStore does not support PROPOSE mode.")
        elif self.config.mode == LearningMode.HITL:
            log_warning("UserMemoryStore does not support HITL mode.")

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """Unique identifier for this learning type."""
        return "user_memory"

    @property
    def schema(self) -> Any:
        """Schema class used for memories."""
        return self._schema

    def recall(self, user_id: str, **kwargs) -> Optional[Any]:
        """Retrieve memories from storage.

        Args:
            user_id: The user to retrieve memories for (required).
            **kwargs: Additional context (ignored).

        Returns:
            Memories, or None if not found.
        """
        if not user_id:
            return None
        return self.get(user_id=user_id)

    async def arecall(self, user_id: str, **kwargs) -> Optional[Any]:
        """Async version of recall."""
        if not user_id:
            return None
        return await self.aget(user_id=user_id)

    def process(
        self,
        messages: List[Any],
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract memories from messages.

        Args:
            messages: Conversation messages to analyze.
            user_id: The user to update memories for (required).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            **kwargs: Additional context (ignored).
        """
        # process only supported in ALWAYS mode
        # for programmatic extraction, use extract_and_save directly
        if self.config.mode != LearningMode.ALWAYS:
            return

        if not user_id or not messages:
            return

        self.extract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    async def aprocess(
        self,
        messages: List[Any],
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Async version of process."""
        if self.config.mode != LearningMode.ALWAYS:
            return

        if not user_id or not messages:
            return

        await self.aextract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Formats memories data for injection into the agent's system prompt.
        Designed to enable natural, personalized responses without meta-commentary
        about memory systems.

        Args:
            data: Memories data from recall().

        Returns:
            Context string to inject into the agent's system prompt.
        """
        # Build tool documentation based on what's enabled
        tool_docs = self._build_tool_documentation()

        if not data:
            if self._should_expose_tools:
                return (
                    dedent("""\
                    <user_memory>
                    No memories saved about this user yet.

                    """)
                    + tool_docs
                    + dedent("""
                    </user_memory>""")
                )
            return ""

        # Build memories section
        memories_text = None
        if hasattr(data, "get_memories_text"):
            memories_text = data.get_memories_text()
        elif hasattr(data, "memories") and data.memories:
            memories_text = "\n".join(f"- {m.get('content', str(m))}" for m in data.memories)

        if not memories_text:
            if self._should_expose_tools:
                return (
                    dedent("""\
                    <user_memory>
                    No memories saved about this user yet.

                    """)
                    + tool_docs
                    + dedent("""
                    </user_memory>""")
                )
            return ""

        context = "<user_memory>\n"
        context += memories_text + "\n"

        context += dedent("""
            <memory_application_guidelines>
            Apply this knowledge naturally - respond as if you inherently know this information,
            exactly as a colleague would recall shared history without narrating their thought process.

            - Selectively apply memories based on relevance to the current query
            - Never say "based on my memory" or "I remember that" - just use the information naturally
            - Current conversation always takes precedence over stored memories
            - Use memories to calibrate tone, depth, and examples without announcing it
            </memory_application_guidelines>""")

        if self._should_expose_tools:
            context += (
                dedent("""

            <memory_updates>

            """)
                + tool_docs
                + dedent("""
            </memory_updates>""")
            )

        context += "\n</user_memory>"

        return context

    def _build_tool_documentation(self) -> str:
        """Build documentation for available memory tools.

        Returns:
            String documenting which tools are available and when to use them.
        """
        docs = []

        if self.config.agent_can_update_memories:
            docs.append(
                "Use `update_user_memory` to save observations, preferences, and context about this user "
                "that would help personalize future conversations or avoid asking the same questions."
            )

        return "\n\n".join(docs) if docs else ""

    def get_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get tools to expose to agent.

        Args:
            user_id: The user context (required for tool to work).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            **kwargs: Additional context (ignored).

        Returns:
            List containing update_user_memory tool if enabled.
        """
        if not user_id or not self._should_expose_tools:
            return []
        return self.get_agent_tools(
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    async def aget_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Async version of get_tools."""
        if not user_id or not self._should_expose_tools:
            return []
        return await self.aget_agent_tools(
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    @property
    def was_updated(self) -> bool:
        """Check if memories were updated in last operation."""
        return self.memories_updated

    @property
    def _should_expose_tools(self) -> bool:
        """Check if tools should be exposed to the agent.

        Returns True if either:
        - mode is AGENTIC (tools are the primary way to update memory), OR
        - enable_agent_tools is explicitly True
        """
        return self.config.mode == LearningMode.AGENTIC or self.config.enable_agent_tools

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
    # Agent Tools
    # =========================================================================

    def get_agent_tools(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get the tools to expose to the agent.

        Args:
            user_id: The user to update (required).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).

        Returns:
            List of callable tools based on config settings.
        """
        tools = []

        # Memory update tool (delegates to extraction)
        if self.config.agent_can_update_memories:

            def update_user_memory(task: str) -> str:
                """Save or update information about this user for future conversations.

                Use this when you learn something worth remembering - information that would
                help personalize future interactions or provide continuity across sessions.

                Args:
                    task: What to save, update, or remove. Be specific and factual.
                          Good examples:
                          - "User is a senior engineer at Stripe working on payments"
                          - "Prefers concise responses without lengthy explanations"
                          - "Update: User moved from NYC to London"
                          - "Remove the memory about their old job at Acme"
                          Bad examples:
                          - "User seems nice" (too vague)
                          - "Had a meeting today" (not durable)

                Returns:
                    Confirmation of what was saved/updated.
                """
                return self.run_memories_update(
                    task=task,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )

            tools.append(update_user_memory)

        return tools

    async def aget_agent_tools(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get the async tools to expose to the agent."""
        tools = []

        if self.config.agent_can_update_memories:

            async def update_user_memory(task: str) -> str:
                """Save or update information about this user for future conversations.

                Use this when you learn something worth remembering - information that would
                help personalize future interactions or provide continuity across sessions.

                Args:
                    task: What to save, update, or remove. Be specific and factual.
                          Good examples:
                          - "User is a senior engineer at Stripe working on payments"
                          - "Prefers concise responses without lengthy explanations"
                          - "Update: User moved from NYC to London"
                          - "Remove the memory about their old job at Acme"
                          Bad examples:
                          - "User seems nice" (too vague)
                          - "Had a meeting today" (not durable)

                Returns:
                    Confirmation of what was saved/updated.
                """
                return await self.arun_memories_update(
                    task=task,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )

            tools.append(update_user_memory)

        return tools

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get(self, user_id: str) -> Optional[Any]:
        """Retrieve memories by user_id.

        Args:
            user_id: The unique user identifier.

        Returns:
            Memories as schema instance, or None if not found.
        """
        if not self.db:
            return None

        try:
            result = self.db.get_learning(
                learning_type=self.learning_type,
                user_id=user_id,
            )

            if result and result.get("content"):  # type: ignore[union-attr]
                return from_dict_safe(self.schema, result["content"])  # type: ignore[index]

            return None

        except Exception as e:
            log_debug(f"UserMemoryStore.get failed for user_id={user_id}: {e}")
            return None

    async def aget(self, user_id: str) -> Optional[Any]:
        """Async version of get."""
        if not self.db:
            return None

        try:
            if isinstance(self.db, AsyncBaseDb):
                result = await self.db.get_learning(
                    learning_type=self.learning_type,
                    user_id=user_id,
                )
            else:
                result = self.db.get_learning(
                    learning_type=self.learning_type,
                    user_id=user_id,
                )

            if result and result.get("content"):
                return from_dict_safe(self.schema, result["content"])

            return None

        except Exception as e:
            log_debug(f"UserMemoryStore.aget failed for user_id={user_id}: {e}")
            return None

    # =========================================================================
    # Write Operations
    # =========================================================================

    def save(
        self,
        user_id: str,
        memories: Any,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Save or update memories.

        Args:
            user_id: The unique user identifier.
            memories: The memories data to save.
            agent_id: Agent context (stored in DB column for audit).
            team_id: Team context (stored in DB column for audit).
        """
        if not self.db or not memories:
            return

        try:
            content = to_dict_safe(memories)
            if not content:
                return

            self.db.upsert_learning(
                id=self._build_memories_id(user_id=user_id),
                learning_type=self.learning_type,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                content=content,
            )
            log_debug(f"UserMemoryStore.save: saved memories for user_id={user_id}")

        except Exception as e:
            log_debug(f"UserMemoryStore.save failed for user_id={user_id}: {e}")

    async def asave(
        self,
        user_id: str,
        memories: Any,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Async version of save."""
        if not self.db or not memories:
            return

        try:
            content = to_dict_safe(memories)
            if not content:
                return

            if isinstance(self.db, AsyncBaseDb):
                await self.db.upsert_learning(
                    id=self._build_memories_id(user_id=user_id),
                    learning_type=self.learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=self._build_memories_id(user_id=user_id),
                    learning_type=self.learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            log_debug(f"UserMemoryStore.asave: saved memories for user_id={user_id}")

        except Exception as e:
            log_debug(f"UserMemoryStore.asave failed for user_id={user_id}: {e}")

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete(self, user_id: str) -> bool:
        """Delete memories for a user.

        Args:
            user_id: The unique user identifier.

        Returns:
            True if deleted, False otherwise.
        """
        if not self.db:
            return False

        try:
            memories_id = self._build_memories_id(user_id=user_id)
            return self.db.delete_learning(id=memories_id)  # type: ignore[return-value]
        except Exception as e:
            log_debug(f"UserMemoryStore.delete failed for user_id={user_id}: {e}")
            return False

    async def adelete(self, user_id: str) -> bool:
        """Async version of delete."""
        if not self.db:
            return False

        try:
            memories_id = self._build_memories_id(user_id=user_id)
            if isinstance(self.db, AsyncBaseDb):
                return await self.db.delete_learning(id=memories_id)
            else:
                return self.db.delete_learning(id=memories_id)
        except Exception as e:
            log_debug(f"UserMemoryStore.adelete failed for user_id={user_id}: {e}")
            return False

    def clear(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Clear all memories for a user (reset to empty).

        Args:
            user_id: The unique user identifier.
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
        """
        if not self.db:
            return

        try:
            empty_memories = self.schema(user_id=user_id)
            self.save(user_id=user_id, memories=empty_memories, agent_id=agent_id, team_id=team_id)
            log_debug(f"UserMemoryStore.clear: cleared memories for user_id={user_id}")
        except Exception as e:
            log_debug(f"UserMemoryStore.clear failed for user_id={user_id}: {e}")

    async def aclear(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Async version of clear."""
        if not self.db:
            return

        try:
            empty_memories = self.schema(user_id=user_id)
            await self.asave(user_id=user_id, memories=empty_memories, agent_id=agent_id, team_id=team_id)
            log_debug(f"UserMemoryStore.aclear: cleared memories for user_id={user_id}")
        except Exception as e:
            log_debug(f"UserMemoryStore.aclear failed for user_id={user_id}: {e}")

    # =========================================================================
    # Memory Operations
    # =========================================================================

    def add_memory(
        self,
        user_id: str,
        memory: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Add a single memory.

        Args:
            user_id: The unique user identifier.
            memory: The memory text to add.
            agent_id: Agent that added this (stored for audit).
            team_id: Team context (stored for audit).
            **kwargs: Additional fields for the memory.

        Returns:
            The memory ID if added, None otherwise.
        """
        memories_data = self.get(user_id=user_id)

        if memories_data is None:
            memories_data = self.schema(user_id=user_id)

        memory_id = None
        if hasattr(memories_data, "add_memory"):
            memory_id = memories_data.add_memory(memory, **kwargs)
        elif hasattr(memories_data, "memories"):
            memory_id = str(uuid.uuid4())[:8]
            memory_entry = {"id": memory_id, "content": memory, **kwargs}
            if agent_id:
                memory_entry["added_by_agent"] = agent_id
            if team_id:
                memory_entry["added_by_team"] = team_id
            memories_data.memories.append(memory_entry)

        self.save(user_id=user_id, memories=memories_data, agent_id=agent_id, team_id=team_id)
        log_debug(f"UserMemoryStore.add_memory: added memory for user_id={user_id}")

        return memory_id

    async def aadd_memory(
        self,
        user_id: str,
        memory: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Async version of add_memory."""
        memories_data = await self.aget(user_id=user_id)

        if memories_data is None:
            memories_data = self.schema(user_id=user_id)

        memory_id = None
        if hasattr(memories_data, "add_memory"):
            memory_id = memories_data.add_memory(memory, **kwargs)
        elif hasattr(memories_data, "memories"):
            memory_id = str(uuid.uuid4())[:8]
            memory_entry = {"id": memory_id, "content": memory, **kwargs}
            if agent_id:
                memory_entry["added_by_agent"] = agent_id
            if team_id:
                memory_entry["added_by_team"] = team_id
            memories_data.memories.append(memory_entry)

        await self.asave(user_id=user_id, memories=memories_data, agent_id=agent_id, team_id=team_id)
        log_debug(f"UserMemoryStore.aadd_memory: added memory for user_id={user_id}")

        return memory_id

    # =========================================================================
    # Extraction Operations
    # =========================================================================

    def extract_and_save(
        self,
        messages: List["Message"],
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Extract memories from messages and save.

        Args:
            messages: Conversation messages to analyze.
            user_id: The unique user identifier.
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).

        Returns:
            Response from model.
        """
        if self.model is None:
            log_warning("UserMemoryStore.extract_and_save: no model provided")
            return "No model provided for memories extraction"

        if not self.db:
            log_warning("UserMemoryStore.extract_and_save: no database provided")
            return "No DB provided for memories store"

        log_debug("UserMemoryStore: Extracting memories", center=True)

        self.memories_updated = False

        existing_memories = self.get(user_id=user_id)
        existing_data = self._memories_to_list(memories=existing_memories)

        input_string = self._messages_to_input_string(messages=messages)

        tools = self._get_extraction_tools(
            user_id=user_id,
            input_string=input_string,
            existing_memories=existing_memories,
            agent_id=agent_id,
            team_id=team_id,
        )

        functions = self._build_functions_for_model(tools=tools)

        messages_for_model = [
            self._get_system_message(existing_data=existing_data),
            *messages,
        ]

        model_copy = deepcopy(self.model)
        response = model_copy.response(
            messages=messages_for_model,
            tools=functions,
        )

        if response.tool_executions:
            self.memories_updated = True

        log_debug("UserMemoryStore: Extraction complete", center=True)

        return response.content or ("Memories updated" if self.memories_updated else "No updates needed")

    async def aextract_and_save(
        self,
        messages: List["Message"],
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Async version of extract_and_save."""
        if self.model is None:
            log_warning("UserMemoryStore.aextract_and_save: no model provided")
            return "No model provided for memories extraction"

        if not self.db:
            log_warning("UserMemoryStore.aextract_and_save: no database provided")
            return "No DB provided for memories store"

        log_debug("UserMemoryStore: Extracting memories (async)", center=True)

        self.memories_updated = False

        existing_memories = await self.aget(user_id=user_id)
        existing_data = self._memories_to_list(memories=existing_memories)

        input_string = self._messages_to_input_string(messages=messages)

        tools = await self._aget_extraction_tools(
            user_id=user_id,
            input_string=input_string,
            existing_memories=existing_memories,
            agent_id=agent_id,
            team_id=team_id,
        )

        functions = self._build_functions_for_model(tools=tools)

        messages_for_model = [
            self._get_system_message(existing_data=existing_data),
            *messages,
        ]

        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=functions,
        )

        if response.tool_executions:
            self.memories_updated = True

        log_debug("UserMemoryStore: Extraction complete", center=True)

        return response.content or ("Memories updated" if self.memories_updated else "No updates needed")

    # =========================================================================
    # Update Operations (called by agent tool)
    # =========================================================================

    def run_memories_update(
        self,
        task: str,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Run a memories update task.

        Args:
            task: The update task description.
            user_id: The unique user identifier.
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).

        Returns:
            Response from model.
        """
        from agno.models.message import Message

        messages = [Message(role="user", content=task)]
        return self.extract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    async def arun_memories_update(
        self,
        task: str,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Async version of run_memories_update."""
        from agno.models.message import Message

        messages = [Message(role="user", content=task)]
        return await self.aextract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _build_memories_id(self, user_id: str) -> str:
        """Build a unique memories ID."""
        return f"memories_{user_id}"

    def _memories_to_list(self, memories: Optional[Any]) -> List[dict]:
        """Convert memories to list of memory dicts for prompt."""
        if not memories:
            return []

        result = []

        if hasattr(memories, "memories") and memories.memories:
            for mem in memories.memories:
                if isinstance(mem, dict):
                    memory_id = mem.get("id", str(uuid.uuid4())[:8])
                    content = mem.get("content", str(mem))
                else:
                    memory_id = str(uuid.uuid4())[:8]
                    content = str(mem)
                result.append({"id": memory_id, "content": content})

        return result

    def _messages_to_input_string(self, messages: List["Message"]) -> str:
        """Convert messages to input string."""
        if len(messages) == 1:
            return messages[0].get_content_string()
        else:
            return "\n".join([f"{m.role}: {m.get_content_string()}" for m in messages if m.content])

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

    def _get_system_message(
        self,
        existing_data: List[dict],
    ) -> "Message":
        """Build system message for memory extraction."""
        from agno.models.message import Message

        if self.config.system_message is not None:
            return Message(role="system", content=self.config.system_message)

        system_prompt = dedent("""\
            You are building a memory of this user to enable personalized, contextual interactions.

            Your goal is NOT to create a database of facts, but to build working knowledge that helps an AI assistant engage naturally with this person - knowing their context, adapting to their preferences, and providing continuity across conversations.

            ## Memory Philosophy

            Think of memories as what a thoughtful colleague would remember after working with someone:
            - Their role and what they're working on
            - How they prefer to communicate
            - What matters to them and what frustrates them
            - Ongoing projects or situations worth tracking

            Memories should make future interactions feel informed and personal, not robotic or surveillance-like.

            ## Memory Categories

            Use memory tools for contextual information organized by relevance:

            **Work/Project Context** - What they're building, their role, current focus
            **Personal Context** - Preferences, communication style, background that shapes interactions
            **Top of Mind** - Active situations, ongoing challenges, time-sensitive context
            **Patterns** - How they work, what they value, recurring themes

        """)

        # Custom instructions or defaults
        capture_instructions = self.config.instructions or dedent("""\
            ## What To Capture

            **DO save:**
            - Role, company, and what they're working on
            - Communication preferences (brevity vs detail, technical depth, tone)
            - Goals, priorities, and current challenges
            - Preferences that affect how to help them (tools, frameworks, approaches)
            - Context that would be awkward to ask about again
            - Patterns in how they think and work

            **DO NOT save:**
            - Sensitive personal information (health conditions, financial details, relationships) unless directly relevant to helping them
            - One-off details unlikely to matter in future conversations
            - Information they'd find creepy to have remembered
            - Inferences or assumptions - only save what they've actually stated
            - Duplicates of existing memories (update instead)
            - Trivial preferences that don't affect interactions\
        """)

        system_prompt += capture_instructions

        system_prompt += dedent("""

            ## Writing Style

            Write memories as concise, factual statements in third person:

            **Good memories:**
            - "Founder and CEO of Acme, a 10-person AI startup"
            - "Prefers direct feedback without excessive caveats"
            - "Currently preparing for Series A fundraise, targeting $50M"
            - "Values simplicity over cleverness in code architecture"

            **Bad memories:**
            - "User mentioned they work at a company" (too vague)
            - "User seems to like technology" (obvious/not useful)
            - "Had a meeting yesterday" (not durable)
            - "User is stressed about fundraising" (inference without direct statement)

            ## Consolidation Over Accumulation

            **Critical:** Prefer updating existing memories over adding new ones.

            - If new information extends an existing memory, UPDATE it
            - If new information contradicts an existing memory, REPLACE it
            - If information is truly new and distinct, then add it
            - Periodically consolidate related memories into cohesive summaries
            - Delete memories that are no longer accurate or relevant

            Think of memory maintenance like note-taking: a few well-organized notes beat many scattered fragments.

        """)

        # Current memories section
        system_prompt += "## Current Memories\n\n"

        if existing_data:
            system_prompt += "Existing memories for this user:\n"
            for entry in existing_data:
                system_prompt += f"- [{entry['id']}] {entry['content']}\n"
            system_prompt += dedent("""
                Review these before adding new ones:
                - UPDATE if new information extends or modifies an existing memory
                - DELETE if a memory is no longer accurate
                - Only ADD if the information is genuinely new and distinct
            """)
        else:
            system_prompt += "No existing memories. Extract what's worth remembering from this conversation.\n"

        # Available actions
        system_prompt += "\n## Available Actions\n\n"

        if self.config.enable_add_memory:
            system_prompt += "- `add_memory`: Add a new memory (only if genuinely new information)\n"
        if self.config.enable_update_memory:
            system_prompt += "- `update_memory`: Update existing memory with new/corrected information\n"
        if self.config.enable_delete_memory:
            system_prompt += "- `delete_memory`: Remove outdated or incorrect memory\n"
        if self.config.enable_clear_memories:
            system_prompt += "- `clear_all_memories`: Reset all memories (use rarely)\n"

        # Examples
        system_prompt += dedent("""
            ## Examples

            **Example 1: New user introduction**
            User: "I'm Sarah, I run engineering at Stripe. We're migrating to Kubernetes."
            → add_memory("Engineering lead at Stripe, currently migrating infrastructure to Kubernetes")

            **Example 2: Updating existing context**
            Existing memory: "Working on Series A fundraise"
            User: "We closed our Series A last week! $12M from Sequoia."
            → update_memory(id, "Closed $12M Series A from Sequoia")

            **Example 3: Learning preferences**
            User: "Can you skip the explanations and just give me the code?"
            → add_memory("Prefers concise responses with code over lengthy explanations")

            **Example 4: Nothing worth saving**
            User: "What's the weather like?"
            → No action needed (trivial, no lasting relevance)

            ## Final Guidance

            - Quality over quantity: 5 great memories beat 20 mediocre ones
            - Durability matters: save information that will still be relevant next month
            - Respect boundaries: when in doubt about whether to save something, don't
            - It's fine to do nothing if the conversation reveals nothing worth remembering\
        """)

        if self.config.additional_instructions:
            system_prompt += f"\n\n{self.config.additional_instructions}"

        return Message(role="system", content=system_prompt)

    def _get_extraction_tools(
        self,
        user_id: str,
        input_string: str,
        existing_memories: Optional[Any] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get sync extraction tools for the model."""
        functions: List[Callable] = []

        if self.config.enable_add_memory:

            def add_memory(memory: str) -> str:
                """Save a new memory about this user.

                Only add genuinely new information that will help personalize future interactions.
                Before adding, check if this extends an existing memory (use update_memory instead).

                Args:
                    memory: Concise, factual statement in third person.
                           Good: "Senior engineer at Stripe, working on payment infrastructure"
                           Bad: "User works at a company" (too vague)

                Returns:
                    Confirmation message.
                """
                try:
                    memories_data = self.get(user_id=user_id)
                    if memories_data is None:
                        memories_data = self.schema(user_id=user_id)

                    if hasattr(memories_data, "memories"):
                        memory_id = str(uuid.uuid4())[:8]
                        memory_entry = {
                            "id": memory_id,
                            "content": memory,
                            "source": input_string[:200] if input_string else None,
                        }
                        if agent_id:
                            memory_entry["added_by_agent"] = agent_id
                        if team_id:
                            memory_entry["added_by_team"] = team_id
                        memories_data.memories.append(memory_entry)

                    self.save(user_id=user_id, memories=memories_data, agent_id=agent_id, team_id=team_id)
                    log_debug(f"Memory added: {memory[:50]}...")
                    return f"Memory saved: {memory}"
                except Exception as e:
                    log_warning(f"Error adding memory: {e}")
                    return f"Error: {e}"

            functions.append(add_memory)

        if self.config.enable_update_memory:

            def update_memory(memory_id: str, memory: str) -> str:
                """Update an existing memory with new or corrected information.

                Prefer updating over adding when new information extends or modifies
                something already stored. This keeps memories consolidated and accurate.

                Args:
                    memory_id: The ID of the memory to update (shown in brackets like [abc123]).
                    memory: The updated memory content. Should be a complete replacement,
                           not a diff or addition.

                Returns:
                    Confirmation message.
                """
                try:
                    memories_data = self.get(user_id=user_id)
                    if memories_data is None:
                        return "No memories found"

                    if hasattr(memories_data, "memories"):
                        for mem in memories_data.memories:
                            if isinstance(mem, dict) and mem.get("id") == memory_id:
                                mem["content"] = memory
                                mem["source"] = input_string[:200] if input_string else None
                                if agent_id:
                                    mem["updated_by_agent"] = agent_id
                                if team_id:
                                    mem["updated_by_team"] = team_id
                                self.save(user_id=user_id, memories=memories_data, agent_id=agent_id, team_id=team_id)
                                log_debug(f"Memory updated: {memory_id}")
                                return f"Memory updated: {memory}"
                        return f"Memory {memory_id} not found"

                    return "No memories field"
                except Exception as e:
                    log_warning(f"Error updating memory: {e}")
                    return f"Error: {e}"

            functions.append(update_memory)

        if self.config.enable_delete_memory:

            def delete_memory(memory_id: str) -> str:
                """Remove a memory that is outdated, incorrect, or no longer relevant.

                Delete when:
                - Information is no longer accurate (e.g., they changed jobs)
                - The memory was a misunderstanding
                - It's been superseded by a more complete memory

                Args:
                    memory_id: The ID of the memory to delete (shown in brackets like [abc123]).

                Returns:
                    Confirmation message.
                """
                try:
                    memories_data = self.get(user_id=user_id)
                    if memories_data is None:
                        return "No memories found"

                    if hasattr(memories_data, "memories"):
                        original_len = len(memories_data.memories)
                        memories_data.memories = [
                            mem
                            for mem in memories_data.memories
                            if not (isinstance(mem, dict) and mem.get("id") == memory_id)
                        ]
                        if len(memories_data.memories) < original_len:
                            self.save(user_id=user_id, memories=memories_data, agent_id=agent_id, team_id=team_id)
                            log_debug(f"Memory deleted: {memory_id}")
                            return f"Memory {memory_id} deleted"
                        return f"Memory {memory_id} not found"

                    return "No memories field"
                except Exception as e:
                    log_warning(f"Error deleting memory: {e}")
                    return f"Error: {e}"

            functions.append(delete_memory)

        if self.config.enable_clear_memories:

            def clear_all_memories() -> str:
                """Clear all memories for this user. Use sparingly.

                Returns:
                    Confirmation message.
                """
                try:
                    self.clear(user_id=user_id, agent_id=agent_id, team_id=team_id)
                    log_debug("All memories cleared")
                    return "All memories cleared"
                except Exception as e:
                    log_warning(f"Error clearing memories: {e}")
                    return f"Error: {e}"

            functions.append(clear_all_memories)

        return functions

    async def _aget_extraction_tools(
        self,
        user_id: str,
        input_string: str,
        existing_memories: Optional[Any] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get async extraction tools for the model."""
        functions: List[Callable] = []

        if self.config.enable_add_memory:

            async def add_memory(memory: str) -> str:
                """Save a new memory about this user.

                Only add genuinely new information that will help personalize future interactions.
                Before adding, check if this extends an existing memory (use update_memory instead).

                Args:
                    memory: Concise, factual statement in third person.
                           Good: "Senior engineer at Stripe, working on payment infrastructure"
                           Bad: "User works at a company" (too vague)

                Returns:
                    Confirmation message.
                """
                try:
                    memories_data = await self.aget(user_id=user_id)
                    if memories_data is None:
                        memories_data = self.schema(user_id=user_id)

                    if hasattr(memories_data, "memories"):
                        memory_id = str(uuid.uuid4())[:8]
                        memory_entry = {
                            "id": memory_id,
                            "content": memory,
                            "source": input_string[:200] if input_string else None,
                        }
                        if agent_id:
                            memory_entry["added_by_agent"] = agent_id
                        if team_id:
                            memory_entry["added_by_team"] = team_id
                        memories_data.memories.append(memory_entry)

                    await self.asave(user_id=user_id, memories=memories_data, agent_id=agent_id, team_id=team_id)
                    log_debug(f"Memory added: {memory[:50]}...")
                    return f"Memory saved: {memory}"
                except Exception as e:
                    log_warning(f"Error adding memory: {e}")
                    return f"Error: {e}"

            functions.append(add_memory)

        if self.config.enable_update_memory:

            async def update_memory(memory_id: str, memory: str) -> str:
                """Update an existing memory with new or corrected information.

                Prefer updating over adding when new information extends or modifies
                something already stored. This keeps memories consolidated and accurate.

                Args:
                    memory_id: The ID of the memory to update (shown in brackets like [abc123]).
                    memory: The updated memory content. Should be a complete replacement,
                           not a diff or addition.

                Returns:
                    Confirmation message.
                """
                try:
                    memories_data = await self.aget(user_id=user_id)
                    if memories_data is None:
                        return "No memories found"

                    if hasattr(memories_data, "memories"):
                        for mem in memories_data.memories:
                            if isinstance(mem, dict) and mem.get("id") == memory_id:
                                mem["content"] = memory
                                mem["source"] = input_string[:200] if input_string else None
                                if agent_id:
                                    mem["updated_by_agent"] = agent_id
                                if team_id:
                                    mem["updated_by_team"] = team_id
                                await self.asave(
                                    user_id=user_id, memories=memories_data, agent_id=agent_id, team_id=team_id
                                )
                                log_debug(f"Memory updated: {memory_id}")
                                return f"Memory updated: {memory}"
                        return f"Memory {memory_id} not found"

                    return "No memories field"
                except Exception as e:
                    log_warning(f"Error updating memory: {e}")
                    return f"Error: {e}"

            functions.append(update_memory)

        if self.config.enable_delete_memory:

            async def delete_memory(memory_id: str) -> str:
                """Remove a memory that is outdated, incorrect, or no longer relevant.

                Delete when:
                - Information is no longer accurate (e.g., they changed jobs)
                - The memory was a misunderstanding
                - It's been superseded by a more complete memory

                Args:
                    memory_id: The ID of the memory to delete (shown in brackets like [abc123]).

                Returns:
                    Confirmation message.
                """
                try:
                    memories_data = await self.aget(user_id=user_id)
                    if memories_data is None:
                        return "No memories found"

                    if hasattr(memories_data, "memories"):
                        original_len = len(memories_data.memories)
                        memories_data.memories = [
                            mem
                            for mem in memories_data.memories
                            if not (isinstance(mem, dict) and mem.get("id") == memory_id)
                        ]
                        if len(memories_data.memories) < original_len:
                            await self.asave(
                                user_id=user_id, memories=memories_data, agent_id=agent_id, team_id=team_id
                            )
                            log_debug(f"Memory deleted: {memory_id}")
                            return f"Memory {memory_id} deleted"
                        return f"Memory {memory_id} not found"

                    return "No memories field"
                except Exception as e:
                    log_warning(f"Error deleting memory: {e}")
                    return f"Error: {e}"

            functions.append(delete_memory)

        if self.config.enable_clear_memories:

            async def clear_all_memories() -> str:
                """Clear all memories for this user. Use sparingly.

                Returns:
                    Confirmation message.
                """
                try:
                    await self.aclear(user_id=user_id, agent_id=agent_id, team_id=team_id)
                    log_debug("All memories cleared")
                    return "All memories cleared"
                except Exception as e:
                    log_warning(f"Error clearing memories: {e}")
                    return f"Error: {e}"

            functions.append(clear_all_memories)

        return functions

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation for debugging."""
        has_db = self.db is not None
        has_model = self.model is not None
        return (
            f"UserMemoryStore("
            f"mode={self.config.mode.value}, "
            f"db={has_db}, "
            f"model={has_model}, "
            f"enable_agent_tools={self.config.enable_agent_tools})"
        )

    def print(self, user_id: str, *, raw: bool = False) -> None:
        """Print formatted memories.

        Args:
            user_id: The user to print memories for.
            raw: If True, print raw dict using pprint instead of formatted panel.

        Example:
            >>> store.print(user_id="alice@example.com")
            ╭──────────────── Memories ─────────────────╮
            │ Memories:                                 │
            │   [dim][a1b2c3d4][/dim] Loves Python      │
            │   [dim][e5f6g7h8][/dim] Works at Anthropic│
            ╰─────────────── alice@example.com ─────────╯
        """
        from agno.learn.utils import print_panel

        memories_data = self.get(user_id=user_id)

        lines = []

        if memories_data:
            if hasattr(memories_data, "memories") and memories_data.memories:
                lines.append("Memories:")
                for mem in memories_data.memories:
                    if isinstance(mem, dict):
                        mem_id = mem.get("id", "?")
                        content = mem.get("content", str(mem))
                    else:
                        mem_id = "?"
                        content = str(mem)
                    lines.append(f"  [dim]\\[{mem_id}][/dim] {content}")

        print_panel(
            title="Memories",
            subtitle=user_id,
            lines=lines,
            empty_message="No memories",
            raw_data=memories_data,
            raw=raw,
        )


# Backwards compatibility alias
MemoriesStore = UserMemoryStore
