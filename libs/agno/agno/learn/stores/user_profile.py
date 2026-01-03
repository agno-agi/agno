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

    Profiles are retrieved by user_id only — all agents sharing the same DB
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

        Args:
            data: User profile data from recall().

        Returns:
            Context string to inject into the agent's system prompt.
        """
        if not data:
            if self.config.enable_agent_tools:
                return dedent("""\
                    <user_profile>
                    No information saved about this user yet.

                    You can use `update_user_memory` to save information worth remembering about this user.
                    </user_profile>""")
            return ""

        # Build profile fields section
        profile_parts = []
        updateable_fields = self._get_updateable_fields()
        for field_name in updateable_fields:
            value = getattr(data, field_name, None)
            if value:
                profile_parts.append(f"- {field_name.replace('_', ' ').title()}: {value}")

        # Build memories section
        memories_text = None
        if hasattr(data, "get_memories_text"):
            memories_text = data.get_memories_text()
        elif hasattr(data, "memories") and data.memories:
            memories_text = "\n".join(f"- {m.get('content', str(m))}" for m in data.memories)

        if not profile_parts and not memories_text:
            if self.config.enable_agent_tools:
                return dedent("""\
                    <user_profile>
                    No information saved about this user yet.

                    You can use `update_user_memory` to save information worth remembering about this user.
                    </user_profile>""")
            return ""

        context = dedent("""\
            <user_profile>
            What you know about this user:
            """)

        if profile_parts:
            context += "\n".join(profile_parts) + "\n"

        if memories_text:
            if profile_parts:
                context += "\nObservations:\n"
            context += memories_text

        if self.config.enable_agent_tools:
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
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            **kwargs: Additional context (ignored).

        Returns:
            List containing update_user_memory tool if enabled.
        """
        if not user_id or not self.config.enable_agent_tools:
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
        if not user_id or not self.config.enable_agent_tools:
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

        # Set the signature and docstring
        update_profile.__signature__ = inspect.Signature(params)
        update_profile.__doc__ = docstring
        update_profile.__name__ = "update_profile"

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

        update_profile.__signature__ = inspect.Signature(params)
        update_profile.__doc__ = docstring
        update_profile.__name__ = "update_profile"

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
        """Build system message for extraction.

        The system message now clearly separates:
        1. Profile Fields (structured) - updated via update_profile
        2. Memories (unstructured) - updated via add_memory, update_memory, delete_memory
        """
        from agno.models.message import Message

        if self.config.system_message is not None:
            return Message(role="system", content=self.config.system_message)

        # Get updateable fields from schema
        profile_fields = self._get_updateable_fields()

        system_prompt = dedent("""\
            You are a User Profile Manager. Your job is to extract and organize
            information about the user from conversations.

            ## Two Types of Information

        """)

        # Profile Fields section
        if profile_fields and self.config.enable_update_profile:
            system_prompt += dedent("""\
                ### 1. Profile Fields (Structured)
                Use `update_profile` for concrete facts that fit these fields:
            """)

            for field_name, field_info in profile_fields.items():
                description = field_info.get("description", f"User's {field_name.replace('_', ' ')}")
                system_prompt += f"    - **{field_name}**: {description}\n"

            # Show current values if profile exists
            if existing_profile:
                system_prompt += "\n    Current values:\n"
                for field_name in profile_fields:
                    value = getattr(existing_profile, field_name, None)
                    if value:
                        system_prompt += f"    - {field_name}: {value}\n"
                    else:
                        system_prompt += f"    - {field_name}: (not set)\n"

            system_prompt += "\n"

        # Memories section
        system_prompt += dedent("""\
            ### 2. Memories (Unstructured)
            Use memory tools for observations that don't fit the fields above:
            - Preferences and opinions
            - Behavioral patterns
            - Context that might be useful later
            - Anything that doesn't have a dedicated field

        """)

        # Custom instructions
        profile_capture_instructions = self.config.instructions or dedent("""\
            **What to capture in memories:**
            - How they think and work (problem-solving style, communication preferences)
            - What matters to them (goals, priorities, frustrations)
            - Patterns and preferences (tools, methods, feedback style)

            **Do NOT capture:**
            - Information that fits a profile field (use update_profile instead)
            - One-time events unless they reveal a pattern
            - Trivial details unlikely to matter later
            - Inferences or assumptions not directly stated\
        """)

        system_prompt += profile_capture_instructions

        system_prompt += dedent("""

            ## How To Write Memory Entries
            - Write in third person: "User is..." or "User prefers..."
            - Be specific and factual, not vague
            - One clear fact per entry
            - Preserve nuance - don't overgeneralize

            ## Current Memories
        """)

        if existing_data:
            system_prompt += "The user already has these memories saved:\n"
            for entry in existing_data:
                system_prompt += f"- [{entry['id']}] {entry['content']}\n"
            system_prompt += "\nYou can update or delete these if the conversation indicates changes.\n"
        else:
            system_prompt += "No existing memories for this user.\n"

        system_prompt += "\n## Available Actions\n"

        if self.config.enable_update_profile and profile_fields:
            fields_list = ", ".join(profile_fields.keys())
            system_prompt += f"- `update_profile`: Update profile fields ({fields_list})\n"
        if self.config.enable_add_memory:
            system_prompt += "- `add_memory`: Add a new memory about the user\n"
        if self.config.enable_update_memory:
            system_prompt += "- `update_memory`: Update an existing memory by its ID\n"
        if self.config.enable_delete_memory:
            system_prompt += "- `delete_memory`: Delete a memory that is no longer accurate\n"
        if self.config.enable_clear_memories:
            system_prompt += "- `clear_all_memories`: Remove all memories (use sparingly)\n"

        system_prompt += dedent("""

            ## Examples

            User says: "I'm Alice, CTO at Acme, based in London"
        """)

        if profile_fields and self.config.enable_update_profile:
            example_fields = []
            if "name" in profile_fields:
                example_fields.append('name="Alice"')
            if "role" in profile_fields:
                example_fields.append('role="CTO"')
            if "company" in profile_fields:
                example_fields.append('company="Acme"')
            if "location" in profile_fields:
                example_fields.append('location="London"')

            if example_fields:
                system_prompt += f"→ update_profile({', '.join(example_fields)})\n"
            else:
                system_prompt += '→ add_memory("User is Alice, CTO at Acme, based in London")\n'
        else:
            system_prompt += '→ add_memory("User is Alice, CTO at Acme, based in London")\n'

        system_prompt += dedent("""
            User says: "I prefer detailed explanations with code examples"
            → add_memory("User prefers detailed explanations with code examples")

            ## Important
            - Profile fields are for FACTS, memories are for OBSERVATIONS
            - Don't duplicate: if it fits a field, don't also add as memory
            - Update existing values when new info contradicts old
            - Quality over quantity - fewer accurate entries beats many vague ones
            - It's fine to do nothing if there's no profile-relevant content\
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
                """Add a new memory about the user.

                Args:
                    memory: The memory to save. Write in third person, e.g. "User prefers dark mode"

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
                """Update an existing memory.

                Args:
                    memory_id: The ID of the memory to update.
                    memory: The new memory content.

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
                """Delete a memory that is no longer accurate.

                Args:
                    memory_id: The ID of the memory to delete.

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
                """Add a new memory about the user.

                Args:
                    memory: The memory to save. Write in third person, e.g. "User prefers dark mode"

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
                """Update an existing memory.

                Args:
                    memory_id: The ID of the memory to update.
                    memory: The new memory content.

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
                """Delete a memory that is no longer accurate.

                Args:
                    memory_id: The ID of the memory to delete.

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
