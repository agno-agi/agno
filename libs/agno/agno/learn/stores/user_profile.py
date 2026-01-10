"""
User Profile Store
==================
Storage backend for User Profile learning type.

Stores long-term structured profile fields about users that persist across sessions.

Key Features:
- Structured profile fields (name, preferred_name, and custom fields)
- Background extraction from conversations
- Agent tools for in-conversation updates
- Multi-user isolation (each user has their own profile)

Profile Fields (structured):
- name, preferred_name, and custom fields from extended schemas
- Updated via `update_profile` tool
- For concrete facts that fit defined schema fields

Note: For unstructured memories, use UserMemoryStore instead.

Scope:
- Profiles are retrieved by user_id only
- agent_id/team_id stored in DB columns for audit trail

Supported Modes:
- ALWAYS: Automatic extraction after conversations
- AGENTIC: Agent calls update_user_profile tool directly
"""

import inspect
from copy import deepcopy
from dataclasses import dataclass, field
from dataclasses import fields as dc_fields
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union, cast

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
    stored for audit purposes in DB columns.

    Profile Fields (structured): name, preferred_name, and any custom
    fields added when extending the schema. Updated via `update_profile` tool.

    Note: For unstructured memories, use UserMemoryStore instead.

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
                return (
                    dedent("""\
                    <user_profile>
                    No profile information saved about this user yet.

                    """)
                    + tool_docs
                    + dedent("""
                    </user_profile>""")
                )
            return ""

        # Build profile fields section
        profile_parts = []
        updateable_fields = self._get_updateable_fields()
        for field_name in updateable_fields:
            value = getattr(data, field_name, None)
            if value:
                profile_parts.append(f"{field_name.replace('_', ' ').title()}: {value}")

        if not profile_parts:
            if self._should_expose_tools:
                return (
                    dedent("""\
                    <user_profile>
                    No profile information saved about this user yet.

                    """)
                    + tool_docs
                    + dedent("""
                    </user_profile>""")
                )
            return ""

        context = "<user_profile>\n"
        context += "\n".join(profile_parts) + "\n"

        context += dedent("""
            <profile_application_guidelines>
            Apply this knowledge naturally - respond as if you inherently know this information,
            exactly as a colleague would recall shared history without narrating their thought process.

            - Use profile information to personalize responses appropriately
            - Never say "based on your profile" or "I see that" - just use the information naturally
            - Current conversation always takes precedence over stored profile data
            </profile_application_guidelines>""")

        if self._should_expose_tools:
            context += (
                dedent("""

            <profile_updates>
            """)
                + tool_docs
                + dedent("""
            </profile_updates>""")
            )

        context += "\n</user_profile>"

        return context

    def _build_tool_documentation(self) -> str:
        """Build documentation for available profile tools.

        Returns:
            String documenting which tools are available and when to use them.
        """
        docs = []

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
            List containing update_profile tool if enabled.
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
        # Use cast to satisfy mypy - all Python functions have these attributes
        func = cast(Any, update_profile)
        func.__signature__ = inspect.Signature(params)
        func.__doc__ = docstring
        func.__name__ = "update_profile"
        func.__annotations__ = {field_name: Optional[str] for field_name in updateable}
        func.__annotations__["return"] = str

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
        # Use cast to satisfy mypy - all Python functions have these attributes
        func = cast(Any, update_profile)
        func.__signature__ = inspect.Signature(params)
        func.__doc__ = docstring
        func.__name__ = "update_profile"
        func.__annotations__ = {field_name: Optional[str] for field_name in updateable}
        func.__annotations__["return"] = str

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

            if result and result.get("content"):  # type: ignore[union-attr]
                return from_dict_safe(self.schema, result["content"])  # type: ignore[index]

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
            return self.db.delete_learning(id=profile_id)  # type: ignore[return-value]
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

        tools = self._get_extraction_tools(
            user_id=user_id,
            existing_profile=existing_profile,
            agent_id=agent_id,
            team_id=team_id,
        )

        functions = self._build_functions_for_model(tools=tools)

        messages_for_model = [
            self._get_system_message(existing_profile=existing_profile),
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

        tools = await self._aget_extraction_tools(
            user_id=user_id,
            existing_profile=existing_profile,
            agent_id=agent_id,
            team_id=team_id,
        )

        functions = self._build_functions_for_model(tools=tools)

        messages_for_model = [
            self._get_system_message(existing_profile=existing_profile),
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
        existing_profile: Optional[Any] = None,
    ) -> "Message":
        """Build system message for profile extraction.

        Guides the model to extract structured profile information from conversations.
        """
        from agno.models.message import Message

        if self.config.system_message is not None:
            return Message(role="system", content=self.config.system_message)

        profile_fields = self._get_updateable_fields()

        system_prompt = dedent("""\
            You are extracting structured profile information about the user.

            Your goal is to identify and save key identity information that fits the defined profile fields.
            Only save information the user explicitly states - do not make inferences.

        """)

        # Profile Fields section
        if profile_fields and self.config.enable_update_profile:
            system_prompt += dedent("""\
                ## Profile Fields

                Use `update_profile` to save structured identity information:
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

        # Custom instructions or defaults
        profile_capture_instructions = self.config.instructions or dedent("""\
            ## Guidelines

            **DO save:**
            - Name and preferred name when explicitly stated
            - Other profile fields when the user provides the information

            **DO NOT save:**
            - Information that doesn't fit the defined profile fields
            - Inferences or assumptions - only save what's explicitly stated
            - Duplicate information that matches existing values
        """)

        system_prompt += profile_capture_instructions

        # Available actions
        system_prompt += "\n## Available Actions\n\n"

        if self.config.enable_update_profile and profile_fields:
            fields_list = ", ".join(profile_fields.keys())
            system_prompt += f"- `update_profile`: Set profile fields ({fields_list})\n"

        # Examples
        system_prompt += dedent("""
            ## Examples

            **Example 1: User introduces themselves**
            User: "I'm Sarah, but everyone calls me Saz."
            → update_profile(name="Sarah", preferred_name="Saz")

            **Example 2: Nothing to save**
            User: "What's the weather like?"
            → No action needed (no profile information shared)

            ## Final Guidance

            - Only call update_profile when the user explicitly shares profile information
            - It's fine to do nothing if the conversation reveals no profile data\
        """)

        if self.config.additional_instructions:
            system_prompt += f"\n\n{self.config.additional_instructions}"

        return Message(role="system", content=system_prompt)

    def _get_extraction_tools(
        self,
        user_id: str,
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

        return functions

    async def _aget_extraction_tools(
        self,
        user_id: str,
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

    def print(self, user_id: str, *, raw: bool = False) -> None:
        """Print formatted user profile.

        Args:
            user_id: The user to print profile for.
            raw: If True, print raw dict using pprint instead of formatted panel.

        Example:
            >>> store.print(user_id="alice@example.com")
            +---------------- User Profile -----------------+
            | Name: Alice                                   |
            | Preferred Name: Ali                           |
            +--------------- alice@example.com -------------+
        """
        from agno.learn.utils import print_panel

        profile = self.get(user_id=user_id)

        lines = []

        if profile:
            # Add profile fields
            updateable_fields = self._get_updateable_fields()
            for field_name in updateable_fields:
                value = getattr(profile, field_name, None)
                if value:
                    display_name = field_name.replace("_", " ").title()
                    lines.append(f"{display_name}: {value}")

        print_panel(
            title="User Profile",
            subtitle=user_id,
            lines=lines,
            empty_message="No profile data",
            raw_data=profile,
            raw=raw,
        )
