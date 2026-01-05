"""
User Profile Store
==================
Storage backend for User Profile learning type.

Stores long-term memories about users that persist across sessions.

Key Features:
- Two types of data: Profile Fields (structured) and Memories (unstructured)
- Background extraction from conversations
- Agent tools for in-conversation updates
- Multi-user isolation (each user has their own profile)

## Profile Fields vs Memories

Profile Fields (structured):
- name, preferred_name, and custom fields from extended schemas
- Updated via `update_profile` tool
- For concrete facts that fit defined schema fields

Memories (unstructured):
- List of observations that don't fit schema fields
- Updated via `add_memory`, `update_memory`, `delete_memory` tools
- For preferences, patterns, and context

Scope:
- Profiles are retrieved by user_id only
- agent_id/team_id stored in DB columns for audit trail
- agent_id/team_id stored on individual memories for granular audit

Supported Modes:
- BACKGROUND: Automatic extraction after conversations
- AGENTIC: Agent calls update_user_memory tool directly
"""

import inspect
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from dataclasses import fields as dc_fields
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union, get_args, get_origin

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

    Profiles are retrieved by user_id only - all agents sharing the same DB
    will see the same profile for a given user. agent_id and team_id are
    stored for audit purposes (both at DB column level and on individual memories).

    ## Two Types of Profile Data

    1. **Profile Fields** (structured): name, preferred_name, and any custom
       fields added when extending the schema. Updated via `update_profile` tool.

    2. **Memories** (unstructured): Observations that don't fit schema fields.
       Updated via `add_memory`, `update_memory`, `delete_memory` tools.

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

        if self.config.mode == LearningMode.PROPOSE:
            log_warning("UserProfileStore does not support PROPOSE mode.")
        elif self.config.mode == LearningMode.HITL:
            log_warning("UserProfileStore does not support HITL mode.")

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

    def recall(self, user_id: str, **kwargs) -> Optional[Any]:
        """Retrieve user profile from storage.

        Args:
            user_id: The user to retrieve profile for (required).
            **kwargs: Additional context (ignored).

        Returns:
            User profile, or None if not found.
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
        """Extract user profile from messages.

        Args:
            messages: Conversation messages to analyze.
            user_id: The user to update profile for (required).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            **kwargs: Additional context (ignored).
        """
        # process only supported in BACKGROUND mode
        # for programmatic extraction, use extract_and_save directly
        if self.config.mode != LearningMode.BACKGROUND:
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
        if self.config.mode != LearningMode.BACKGROUND:
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

        Formats user profile data for injection into the agent's system prompt.
        Designed to enable natural, personalized responses without meta-commentary
        about memory systems.

        Args:
            data: User profile data from recall().

        Returns:
            Context string to inject into the agent's system prompt.
        """
        # Build tool documentation based on what's enabled
        tool_docs = self._build_tool_documentation()

        if not data:
            if self._should_expose_tools:
                return dedent(f"""\
                    <user_memory>
                    No information saved about this user yet.

                    {tool_docs}
                    </user_memory>""")
            return ""

        # Build profile fields section
        profile_parts = []
        updateable_fields = self._get_updateable_fields()
        for field_name in updateable_fields:
            value = getattr(data, field_name, None)
            if value:
                profile_parts.append(f"{field_name.replace('_', ' ').title()}: {value}")

        # Build memories section
        memories_text = None
        if hasattr(data, "get_memories_text"):
            memories_text = data.get_memories_text()
        elif hasattr(data, "memories") and data.memories:
            memories_text = "\n".join(f"- {m.get('content', str(m))}" for m in data.memories)

        if not profile_parts and not memories_text:
            if self._should_expose_tools:
                return dedent(f"""\
                    <user_memory>
                    No information saved about this user yet.

                    {tool_docs}
                    </user_memory>""")
            return ""

        context = "<user_memory>\n"

        if profile_parts:
            context += "\n".join(profile_parts) + "\n"

        if memories_text:
            if profile_parts:
                context += "\n"
            context += memories_text

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
            context += dedent(f"""

            <memory_updates>
            {tool_docs}
            </memory_updates>""")

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

        if self.config.agent_can_update_profile:
            # Get the actual field names to document
            updateable_fields = self._get_updateable_fields()
            if updateable_fields:
                field_names = ", ".join(updateable_fields.keys())
                docs.append(
                    f"Use `update_profile` to set structured profile fields ({field_names}) "
                    "when the user explicitly shares this information."
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
        """Check if profile was updated in last operation."""
        return self.profile_updated

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
    # Schema Field Introspection
    # =========================================================================

    def _get_updateable_fields(self) -> Dict[str, Dict[str, Any]]:
        """Get schema fields that can be updated via update_profile tool.

        Returns:
            Dict mapping field name to field info including description.
            Excludes internal fields (user_id, memories, timestamps, etc).
        """
        # Use schema method if available
        if hasattr(self.schema, "get_updateable_fields"):
            return self.schema.get_updateable_fields()

        # Fallback: introspect dataclass fields
        skip = {"user_id", "memories", "created_at", "updated_at", "agent_id", "team_id"}

        result = {}
        for f in dc_fields(self.schema):
            if f.name in skip:
                continue
            # Skip fields marked as internal
            if f.metadata.get("internal"):
                continue

            result[f.name] = {
                "type": f.type,
                "description": f.metadata.get("description", f"User's {f.name.replace('_', ' ')}"),
            }

        return result

    def _build_update_profile_tool(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Callable]:
        """Build a typed update_profile tool dynamically from schema.

        Creates a function with explicit parameters for each schema field,
        giving the LLM clear typed parameters to work with.
        """
        updateable = self._get_updateable_fields()

        if not updateable:
            return None

        # Build parameter list for signature
        params = [
            inspect.Parameter(
                name=field_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=Optional[str],  # Simplified to str for LLM compatibility
            )
            for field_name in updateable
        ]

        # Build docstring with field descriptions
        fields_doc = "\n".join(f"            {name}: {info['description']}" for name, info in updateable.items())

        docstring = f"""Update user profile fields.

        Use this to update structured information about the user.
        Only provide fields you want to update.

        Args:
{fields_doc}

        Returns:
            Confirmation of updated fields.

        Examples:
            update_profile(name="Alice")
            update_profile(name="Bob", preferred_name="Bobby")
        """

        # Capture self and IDs in closure
        store = self

        def update_profile(**kwargs) -> str:
            try:
                profile = store.get(user_id=user_id)
                if profile is None:
                    profile = store.schema(user_id=user_id)

                changed = []
                for field_name, value in kwargs.items():
                    if value is not None and field_name in updateable:
                        setattr(profile, field_name, value)
                        changed.append(f"{field_name}={value}")

                if changed:
                    store.save(
                        user_id=user_id,
                        profile=profile,
                        agent_id=agent_id,
                        team_id=team_id,
                    )
                    log_debug(f"Profile fields updated: {', '.join(changed)}")
                    return f"Profile updated: {', '.join(changed)}"

                return "No fields provided to update"

            except Exception as e:
                log_warning(f"Error updating profile: {e}")
                return f"Error: {e}"

        # Set the signature, docstring, and annotations
        update_profile.__signature__ = inspect.Signature(params)
        update_profile.__doc__ = docstring
        update_profile.__name__ = "update_profile"
        update_profile.__annotations__ = {field_name: Optional[str] for field_name in updateable}
        update_profile.__annotations__["return"] = str

        return update_profile

    async def _abuild_update_profile_tool(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Callable]:
        """Async version of _build_update_profile_tool."""
        updateable = self._get_updateable_fields()

        if not updateable:
            return None

        params = [
            inspect.Parameter(
                name=field_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=Optional[str],
            )
            for field_name in updateable
        ]

        fields_doc = "\n".join(f"            {name}: {info['description']}" for name, info in updateable.items())

        docstring = f"""Update user profile fields.

        Use this to update structured information about the user.
        Only provide fields you want to update.

        Args:
{fields_doc}

        Returns:
            Confirmation of updated fields.
        """

        store = self

        async def update_profile(**kwargs) -> str:
            try:
                profile = await store.aget(user_id=user_id)
                if profile is None:
                    profile = store.schema(user_id=user_id)

                changed = []
                for field_name, value in kwargs.items():
                    if value is not None and field_name in updateable:
                        setattr(profile, field_name, value)
                        changed.append(f"{field_name}={value}")

                if changed:
                    await store.asave(
                        user_id=user_id,
                        profile=profile,
                        agent_id=agent_id,
                        team_id=team_id,
                    )
                    log_debug(f"Profile fields updated: {', '.join(changed)}")
                    return f"Profile updated: {', '.join(changed)}"

                return "No fields provided to update"

            except Exception as e:
                log_warning(f"Error updating profile: {e}")
                return f"Error: {e}"

        # Set the signature, docstring, and annotations
        update_profile.__signature__ = inspect.Signature(params)
        update_profile.__doc__ = docstring
        update_profile.__name__ = "update_profile"
        update_profile.__annotations__ = {field_name: Optional[str] for field_name in updateable}
        update_profile.__annotations__["return"] = str

        return update_profile

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
                return self.run_user_profile_update(
                    task=task,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )

            tools.append(update_user_memory)

        # Profile field update tool
        if self.config.agent_can_update_profile:
            update_profile = self._build_update_profile_tool(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )
            if update_profile:
                tools.append(update_profile)

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
                return await self.arun_user_profile_update(
                    task=task,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )

            tools.append(update_user_memory)

        if self.config.agent_can_update_profile:
            update_profile = await self._abuild_update_profile_tool(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )
            if update_profile:
                tools.append(update_profile)

        return tools

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get(self, user_id: str) -> Optional[Any]:
        """Retrieve user profile by user_id.

        Args:
            user_id: The unique user identifier.

        Returns:
            User profile as schema instance, or None if not found.
        """
        if not self.db:
            return None

        try:
            result = self.db.get_learning(
                learning_type=self.learning_type,
                user_id=user_id,
            )

            if result and result.get("content"):  # type: ignore
                return from_dict_safe(self.schema, result["content"])

            return None

        except Exception as e:
            log_debug(f"UserProfileStore.get failed for user_id={user_id}: {e}")
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
            log_debug(f"UserProfileStore.aget failed for user_id={user_id}: {e}")
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
            agent_id: Agent context (stored in DB column for audit).
            team_id: Team context (stored in DB column for audit).
        """
        if not self.db or not profile:
            return

        try:
            content = to_dict_safe(profile)
            if not content:
                return

            self.db.upsert_learning(
                id=self._build_profile_id(user_id=user_id),
                learning_type=self.learning_type,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                content=content,
            )
            log_debug(f"UserProfileStore.save: saved profile for user_id={user_id}")

        except Exception as e:
            log_debug(f"UserProfileStore.save failed for user_id={user_id}: {e}")

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

            if isinstance(self.db, AsyncBaseDb):
                await self.db.upsert_learning(
                    id=self._build_profile_id(user_id=user_id),
                    learning_type=self.learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=self._build_profile_id(user_id=user_id),
                    learning_type=self.learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            log_debug(f"UserProfileStore.asave: saved profile for user_id={user_id}")

        except Exception as e:
            log_debug(f"UserProfileStore.asave failed for user_id={user_id}: {e}")

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete(self, user_id: str) -> bool:
        """Delete a user profile.

        Args:
            user_id: The unique user identifier.

        Returns:
            True if deleted, False otherwise.
        """
        if not self.db:
            return False

        try:
            profile_id = self._build_profile_id(user_id=user_id)
            return self.db.delete_learning(id=profile_id)
        except Exception as e:
            log_debug(f"UserProfileStore.delete failed for user_id={user_id}: {e}")
            return False

    async def adelete(self, user_id: str) -> bool:
        """Async version of delete."""
        if not self.db:
            return False

        try:
            profile_id = self._build_profile_id(user_id=user_id)
            if isinstance(self.db, AsyncBaseDb):
                return await self.db.delete_learning(id=profile_id)
            else:
                return self.db.delete_learning(id=profile_id)
        except Exception as e:
            log_debug(f"UserProfileStore.adelete failed for user_id={user_id}: {e}")
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
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
        """
        if not self.db:
            return

        try:
            empty_profile = self.schema(user_id=user_id)
            self.save(user_id=user_id, profile=empty_profile, agent_id=agent_id, team_id=team_id)
            log_debug(f"UserProfileStore.clear: cleared profile for user_id={user_id}")
        except Exception as e:
            log_debug(f"UserProfileStore.clear failed for user_id={user_id}: {e}")

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
            log_debug(f"UserProfileStore.aclear: cleared profile for user_id={user_id}")
        except Exception as e:
            log_debug(f"UserProfileStore.aclear failed for user_id={user_id}: {e}")

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
            agent_id: Agent that added this (stored for audit).
            team_id: Team context (stored for audit).
            **kwargs: Additional fields for the memory.

        Returns:
            The memory ID if added, None otherwise.
        """
        profile = self.get(user_id=user_id)

        if profile is None:
            profile = self.schema(user_id=user_id)

        memory_id = None
        if hasattr(profile, "add_memory"):
            memory_id = profile.add_memory(memory, **kwargs)
        elif hasattr(profile, "memories"):
            memory_id = str(uuid.uuid4())[:8]
            memory_entry = {"id": memory_id, "content": memory, **kwargs}
            if agent_id:
                memory_entry["added_by_agent"] = agent_id
            if team_id:
                memory_entry["added_by_team"] = team_id
            profile.memories.append(memory_entry)

        self.save(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
        log_debug(f"UserProfileStore.add_memory: added memory for user_id={user_id}")

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
        profile = await self.aget(user_id=user_id)

        if profile is None:
            profile = self.schema(user_id=user_id)

        memory_id = None
        if hasattr(profile, "add_memory"):
            memory_id = profile.add_memory(memory, **kwargs)
        elif hasattr(profile, "memories"):
            memory_id = str(uuid.uuid4())[:8]
            memory_entry = {"id": memory_id, "content": memory, **kwargs}
            if agent_id:
                memory_entry["added_by_agent"] = agent_id
            if team_id:
                memory_entry["added_by_team"] = team_id
            profile.memories.append(memory_entry)

        await self.asave(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
        log_debug(f"UserProfileStore.aadd_memory: added memory for user_id={user_id}")

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

        Args:
            messages: Conversation messages to analyze.
            user_id: The unique user identifier.
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).

        Returns:
            Response from model.
        """
        if self.model is None:
            log_warning("UserProfileStore.extract_and_save: no model provided")
            return "No model provided for user profile extraction"

        if not self.db:
            log_warning("UserProfileStore.extract_and_save: no database provided")
            return "No DB provided for user profile store"

        log_debug("UserProfileStore: Extracting user profile", center=True)

        self.profile_updated = False

        existing_profile = self.get(user_id=user_id)
        existing_data = self._profile_to_memory_list(profile=existing_profile)

        input_string = self._messages_to_input_string(messages=messages)

        tools = self._get_extraction_tools(
            user_id=user_id,
            input_string=input_string,
            existing_profile=existing_profile,
            agent_id=agent_id,
            team_id=team_id,
        )

        functions = self._build_functions_for_model(tools=tools)

        messages_for_model = [
            self._get_system_message(existing_data=existing_data, existing_profile=existing_profile),
            *messages,
        ]

        model_copy = deepcopy(self.model)
        response = model_copy.response(
            messages=messages_for_model,
            tools=functions,
        )

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
            log_warning("UserProfileStore.aextract_and_save: no model provided")
            return "No model provided for user profile extraction"

        if not self.db:
            log_warning("UserProfileStore.aextract_and_save: no database provided")
            return "No DB provided for user profile store"

        log_debug("UserProfileStore: Extracting user profile (async)", center=True)

        self.profile_updated = False

        existing_profile = await self.aget(user_id=user_id)
        existing_data = self._profile_to_memory_list(profile=existing_profile)

        input_string = self._messages_to_input_string(messages=messages)

        tools = await self._aget_extraction_tools(
            user_id=user_id,
            input_string=input_string,
            existing_profile=existing_profile,
            agent_id=agent_id,
            team_id=team_id,
        )

        functions = self._build_functions_for_model(tools=tools)

        messages_for_model = [
            self._get_system_message(existing_data=existing_data, existing_profile=existing_profile),
            *messages,
        ]

        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=functions,
        )

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

    def _build_profile_id(self, user_id: str) -> str:
        """Build a unique profile ID."""
        return f"user_profile_{user_id}"

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

    def _get_system_message(
        self,
        existing_data: List[dict],
        existing_profile: Optional[Any] = None,
    ) -> "Message":
        """Build system message for memory extraction.

        Guides the model to extract and organize user information in a way that
        enables natural, personalized future interactions - not as a database,
        but as working knowledge that informs how to engage with this person.
        """
        from agno.models.message import Message

        if self.config.system_message is not None:
            return Message(role="system", content=self.config.system_message)

        profile_fields = self._get_updateable_fields()

        system_prompt = dedent("""\
            You are building a memory of this user to enable personalized, contextual interactions.

            Your goal is NOT to create a database of facts, but to build working knowledge that helps
            an AI assistant engage naturally with this person - knowing their context, adapting to their
            preferences, and providing continuity across conversations.

            ## Memory Philosophy

            Think of memories as what a thoughtful colleague would remember after working with someone:
            - Their role and what they're working on
            - How they prefer to communicate
            - What matters to them and what frustrates them
            - Ongoing projects or situations worth tracking

            Memories should make future interactions feel informed and personal, not robotic or surveillance-like.

        """)

        # Profile Fields section
        if profile_fields and self.config.enable_update_profile:
            system_prompt += dedent("""\
                ## Profile Fields

                Use `update_profile` for stable identity information:
            """)

            for field_name, field_info in profile_fields.items():
                description = field_info.get("description", f"User's {field_name.replace('_', ' ')}")
                system_prompt += f"- **{field_name}**: {description}\n"

            if existing_profile:
                has_values = False
                for field_name in profile_fields:
                    if getattr(existing_profile, field_name, None):
                        has_values = True
                        break

                if has_values:
                    system_prompt += "\nCurrent values:\n"
                    for field_name in profile_fields:
                        value = getattr(existing_profile, field_name, None)
                        if value:
                            system_prompt += f"- {field_name}: {value}\n"

            system_prompt += "\n"

        # Memories section with improved categories
        system_prompt += dedent("""\
            ## Memories

            Use memory tools for contextual information organized by relevance:

            **Work/Project Context** - What they're building, their role, current focus
            **Personal Context** - Preferences, communication style, background that shapes interactions
            **Top of Mind** - Active situations, ongoing challenges, time-sensitive context
            **Patterns** - How they work, what they value, recurring themes

        """)

        # Custom instructions or defaults
        profile_capture_instructions = self.config.instructions or dedent("""\
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

        system_prompt += profile_capture_instructions

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

        if self.config.enable_update_profile and profile_fields:
            fields_list = ", ".join(profile_fields.keys())
            system_prompt += f"- `update_profile`: Set profile fields ({fields_list})\n"
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
        """)

        if profile_fields and self.config.enable_update_profile and "name" in profile_fields:
            system_prompt += '→ update_profile(name="Sarah")\n'

        system_prompt += dedent("""\
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
        existing_profile: Optional[Any] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get sync extraction tools for the model."""
        functions: List[Callable] = []

        # Profile update tool
        if self.config.enable_update_profile:
            update_profile = self._build_update_profile_tool(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )
            if update_profile:
                functions.append(update_profile)

        # Memory tools
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
                    profile = self.get(user_id=user_id)
                    if profile is None:
                        profile = self.schema(user_id=user_id)

                    if hasattr(profile, "memories"):
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
                        profile.memories.append(memory_entry)

                    self.save(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
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
                    profile = self.get(user_id=user_id)
                    if profile is None:
                        return "No profile found"

                    if hasattr(profile, "memories"):
                        for mem in profile.memories:
                            if isinstance(mem, dict) and mem.get("id") == memory_id:
                                mem["content"] = memory
                                mem["source"] = input_string[:200] if input_string else None
                                if agent_id:
                                    mem["updated_by_agent"] = agent_id
                                if team_id:
                                    mem["updated_by_team"] = team_id
                                self.save(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
                                log_debug(f"Memory updated: {memory_id}")
                                return f"Memory updated: {memory}"
                        return f"Memory {memory_id} not found"

                    return "Profile has no memories field"
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
                    profile = self.get(user_id=user_id)
                    if profile is None:
                        return "No profile found"

                    if hasattr(profile, "memories"):
                        original_len = len(profile.memories)
                        profile.memories = [
                            mem
                            for mem in profile.memories
                            if not (isinstance(mem, dict) and mem.get("id") == memory_id)
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
        existing_profile: Optional[Any] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get async extraction tools for the model."""
        functions: List[Callable] = []

        # Profile update tool
        if self.config.enable_update_profile:
            update_profile = await self._abuild_update_profile_tool(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )
            if update_profile:
                functions.append(update_profile)

        # Memory tools
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
                    profile = await self.aget(user_id=user_id)
                    if profile is None:
                        profile = self.schema(user_id=user_id)

                    if hasattr(profile, "memories"):
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
                        profile.memories.append(memory_entry)

                    await self.asave(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
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
                    profile = await self.aget(user_id=user_id)
                    if profile is None:
                        return "No profile found"

                    if hasattr(profile, "memories"):
                        for mem in profile.memories:
                            if isinstance(mem, dict) and mem.get("id") == memory_id:
                                mem["content"] = memory
                                mem["source"] = input_string[:200] if input_string else None
                                if agent_id:
                                    mem["updated_by_agent"] = agent_id
                                if team_id:
                                    mem["updated_by_team"] = team_id
                                await self.asave(user_id=user_id, profile=profile, agent_id=agent_id, team_id=team_id)
                                log_debug(f"Memory updated: {memory_id}")
                                return f"Memory updated: {memory}"
                        return f"Memory {memory_id} not found"

                    return "Profile has no memories field"
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
                    profile = await self.aget(user_id=user_id)
                    if profile is None:
                        return "No profile found"

                    if hasattr(profile, "memories"):
                        original_len = len(profile.memories)
                        profile.memories = [
                            mem
                            for mem in profile.memories
                            if not (isinstance(mem, dict) and mem.get("id") == memory_id)
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
            f"UserProfileStore("
            f"mode={self.config.mode.value}, "
            f"db={has_db}, "
            f"model={has_model}, "
            f"enable_agent_tools={self.config.enable_agent_tools})"
        )
