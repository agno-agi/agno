"""
User Profile Store
==================
Storage backend for User Profile learning type.
"""

from copy import deepcopy
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Callable, List, Optional, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.learn.config import UserProfileConfig
from agno.learn.schemas import BaseUserProfile
from agno.learn.stores.base import BaseLearningStore, from_dict_safe, to_dict_safe
from agno.models.base import Model
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning


@dataclass
class UserProfileStore(BaseLearningStore):
    """Storage backend for User Profile learning type.

    Handles retrieval, storage, and extraction of user profiles.
    Profiles are stored per user_id and persist across sessions.

    Args:
        db: Database backend for UserProfile storage.
        model: Model for profile extraction.
        config: UserProfileConfig with settings.
    """

    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    model: Optional[Model] = None
    config: Optional[UserProfileConfig] = None

    # Whether profile was updated in the last run
    profile_updated: bool = False

    # Provide the system message for the manager as a string
    system_message: Optional[str] = None
    # Provide custom instructions for profile extraction
    profile_capture_instructions: Optional[str] = None
    # Additional instructions appended to the default system message
    additional_instructions: Optional[str] = None

    # Tool controls
    enable_add: bool = True
    enable_update: bool = True
    enable_delete: bool = True
    enable_clear: bool = False

    def __post_init__(self):
        self.config = self.config or UserProfileConfig()
        self.schema = self.config.schema or BaseUserProfile

    # --- Read Operations ---

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

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "get() is not supported with an async DB. Please use aget() instead."
            )

        try:
            result = self.db.get_learning(
                learning_type="user_profile",
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
            if isinstance(self.db, AsyncBaseDb):
                result = await self.db.aget_learning(
                    learning_type="user_profile",
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            else:
                result = self.db.get_learning(
                    learning_type="user_profile",
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

    # --- Write Operations ---

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

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "save() is not supported with an async DB. Please use asave() instead."
            )

        try:
            content = to_dict_safe(profile)
            if not content:
                return

            self.db.upsert_learning(
                id=self._build_profile_id(user_id, agent_id, team_id),
                learning_type="user_profile",
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

            if isinstance(self.db, AsyncBaseDb):
                await self.db.aupsert_learning(
                    id=self._build_profile_id(user_id, agent_id, team_id),
                    learning_type="user_profile",
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=self._build_profile_id(user_id, agent_id, team_id),
                    learning_type="user_profile",
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            log_debug(f"Saved user profile for user_id: {user_id}")

        except Exception as e:
            log_debug(f"Error saving user profile: {e}")

    # --- Delete Operations ---

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

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "delete() is not supported with an async DB. Please use adelete() instead."
            )

        try:
            profile_id = self._build_profile_id(user_id, agent_id, team_id)
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
            profile_id = self._build_profile_id(user_id, agent_id, team_id)
            if isinstance(self.db, AsyncBaseDb):
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

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "clear() is not supported with an async DB. Please use aclear() instead."
            )

        try:
            empty_profile = self.schema(user_id=user_id)
            self.save(user_id, empty_profile, agent_id=agent_id, team_id=team_id)
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
            await self.asave(user_id, empty_profile, agent_id=agent_id, team_id=team_id)
            log_debug(f"Cleared user profile for user_id: {user_id}")
        except Exception as e:
            log_debug(f"Error clearing user profile: {e}")

    # --- Memory Operations ---

    def add_memory(
        self,
        user_id: str,
        memory: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Add a single memory to the user's profile.

        Args:
            user_id: The unique user identifier.
            memory: The memory text to add.
            agent_id: Optional agent context.
            team_id: Optional team context.
        """
        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "add_memory() is not supported with an async DB. Please use aadd_memory() instead."
            )

        profile = self.get(user_id, agent_id=agent_id, team_id=team_id)

        if profile is None:
            profile = self.schema(user_id=user_id)

        if hasattr(profile, "add_memory"):
            profile.add_memory(memory)
        elif hasattr(profile, "memories"):
            profile.memories.append({"content": memory})

        self.save(user_id, profile, agent_id=agent_id, team_id=team_id)
        log_debug(f"Added memory for user {user_id}: {memory[:50]}...")

    async def aadd_memory(
        self,
        user_id: str,
        memory: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Async version of add_memory."""
        profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)

        if profile is None:
            profile = self.schema(user_id=user_id)

        if hasattr(profile, "add_memory"):
            profile.add_memory(memory)
        elif hasattr(profile, "memories"):
            profile.memories.append({"content": memory})

        await self.asave(user_id, profile, agent_id=agent_id, team_id=team_id)
        log_debug(f"Added memory for user {user_id}: {memory[:50]}...")

    # --- Extraction Operations ---

    def extract_and_save(
        self,
        messages: List[Message],
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

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "extract_and_save() is not supported with an async DB. Please use aextract_and_save() instead."
            )

        log_debug("UserProfileStore: Extracting user profile", center=True)

        # Reset state
        self.profile_updated = False

        # Get existing profile
        existing_profile = self.get(user_id, agent_id=agent_id, team_id=team_id)
        existing_data = self._profile_to_memory_list(existing_profile)

        # Build input string from messages
        input_string = self._messages_to_input_string(messages)

        # Get tools
        tools = self._determine_tools_for_model(
            self._get_db_tools(
                user_id=user_id,
                db=self.db,
                input_string=input_string,
                agent_id=agent_id,
                team_id=team_id,
            )
        )

        # Prepare messages for model
        messages_for_model: List[Message] = [
            self._get_system_message(existing_data),
            *messages,
        ]

        # Generate response (model will call tools)
        model_copy = deepcopy(self.model)
        response = model_copy.response(
            messages=messages_for_model,
            tools=tools,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.profile_updated = True

        log_debug("UserProfileStore: Extraction complete", center=True)

        return response.content or "No response from model"

    async def aextract_and_save(
        self,
        messages: List[Message],
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
        existing_profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)
        existing_data = self._profile_to_memory_list(existing_profile)

        # Build input string from messages
        input_string = self._messages_to_input_string(messages)

        # Get tools
        if isinstance(self.db, AsyncBaseDb):
            tools = self._determine_tools_for_model(
                await self._aget_db_tools(
                    user_id=user_id,
                    db=self.db,
                    input_string=input_string,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )
        else:
            tools = self._determine_tools_for_model(
                self._get_db_tools(
                    user_id=user_id,
                    db=self.db,
                    input_string=input_string,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )

        # Prepare messages for model
        messages_for_model: List[Message] = [
            self._get_system_message(existing_data),
            *messages,
        ]

        # Generate response (model will call tools)
        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=tools,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.profile_updated = True

        log_debug("UserProfileStore: Extraction complete", center=True)

        return response.content or "No response from model"

    # --- Task Operations ---

    def run_profile_task(
        self,
        task: str,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Run a profile management task.

        Args:
            task: The task description.
            user_id: The unique user identifier.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            Response from model.
        """
        if self.model is None:
            log_warning("No model provided for user profile task")
            return "No model provided for user profile task"

        if not self.db:
            log_warning("No DB provided for user profile store")
            return "No DB provided for user profile store"

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "run_profile_task() is not supported with an async DB. Please use arun_profile_task() instead."
            )

        log_debug("UserProfileStore: Running profile task", center=True)

        # Reset state
        self.profile_updated = False

        # Get existing profile
        existing_profile = self.get(user_id, agent_id=agent_id, team_id=team_id)
        existing_data = self._profile_to_memory_list(existing_profile)

        # Get tools
        tools = self._determine_tools_for_model(
            self._get_db_tools(
                user_id=user_id,
                db=self.db,
                input_string=task,
                agent_id=agent_id,
                team_id=team_id,
            )
        )

        # Prepare messages for model
        messages_for_model: List[Message] = [
            self._get_system_message(existing_data),
            Message(role="user", content=task),
        ]

        # Generate response (model will call tools)
        model_copy = deepcopy(self.model)
        response = model_copy.response(
            messages=messages_for_model,
            tools=tools,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.profile_updated = True

        log_debug("UserProfileStore: Task complete", center=True)

        return response.content or "No response from model"

    async def arun_profile_task(
        self,
        task: str,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Async version of run_profile_task."""
        if self.model is None:
            log_warning("No model provided for user profile task")
            return "No model provided for user profile task"

        if not self.db:
            log_warning("No DB provided for user profile store")
            return "No DB provided for user profile store"

        log_debug("UserProfileStore: Running profile task (async)", center=True)

        # Reset state
        self.profile_updated = False

        # Get existing profile
        existing_profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)
        existing_data = self._profile_to_memory_list(existing_profile)

        # Get tools
        if isinstance(self.db, AsyncBaseDb):
            tools = self._determine_tools_for_model(
                await self._aget_db_tools(
                    user_id=user_id,
                    db=self.db,
                    input_string=task,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )
        else:
            tools = self._determine_tools_for_model(
                self._get_db_tools(
                    user_id=user_id,
                    db=self.db,
                    input_string=task,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )

        # Prepare messages for model
        messages_for_model: List[Message] = [
            self._get_system_message(existing_data),
            Message(role="user", content=task),
        ]

        # Generate response (model will call tools)
        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=tools,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.profile_updated = True

        log_debug("UserProfileStore: Task complete", center=True)

        return response.content or "No response from model"

    # --- Private Helpers ---

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

        # Add name as a memory if present
        if hasattr(profile, "name") and profile.name:
            memories.append({"memory_id": "name", "memory": f"User's name is {profile.name}"})

        if hasattr(profile, "preferred_name") and profile.preferred_name:
            memories.append({"memory_id": "preferred_name", "memory": f"User prefers to be called {profile.preferred_name}"})

        # Add memories from profile
        if hasattr(profile, "memories") and profile.memories:
            for i, mem in enumerate(profile.memories):
                if isinstance(mem, dict):
                    content = mem.get("content", str(mem))
                else:
                    content = str(mem)
                memories.append({"memory_id": f"memory_{i}", "memory": content})

        return memories

    def _messages_to_input_string(self, messages: List[Message]) -> str:
        """Convert messages to input string."""
        if len(messages) == 1:
            return messages[0].get_content_string()
        else:
            return ", ".join([
                m.get_content_string()
                for m in messages
                if m.role == "user" and m.content
            ])

    def _determine_tools_for_model(self, tools: List[Callable]) -> List[Union[Function, dict]]:
        """Convert callables to Functions for model."""
        _function_names = []
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

    def _get_system_message(self, existing_data: List[dict]) -> Message:
        """Build system message for extraction."""
        if self.system_message is not None:
            return Message(role="system", content=self.system_message)

        profile_capture_instructions = self.profile_capture_instructions or dedent("""\
            Profile information should capture personal details about the user that are relevant to the current conversation, such as:
            - Personal facts: name, age, occupation, location, interests, and preferences
            - Opinions and preferences: what the user likes, dislikes, enjoys, or finds frustrating
            - Significant life events or experiences shared by the user
            - Important context about the user's current situation, challenges, or goals
            - Any other details that offer meaningful insight into the user's personality, perspective, or needs
        """)

        system_prompt_lines = [
            "You are a User Profile Manager that is responsible for managing information and preferences about the user. "
            "You will be provided with criteria for profile information to capture in the <profile_to_capture> section and a list of existing profile data in the <existing_profile> section.",
            "",
            "## When to add or update profile",
            "- Your first task is to decide if profile data needs to be added, updated, or deleted based on the user's message OR if no changes are needed.",
            "- If the user's message meets the criteria in the <profile_to_capture> section and that information is not already captured in the <existing_profile> section, you should capture it.",
            "- If the user's message does not meet the criteria in the <profile_to_capture> section, no profile updates are needed.",
            "- If the existing data in the <existing_profile> section captures all relevant information, no profile updates are needed.",
            "",
            "## How to add or update profile",
            "- If you decide to add new profile data, create entries that capture key information, as if you were storing it for future reference.",
            "- Profile entries should be brief, third-person statements that encapsulate the most important aspect of the user's input.",
            "  - Example: If the user's message is 'I'm going to the gym', an entry could be `User goes to the gym regularly`.",
            "  - Example: If the user's message is 'My name is John Doe', an entry could be `User's name is John Doe`.",
            "- Don't make a single entry too long or complex, create multiple entries if needed.",
            "- Don't repeat the same information in multiple entries. Rather update existing entries if needed.",
            "- If a user asks for profile data to be updated or forgotten, remove all reference to the information that should be forgotten.",
            "- When updating an entry, append with new information rather than completely overwriting it.",
            "- When a user's preferences change, update the relevant entries to reflect the new preferences.",
            "",
            "## Criteria for creating profile entries",
            "Use the following criteria to determine if a user's message should be captured.",
            "",
            "<profile_to_capture>",
            profile_capture_instructions,
            "</profile_to_capture>",
            "",
            "## Updating profile",
            "You will also be provided with a list of existing profile data in the <existing_profile> section. You can:",
            "  - Decide to make no changes.",
        ]

        if self.enable_add:
            system_prompt_lines.append("  - Decide to add new profile data, using the `add_profile_entry` tool.")
        if self.enable_update:
            system_prompt_lines.append("  - Decide to update an existing entry, using the `update_profile_entry` tool.")
        if self.enable_delete:
            system_prompt_lines.append("  - Decide to delete an existing entry, using the `delete_profile_entry` tool.")
        if self.enable_clear:
            system_prompt_lines.append("  - Decide to clear all profile data, using the `clear_profile` tool.")

        system_prompt_lines += [
            "You can call multiple tools in a single response if needed.",
            "Only add or update profile data if it is necessary to capture key information provided by the user.",
        ]

        if existing_data and len(existing_data) > 0:
            system_prompt_lines.append("\n<existing_profile>")
            for entry in existing_data:
                system_prompt_lines.append(f"ID: {entry['memory_id']}")
                system_prompt_lines.append(f"Entry: {entry['memory']}")
                system_prompt_lines.append("")
            system_prompt_lines.append("</existing_profile>")

        if self.additional_instructions:
            system_prompt_lines.append(self.additional_instructions)

        return Message(role="system", content="\n".join(system_prompt_lines))

    def _get_db_tools(
        self,
        user_id: str,
        db: BaseDb,
        input_string: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get sync DB tools for the model."""

        def add_profile_entry(entry: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to add a new entry to the user profile.
            Args:
                entry (str): The profile entry to be added.
                topics (Optional[List[str]]): The topics of the entry (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the entry was added successfully or not.
            """
            try:
                profile = self.get(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    profile = self.schema(user_id=user_id)

                if hasattr(profile, "memories"):
                    profile.memories.append({"content": entry, "topics": topics, "input": input_string})

                self.save(user_id, profile, agent_id=agent_id, team_id=team_id)
                log_debug(f"Profile entry added: {entry[:50]}...")
                return "Profile entry added successfully"
            except Exception as e:
                log_warning(f"Error adding profile entry: {e}")
                return f"Error adding profile entry: {e}"

        def update_profile_entry(entry_id: str, entry: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to update an existing entry in the user profile.
            Args:
                entry_id (str): The id of the entry to be updated.
                entry (str): The updated entry text.
                topics (Optional[List[str]]): The topics of the entry (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the entry was updated successfully or not.
            """
            if entry == "":
                return "Can't update entry with empty string. Use the delete function if available."

            try:
                profile = self.get(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found to update"

                # Handle special fields
                if entry_id == "name" and hasattr(profile, "name"):
                    profile.name = entry
                elif entry_id == "preferred_name" and hasattr(profile, "preferred_name"):
                    profile.preferred_name = entry
                elif entry_id.startswith("memory_") and hasattr(profile, "memories"):
                    idx = int(entry_id.replace("memory_", ""))
                    if 0 <= idx < len(profile.memories):
                        profile.memories[idx] = {"content": entry, "topics": topics, "input": input_string}

                self.save(user_id, profile, agent_id=agent_id, team_id=team_id)
                log_debug(f"Profile entry updated: {entry_id}")
                return "Profile entry updated successfully"
            except Exception as e:
                log_warning(f"Error updating profile entry: {e}")
                return f"Error updating profile entry: {e}"

        def delete_profile_entry(entry_id: str) -> str:
            """Use this function to delete an entry from the user profile.
            Args:
                entry_id (str): The id of the entry to be deleted.
            Returns:
                str: A message indicating if the entry was deleted successfully or not.
            """
            try:
                profile = self.get(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                # Handle special fields
                if entry_id == "name" and hasattr(profile, "name"):
                    profile.name = None
                elif entry_id == "preferred_name" and hasattr(profile, "preferred_name"):
                    profile.preferred_name = None
                elif entry_id.startswith("memory_") and hasattr(profile, "memories"):
                    idx = int(entry_id.replace("memory_", ""))
                    if 0 <= idx < len(profile.memories):
                        profile.memories.pop(idx)

                self.save(user_id, profile, agent_id=agent_id, team_id=team_id)
                log_debug(f"Profile entry deleted: {entry_id}")
                return "Profile entry deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting profile entry: {e}")
                return f"Error deleting profile entry: {e}"

        def clear_profile() -> str:
            """Use this function to clear all profile data for the user.

            Returns:
                str: A message indicating if the profile was cleared successfully or not.
            """
            try:
                self.clear(user_id, agent_id=agent_id, team_id=team_id)
                log_debug("Profile cleared")
                return "Profile cleared successfully"
            except Exception as e:
                log_warning(f"Error clearing profile: {e}")
                return f"Error clearing profile: {e}"

        functions: List[Callable] = []
        if self.enable_add:
            functions.append(add_profile_entry)
        if self.enable_update:
            functions.append(update_profile_entry)
        if self.enable_delete:
            functions.append(delete_profile_entry)
        if self.enable_clear:
            functions.append(clear_profile)
        return functions

    async def _aget_db_tools(
        self,
        user_id: str,
        db: Union[BaseDb, AsyncBaseDb],
        input_string: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get async DB tools for the model."""

        async def add_profile_entry(entry: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to add a new entry to the user profile.
            Args:
                entry (str): The profile entry to be added.
                topics (Optional[List[str]]): The topics of the entry (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the entry was added successfully or not.
            """
            try:
                profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    profile = self.schema(user_id=user_id)

                if hasattr(profile, "memories"):
                    profile.memories.append({"content": entry, "topics": topics, "input": input_string})

                await self.asave(user_id, profile, agent_id=agent_id, team_id=team_id)
                log_debug(f"Profile entry added: {entry[:50]}...")
                return "Profile entry added successfully"
            except Exception as e:
                log_warning(f"Error adding profile entry: {e}")
                return f"Error adding profile entry: {e}"

        async def update_profile_entry(entry_id: str, entry: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to update an existing entry in the user profile.
            Args:
                entry_id (str): The id of the entry to be updated.
                entry (str): The updated entry text.
                topics (Optional[List[str]]): The topics of the entry (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the entry was updated successfully or not.
            """
            if entry == "":
                return "Can't update entry with empty string. Use the delete function if available."

            try:
                profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found to update"

                # Handle special fields
                if entry_id == "name" and hasattr(profile, "name"):
                    profile.name = entry
                elif entry_id == "preferred_name" and hasattr(profile, "preferred_name"):
                    profile.preferred_name = entry
                elif entry_id.startswith("memory_") and hasattr(profile, "memories"):
                    idx = int(entry_id.replace("memory_", ""))
                    if 0 <= idx < len(profile.memories):
                        profile.memories[idx] = {"content": entry, "topics": topics, "input": input_string}

                await self.asave(user_id, profile, agent_id=agent_id, team_id=team_id)
                log_debug(f"Profile entry updated: {entry_id}")
                return "Profile entry updated successfully"
            except Exception as e:
                log_warning(f"Error updating profile entry: {e}")
                return f"Error updating profile entry: {e}"

        async def delete_profile_entry(entry_id: str) -> str:
            """Use this function to delete an entry from the user profile.
            Args:
                entry_id (str): The id of the entry to be deleted.
            Returns:
                str: A message indicating if the entry was deleted successfully or not.
            """
            try:
                profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                # Handle special fields
                if entry_id == "name" and hasattr(profile, "name"):
                    profile.name = None
                elif entry_id == "preferred_name" and hasattr(profile, "preferred_name"):
                    profile.preferred_name = None
                elif entry_id.startswith("memory_") and hasattr(profile, "memories"):
                    idx = int(entry_id.replace("memory_", ""))
                    if 0 <= idx < len(profile.memories):
                        profile.memories.pop(idx)

                await self.asave(user_id, profile, agent_id=agent_id, team_id=team_id)
                log_debug(f"Profile entry deleted: {entry_id}")
                return "Profile entry deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting profile entry: {e}")
                return f"Error deleting profile entry: {e}"

        async def clear_profile() -> str:
            """Use this function to clear all profile data for the user.

            Returns:
                str: A message indicating if the profile was cleared successfully or not.
            """
            try:
                await self.aclear(user_id, agent_id=agent_id, team_id=team_id)
                log_debug("Profile cleared")
                return "Profile cleared successfully"
            except Exception as e:
                log_warning(f"Error clearing profile: {e}")
                return f"Error clearing profile: {e}"

        functions: List[Callable] = []
        if self.enable_add:
            functions.append(add_profile_entry)
        if self.enable_update:
            functions.append(update_profile_entry)
        if self.enable_delete:
            functions.append(delete_profile_entry)
        if self.enable_clear:
            functions.append(clear_profile)
        return functions
