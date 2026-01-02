"""
User Profile Store
==================
Storage backend for User Profile learning type.

Stores long-term memories about users that persist across sessions.

Key Features:
- Manual memory addition via add_memory()
- Background extraction from conversations
- Agent tool for in-conversation updates
- Multi-user isolation (each user has their own profile)
- Agent/team context for different perspectives on same user

Supported Modes:
- BACKGROUND: Automatic extraction with duplicate detection
- AGENTIC: Agent calls update_user_memory directly when it discovers insights
"""

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from os import getenv
from textwrap import dedent
from typing import Any, Callable, List, Optional, Union

from agno.learn.config import LearningMode, UserProfileConfig
from agno.learn.schemas import UserProfile
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
class UserProfileStore(LearningStore):
    """Storage backend for User Profile learning type.

    Handles retrieval, storage, and extraction of user profiles.
    Profiles are stored per user_id and persist across sessions.

    Usage:
        >>> store = UserProfileStore(config=UserProfileConfig(db=db, model=model))
        >>>
        >>> # Manual memory addition
        >>> store.add_memory("alice", "User is a software engineer")
        >>>
        >>> # Get profile
        >>> profile = store.get("alice")
        >>> print(profile.get_memories_text())
        >>>
        >>> # Background extraction
        >>> store.extract_and_save(messages, user_id="alice")
        >>>
        >>> # Agent tools
        >>> tools = store.get_agent_tools(user_id="alice")
        >>> tools[0]("Remember that user prefers dark mode")

    Args:
        config: UserProfileConfig with all settings including db and model.
        debug_mode: Enable debug logging.
    """

    config: UserProfileConfig = field(default_factory=UserProfileConfig)
    debug_mode: bool = False

    # State tracking (internal)
    profile_updated: bool = field(default=False, init=False)
    _schema: Any = field(default=None, init=False)

    def __post_init__(self):
        self._schema = self.config.schema or UserProfile

        # Warn if unsupported mode is used
        if self.config.mode == LearningMode.PROPOSE:
            log_warning(
                "UserProfileStore does not support PROPOSE mode. "
                "User profile captures facts, not insights requiring approval. "
                "Falling back to BACKGROUND mode. Use AGENTIC mode or enable_tool=True for agent updates."
            )
        elif self.config.mode == LearningMode.HITL:
            log_warning(
                "UserProfileStore does not support HITL mode. "
                "User profile captures facts, not insights requiring approval. "
                "Falling back to BACKGROUND mode. Use AGENTIC mode or enable_tool=True for agent updates."
            )

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """Unique identifier for this learning type."""
        return "user_profile"

    @property
    def schema(self) -> Any:
        """Schema class used for profiles."""
        return self._schema

    def recall(
        self, user_id: str, agent_id: Optional[str] = None, team_id: Optional[str] = None, **kwargs
    ) -> Optional[Any]:
        """Retrieve user profile from storage.

        Args:
            user_id: The user to retrieve profile for (required).
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context (ignored).

        Returns:
            User profile, or None if not found.
        """
        if not user_id:
            return None
        return self.get(
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

    async def arecall(
        self, user_id: str, agent_id: Optional[str] = None, team_id: Optional[str] = None, **kwargs
    ) -> Optional[Any]:
        """Async version of recall."""
        if not user_id:
            return None
        return await self.aget(user_id=user_id, agent_id=agent_id, team_id=team_id)

    def process(
        self, messages: List[Any], user_id: str, agent_id: Optional[str] = None, team_id: Optional[str] = None, **kwargs
    ) -> None:
        """Extract user profile from messages.

        Args:
            messages: Conversation messages to analyze.
            user_id: The user to update profile for (required).
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context (ignored).
        """
        # Only run process in BACKGROUND mode (or PROPOSE/HITL which falls back to BACKGROUND mode)
        if self.config.mode == LearningMode.AGENTIC:
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
        self, messages: List[Any], user_id: str, agent_id: Optional[str] = None, team_id: Optional[str] = None, **kwargs
    ) -> None:
        """Async version of process."""
        # Only run background extraction in BACKGROUND mode (or PROPOSE/HITL which falls back to BACKGROUND mode)
        if self.config.mode == LearningMode.AGENTIC:
            return

        if not user_id or not messages:
            return
        await self.aextract_and_save(messages=messages, user_id=user_id, agent_id=agent_id, team_id=team_id)

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Args:
            data: User profile data from recall().

        Returns:
            Context string to inject into the agent's system prompt, or empty string if no data.
        """
        if not data:
            # Even with no data, mention tool if enabled
            if self.config.enable_tool:
                return dedent("""\
                    <user_profile>
                    No information saved about this user yet.

                    You can use `update_user_memory` to save information worth remembering about this user.
                    </user_profile>""")
            return ""

        memories_text = None
        if hasattr(data, "get_memories_text"):
            memories_text = data.get_memories_text()
        elif hasattr(data, "memories") and data.memories:
            memories_text = "\n".join(f"- {m.get('content', str(m))}" for m in data.memories)

        if not memories_text:
            if self.config.enable_tool:
                return dedent("""\
                    <user_profile>
                    No information saved about this user yet.

                    You can use `update_user_memory` to save information worth remembering about this user.
                    </user_profile>""")
            return ""

        context = (
            dedent("""\
            <user_profile>
            What you know about this user:
            """)
            + memories_text
        )

        if self.config.enable_tool:
            context += dedent("""

            You can use `update_user_memory` to save new information or update existing memories.
            Use this to personalize responses. Current conversation takes precedence.
            </user_profile>""")
        else:
            context += dedent("""

            Use this to personalize responses. Current conversation takes precedence.
            </user_profile>""")

        return context

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
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context (ignored).

        Returns:
            List containing update_user_memory tool if enabled.
        """
        if not user_id or not self.config.enable_tool:
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
        if not user_id or not self.config.enable_tool:
            return []
        return await self.aget_agent_tools(user_id=user_id, agent_id=agent_id, team_id=team_id)

    @property
    def was_updated(self) -> bool:
        """Check if profile was updated in last operation."""
        return self.profile_updated

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

        Returns a list of callable tools that the agent can use to update user memory.
        """

        def update_user_memory(task: str) -> str:
            """Update information about the user.

            Use this to save, update, or delete information about the user.

            Args:
                task: What to remember, update, or forget about the user.
                      Examples:
                      - "Remember that user's name is John"
                      - "User now prefers dark mode"
                      - "Forget user's old address"

            Returns:
                Confirmation message.
            """
            return self.run_user_profile_update(
                task=task,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )

        return [update_user_memory]

    async def aget_agent_tools(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get the async tools to expose to the agent."""

        async def update_user_memory(task: str) -> str:
            """Update information about the user.

            Use this to save, update, or delete information about the user.

            Args:
                task: What to remember, update, or forget about the user.
                      Examples:
                      - "Remember that user's name is John"
                      - "User now prefers dark mode"
                      - "Forget user's old address"

            Returns:
                Confirmation message.
            """
            return await self.arun_user_profile_update(
                task=task,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )

        return [update_user_memory]

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Retrieve user profile by user_id.

        Args:
            user_id: The unique user identifier.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            User profile as schema instance, or None if not found.
        """
        if not self.db:
            return None

        try:
            result = self.db.get_learning(
                learning_type=self.learning_type,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )

            if result and result.get("content"):  # type: ignore
                return from_dict_safe(self.schema, result["content"])

            return None

        except Exception as e:
            log_debug(f"Error retrieving user profile: {e}")
            return None

    async def aget(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Async version of get."""
        if not self.db:
            return None

        try:
            if hasattr(self.db, "aget_learning"):
                result = await self.db.aget_learning(
                    learning_type=self.learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            else:
                result = self.db.get_learning(
                    learning_type=self.learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )

            if result and result.get("content"):
                return from_dict_safe(self.schema, result["content"])

            return None

        except Exception as e:
            log_debug(f"Error retrieving user profile: {e}")
            return None

    # =========================================================================
    # Write Operations
    # =========================================================================

    def save(
        self,
        user_id: str,
        profile: Any,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Save or update user profile.

        Args:
            user_id: The unique user identifier.
            profile: The profile data to save.
            agent_id: Optional agent context.
            team_id: Optional team context.
        """
        if not self.db or not profile:
            return

        try:
            content = to_dict_safe(profile)
            if not content:
                return

            self.db.upsert_learning(
                id=self._build_profile_id(user_id=user_id, agent_id=agent_id, team_id=team_id),
                learning_type=self.learning_type,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                content=content,
            )
            log_debug(f"Saved user profile for user_id: {user_id}")

        except Exception as e:
            log_debug(f"Error saving user profile: {e}")

    async def asave(
        self,
        user_id: str,
        profile: Any,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Async version of save."""
        if not self.db or not profile:
            return

        try:
            content = to_dict_safe(profile)
            if not content:
                return

            if hasattr(self.db, "aupsert_learning"):
                await self.db.aupsert_learning(
                    id=self._build_profile_id(user_id=user_id, agent_id=agent_id, team_id=team_id),
                    learning_type=self.learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=self._build_profile_id(user_id=user_id, agent_id=agent_id, team_id=team_id),
                    learning_type=self.learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            log_debug(f"Saved user profile for user_id: {user_id}")

        except Exception as e:
            log_debug(f"Error saving user profile: {e}")

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> bool:
        """Delete a user profile.

        Args:
            user_id: The unique user identifier.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            True if deleted, False otherwise.
        """
        if not self.db:
            return False

        try:
            profile_id = self._build_profile_id(user_id=user_id, agent_id=agent_id, team_id=team_id)
            return self.db.delete_learning(id=profile_id)
        except Exception as e:
            log_debug(f"Error deleting user profile: {e}")
            return False

    async def adelete(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> bool:
        """Async version of delete."""
        if not self.db:
            return False

        try:
            profile_id = self._build_profile_id(user_id=user_id, agent_id=agent_id, team_id=team_id)
            if hasattr(self.db, "adelete_learning"):
                return await self.db.adelete_learning(id=profile_id)
            else:
                return self.db.delete_learning(id=profile_id)
        except Exception as e:
            log_debug(f"Error deleting user profile: {e}")
            return False

    def clear(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Clear user profile (reset to empty).

        Args:
            user_id: The unique user identifier.
            agent_id: Optional agent context.
            team_id: Optional team context.
        """
        if not self.db:
            return

        try:
            empty_profile = self.schema(user_id=user_id)
            self.save(user_id=user_id, profile=empty_profile, agent_id=agent_id, team_id=team_id)
            log_debug(f"Cleared user profile for user_id: {user_id}")
        except Exception as e:
            log_debug(f"Error clearing user profile: {e}")

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
            empty_profile = self.schema(user_id=user_id)
            await self.asave(user_id=user_id, profile=empty_profile, agent_id=agent_id, team_id=team_id)
            log_debug(f"Cleared user profile for user_id: {user_id}")
        except Exception as e:
            log_debug(f"Error clearing user profile: {e}")

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
        """Add a single memory to the user's profile.

        Args:
            user_id: The unique user identifier.
            memory: The memory text to add.
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional fields for the memory.

        Returns:
            The memory ID if added, None otherwise.
        """
        profile = self.get(user_id=user_id, agent_id=agent_id, team_id=team_id)

        if profile is None:
            profile = self.schema(user_id=user_id)

        memory_id = None
        if hasattr(profile, "add_memory"):
            memory_id = profile.add_memory(memory, **kwargs)
        elif hasattr(profile, "memories"):
            memory_id = str(uuid.uuid4())[:8]
            profile.memories.append({"id": memory_id, "content": memory, **kwargs})

        self.save(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
        log_debug(f"Added memory for user {user_id}: {memory[:50]}...")

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
        profile = await self.aget(user_id=user_id, agent_id=agent_id, team_id=team_id)

        if profile is None:
            profile = self.schema(user_id=user_id)

        memory_id = None
        if hasattr(profile, "add_memory"):
            memory_id = profile.add_memory(memory, **kwargs)
        elif hasattr(profile, "memories"):
            memory_id = str(uuid.uuid4())[:8]
            profile.memories.append({"id": memory_id, "content": memory, **kwargs})

        await self.asave(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
        log_debug(f"Added memory for user {user_id}: {memory[:50]}...")

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
        """Extract user profile information from messages and save.

        Uses tool-based extraction where the model calls add/update/delete tools.

        Args:
            messages: Conversation messages to analyze.
            user_id: The unique user identifier.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            Response from model.
        """
        if self.model is None:
            log_warning("No model provided for user profile extraction")
            return "No model provided for user profile extraction"

        if not self.db:
            log_warning("No DB provided for user profile store")
            return "No DB provided for user profile store"

        log_debug("UserProfileStore: Extracting user profile", center=True)

        # Reset state
        self.profile_updated = False

        # Get existing profile
        existing_profile = self.get(user_id=user_id, agent_id=agent_id, team_id=team_id)
        existing_data = self._profile_to_memory_list(profile=existing_profile)

        # Build input string from messages
        input_string = self._messages_to_input_string(messages=messages)

        # Get tools
        tools = self._get_extraction_tools(
            user_id=user_id,
            input_string=input_string,
            agent_id=agent_id,
            team_id=team_id,
        )

        # Convert to Function objects for model
        functions = self._build_functions_for_model(tools=tools)

        # Prepare messages for model
        messages_for_model = [
            self._get_system_message(existing_data=existing_data),
            *messages,
        ]

        # Generate response (model will call tools)
        model_copy = deepcopy(self.model)
        response = model_copy.response(
            messages=messages_for_model,
            tools=functions,
        )

        # Set profile updated flag if tools were executed
        if response.tool_executions:
            self.profile_updated = True

        log_debug("UserProfileStore: Extraction complete", center=True)

        return response.content or ("Profile updated" if self.profile_updated else "No updates needed")

    async def aextract_and_save(
        self,
        messages: List["Message"],
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Async version of extract_and_save."""
        if self.model is None:
            log_warning("No model provided for user profile extraction")
            return "No model provided for user profile extraction"

        if not self.db:
            log_warning("No DB provided for user profile store")
            return "No DB provided for user profile store"

        log_debug("UserProfileStore: Extracting user profile (async)", center=True)

        # Reset state
        self.profile_updated = False

        # Get existing profile
        existing_profile = await self.aget(user_id=user_id, agent_id=agent_id, team_id=team_id)
        existing_data = self._profile_to_memory_list(profile=existing_profile)

        # Build input string from messages
        input_string = self._messages_to_input_string(messages=messages)

        # Get tools
        tools = await self._aget_extraction_tools(
            user_id=user_id,
            input_string=input_string,
            agent_id=agent_id,
            team_id=team_id,
        )

        # Convert to Function objects for model
        functions = self._build_functions_for_model(tools=tools)

        # Prepare messages for model
        messages_for_model = [
            self._get_system_message(existing_data=existing_data),
            *messages,
        ]

        # Generate response (model will call tools)
        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=functions,
        )

        # Set profile updated flag if tools were executed
        if response.tool_executions:
            self.profile_updated = True

        log_debug("UserProfileStore: Extraction complete", center=True)

        return response.content or ("Profile updated" if self.profile_updated else "No updates needed")

    # =========================================================================
    # Update Operations (called by agent tool)
    # =========================================================================

    def run_user_profile_update(
        self,
        task: str,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Run a user profile update task.

        Called by the agent tool to update user profile.

        Args:
            task: The update task description.
            user_id: The unique user identifier.
            agent_id: Optional agent context.
            team_id: Optional team context.

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

    async def arun_user_profile_update(
        self,
        task: str,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Async version of run_user_profile_update."""
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

    def _build_profile_id(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Build a unique profile ID."""
        parts = [f"user_profile_{user_id}"]
        if agent_id:
            parts.append(f"agent_{agent_id}")
        if team_id:
            parts.append(f"team_{team_id}")
        return "_".join(parts)

    def _profile_to_memory_list(self, profile: Optional[Any]) -> List[dict]:
        """Convert profile to list of memory dicts for prompt."""
        if not profile:
            return []

        memories = []

        if hasattr(profile, "memories") and profile.memories:
            for mem in profile.memories:
                if isinstance(mem, dict):
                    memory_id = mem.get("id", str(uuid.uuid4())[:8])
                    content = mem.get("content", str(mem))
                else:
                    memory_id = str(uuid.uuid4())[:8]
                    content = str(mem)
                memories.append({"id": memory_id, "content": content})

        return memories

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

    def _get_system_message(self, existing_data: List[dict]) -> "Message":
        """Build system message for extraction."""
        from agno.models.message import Message

        # Full override from config
        if self.config.system_message is not None:
            return Message(role="system", content=self.config.system_message)

        # Use config instructions or default
        profile_capture_instructions = self.config.instructions or dedent("""\
            Capture information that reveals who this person truly is:

            **Identity & Background**
            - Name and how they prefer to be addressed
            - Professional role, expertise, and experience level
            - Key life context (location, situation, background)

            **How They Think & Work**
            - Problem-solving approach and working style
            - Communication preferences (direct, detailed, casual, formal)
            - Values and principles that guide their decisions
            - Areas of deep knowledge or expertise

            **What Matters To Them**
            - Current goals, projects, and priorities
            - Recurring challenges or frustrations
            - Strong opinions and preferences
            - What motivates or energizes them

            **Patterns & Preferences**
            - Consistent behaviors or habits mentioned multiple times
            - Tools, technologies, or methods they prefer
            - How they like to receive information or feedback

            Do NOT capture:
            - One-time events unless they reveal a pattern
            - Trivial details unlikely to matter in future conversations
            - Inferences or assumptions not directly stated\
        """)

        system_prompt = (
            dedent("""\
            You are a User Profile Manager. Your job is to maintain accurate, useful memories about the user.

            ## Your Task
            Review the conversation and decide if any information should be saved to the user's profile.
            Only save information that will be genuinely useful in future conversations.

            ## What To Capture
        """)
            + profile_capture_instructions
            + dedent("""

            ## How To Write Entries
            - Write in third person: "User is..." or "User prefers..."
            - Be specific and factual, not vague
            - One clear fact per entry
            - Preserve nuance - don't overgeneralize

            Good: "User is a software engineer at Google working on search infrastructure"
            Bad: "User works in tech"

            Good: "User mentioned going to the gym today"
            Bad: "User goes to the gym regularly" (don't infer patterns from single mentions)

            ## Existing Profile\
        """)
        )

        if existing_data:
            system_prompt += "\nThe user already has these memories saved:\n"
            for entry in existing_data:
                system_prompt += f"- [{entry['id']}] {entry['content']}\n"
            system_prompt += "\nYou can update or delete these if the conversation indicates changes.\n"
        else:
            system_prompt += "\nNo existing memories for this user.\n"

        system_prompt += "\n## Available Actions\n"

        if self.config.enable_add:
            system_prompt += "- `add_memory`: Add a new memory about the user\n"
        if self.config.enable_update:
            system_prompt += "- `update_memory`: Update an existing memory by its ID\n"
        if self.config.enable_delete:
            system_prompt += "- `delete_memory`: Delete a memory that is no longer accurate\n"
        if self.config.enable_clear:
            system_prompt += "- `clear_all_memories`: Remove all memories (use sparingly)\n"

        system_prompt += dedent("""
            ## Important
            - Only take action if there's genuinely useful information to save
            - It's fine to do nothing if the conversation has no profile-relevant content
            - Quality over quantity - fewer accurate memories beats many vague ones\
        """)

        if self.config.additional_instructions:
            system_prompt += f"\n\n{self.config.additional_instructions}"

        return Message(role="system", content=system_prompt)

    def _get_extraction_tools(
        self,
        user_id: str,
        input_string: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get sync extraction tools for the model."""

        def add_memory(memory: str) -> str:
            """Add a new memory about the user.

            Args:
                memory: The memory to save. Write in third person, e.g. "User is a software engineer"

            Returns:
                Confirmation message.
            """
            try:
                profile = self.get(user_id=user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    profile = self.schema(user_id=user_id)

                if hasattr(profile, "memories"):
                    memory_id = str(uuid.uuid4())[:8]
                    profile.memories.append(
                        {
                            "id": memory_id,
                            "content": memory,
                            "source": input_string[:200] if input_string else None,
                        }
                    )

                self.save(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
                log_debug(f"Memory added: {memory[:50]}...")
                return f"Memory saved: {memory}"
            except Exception as e:
                log_warning(f"Error adding memory: {e}")
                return f"Error: {e}"

        def update_memory(memory_id: str, memory: str) -> str:
            """Update an existing memory.

            Args:
                memory_id: The ID of the memory to update.
                memory: The new memory content.

            Returns:
                Confirmation message.
            """
            try:
                profile = self.get(user_id=user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                if hasattr(profile, "memories"):
                    for mem in profile.memories:
                        if isinstance(mem, dict) and mem.get("id") == memory_id:
                            mem["content"] = memory
                            mem["source"] = input_string[:200] if input_string else None
                            self.save(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
                            log_debug(f"Memory updated: {memory_id}")
                            return f"Memory updated: {memory}"
                    return f"Memory {memory_id} not found"

                return "Profile has no memories field"
            except Exception as e:
                log_warning(f"Error updating memory: {e}")
                return f"Error: {e}"

        def delete_memory(memory_id: str) -> str:
            """Delete a memory that is no longer accurate.

            Args:
                memory_id: The ID of the memory to delete.

            Returns:
                Confirmation message.
            """
            try:
                profile = self.get(user_id=user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                if hasattr(profile, "memories"):
                    original_len = len(profile.memories)
                    profile.memories = [
                        mem for mem in profile.memories if not (isinstance(mem, dict) and mem.get("id") == memory_id)
                    ]
                    if len(profile.memories) < original_len:
                        self.save(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
                        log_debug(f"Memory deleted: {memory_id}")
                        return f"Memory {memory_id} deleted"
                    return f"Memory {memory_id} not found"

                return "Profile has no memories field"
            except Exception as e:
                log_warning(f"Error deleting memory: {e}")
                return f"Error: {e}"

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

        functions: List[Callable] = []
        if self.config.enable_add:
            functions.append(add_memory)
        if self.config.enable_update:
            functions.append(update_memory)
        if self.config.enable_delete:
            functions.append(delete_memory)
        if self.config.enable_clear:
            functions.append(clear_all_memories)

        return functions

    async def _aget_extraction_tools(
        self,
        user_id: str,
        input_string: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get async extraction tools for the model."""

        async def add_memory(memory: str) -> str:
            """Add a new memory about the user.

            Args:
                memory: The memory to save. Write in third person, e.g. "User is a software engineer"

            Returns:
                Confirmation message.
            """
            try:
                profile = await self.aget(user_id=user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    profile = self.schema(user_id=user_id)

                if hasattr(profile, "memories"):
                    memory_id = str(uuid.uuid4())[:8]
                    profile.memories.append(
                        {
                            "id": memory_id,
                            "content": memory,
                            "source": input_string[:200] if input_string else None,
                        }
                    )

                await self.asave(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
                log_debug(f"Memory added: {memory[:50]}...")
                return f"Memory saved: {memory}"
            except Exception as e:
                log_warning(f"Error adding memory: {e}")
                return f"Error: {e}"

        async def update_memory(memory_id: str, memory: str) -> str:
            """Update an existing memory.

            Args:
                memory_id: The ID of the memory to update.
                memory: The new memory content.

            Returns:
                Confirmation message.
            """
            try:
                profile = await self.aget(user_id=user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                if hasattr(profile, "memories"):
                    for mem in profile.memories:
                        if isinstance(mem, dict) and mem.get("id") == memory_id:
                            mem["content"] = memory
                            mem["source"] = input_string[:200] if input_string else None
                            await self.asave(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
                            log_debug(f"Memory updated: {memory_id}")
                            return f"Memory updated: {memory}"
                    return f"Memory {memory_id} not found"

                return "Profile has no memories field"
            except Exception as e:
                log_warning(f"Error updating memory: {e}")
                return f"Error: {e}"

        async def delete_memory(memory_id: str) -> str:
            """Delete a memory that is no longer accurate.

            Args:
                memory_id: The ID of the memory to delete.

            Returns:
                Confirmation message.
            """
            try:
                profile = await self.aget(user_id=user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                if hasattr(profile, "memories"):
                    original_len = len(profile.memories)
                    profile.memories = [
                        mem for mem in profile.memories if not (isinstance(mem, dict) and mem.get("id") == memory_id)
                    ]
                    if len(profile.memories) < original_len:
                        await self.asave(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
                        log_debug(f"Memory deleted: {memory_id}")
                        return f"Memory {memory_id} deleted"
                    return f"Memory {memory_id} not found"

                return "Profile has no memories field"
            except Exception as e:
                log_warning(f"Error deleting memory: {e}")
                return f"Error: {e}"

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

        functions: List[Callable] = []
        if self.config.enable_add:
            functions.append(add_memory)
        if self.config.enable_update:
            functions.append(update_memory)
        if self.config.enable_delete:
            functions.append(delete_memory)
        if self.config.enable_clear:
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
            f"UserProfileStore("
            f"mode={self.config.mode.value}, "
            f"db={has_db}, "
            f"model={has_model}, "
            f"enable_tool={self.config.enable_tool})"
        )
