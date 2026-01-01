"""
User Profile Store
==================
Storage backend for User Profile learning type.
"""

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Callable, List, Optional, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.learn.config import UserProfileConfig
from agno.learn.schemas import BaseUserProfile
from agno.learn.stores.base import BaseLearningStore, from_dict_safe, to_dict_safe
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning


@dataclass
class UserProfileStore(BaseLearningStore):
    """Storage backend for User Profile learning type.

    Handles retrieval, storage, and extraction of user profiles.
    Profiles are stored per user_id and persist across sessions.

    Args:
        config: UserProfileConfig with all settings including db and model.
    """

    config: UserProfileConfig = field(default_factory=UserProfileConfig)

    # State tracking (internal)
    profile_updated: bool = False

    def __post_init__(self):
        self.schema = self.config.schema or BaseUserProfile

    # --- Properties for cleaner access ---

    @property
    def db(self) -> Optional[Union[BaseDb, AsyncBaseDb]]:
        return self.config.db

    @property
    def model(self):
        return self.config.model

    # --- Agent Tool ---

    def get_agent_tool(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Callable:
        """Get the tool to expose to the agent.

        Returns a callable that the agent can use to update user memory.
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

        return update_user_memory

    async def aget_agent_tool(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Callable:
        """Get the async tool to expose to the agent."""

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

        return update_user_memory

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
            raise ValueError("get() is not supported with an async DB. Please use aget() instead.")

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
            raise ValueError("save() is not supported with an async DB. Please use asave() instead.")

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
            raise ValueError("delete() is not supported with an async DB. Please use adelete() instead.")

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
            raise ValueError("clear() is not supported with an async DB. Please use aclear() instead.")

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
            raise ValueError("add_memory() is not supported with an async DB. Please use aadd_memory() instead.")

        profile = self.get(user_id, agent_id=agent_id, team_id=team_id)

        if profile is None:
            profile = self.schema(user_id=user_id)

        if hasattr(profile, "add_memory"):
            profile.add_memory(memory)
        elif hasattr(profile, "memories"):
            memory_id = str(uuid.uuid4())[:8]
            profile.memories.append({"id": memory_id, "content": memory})

        print(f"about to upsert profile: {profile}")
        self.save(user_id, profile,  agent_id=agent_id, team_id=team_id)
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
            memory_id = str(uuid.uuid4())[:8]
            profile.memories.append({"id": memory_id, "content": memory})

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
        tools = self._get_extraction_tools(
            user_id=user_id,
            input_string=input_string,
            agent_id=agent_id,
            team_id=team_id,
        )
        tool_map = {func.__name__: func for func in tools}

        # Convert to Function objects for model
        functions = self._determine_tools_for_model(tools)

        # Prepare messages for model
        messages_for_model: List[Message] = [
            self._get_system_message(existing_data),
            *messages,
        ]

        # Generate response (model will call tools)
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
                        self.profile_updated = True
                    except Exception as e:
                        log_warning(f"Error executing {tool_name}: {e}")

        log_debug("UserProfileStore: Extraction complete", center=True)

        return response.content or "Profile updated" if self.profile_updated else "No updates needed"

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
            tools = await self._aget_extraction_tools(
                user_id=user_id,
                input_string=input_string,
                agent_id=agent_id,
                team_id=team_id,
            )
        else:
            tools = self._get_extraction_tools(
                user_id=user_id,
                input_string=input_string,
                agent_id=agent_id,
                team_id=team_id,
            )
        tool_map = {func.__name__: func for func in tools}

        # Convert to Function objects for model
        functions = self._determine_tools_for_model(tools)

        # Prepare messages for model
        messages_for_model: List[Message] = [
            self._get_system_message(existing_data),
            *messages,
        ]

        # Generate response (model will call tools)
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
                        self.profile_updated = True
                    except Exception as e:
                        log_warning(f"Error executing {tool_name}: {e}")

        log_debug("UserProfileStore: Extraction complete", center=True)

        return response.content or "Profile updated" if self.profile_updated else "No updates needed"

    # --- Update Operations (called by agent tool) ---

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
        messages = [Message(role="user", content=task)]
        return await self.aextract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
        )

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

        # Add memories from profile
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

    def _messages_to_input_string(self, messages: List[Message]) -> str:
        """Convert messages to input string."""
        if len(messages) == 1:
            return messages[0].get_content_string()
        else:
            return "\n".join([f"{m.role}: {m.get_content_string()}" for m in messages if m.content])

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

    def _get_system_message(self, existing_data: List[dict]) -> Message:
        """Build system message for extraction."""
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
            - Inferences or assumptions not directly stated
        """)

        system_prompt = dedent(f"""\
            You are a User Profile Manager. Your job is to maintain accurate, useful memories about the user.

            ## Your Task
            Review the conversation and decide if any information should be saved to the user's profile.
            Only save information that will be genuinely useful in future conversations.

            ## What To Capture
            {profile_capture_instructions}

            ## How To Write Entries
            - Write in third person: "User is..." or "User prefers..."
            - Be specific and factual, not vague
            - One clear fact per entry
            - Preserve nuance - don't overgeneralize

            Good: "User is a software engineer at Google working on search infrastructure"
            Bad: "User works in tech"

            Good: "User mentioned going to the gym today"
            Bad: "User goes to the gym regularly" (don't infer patterns from single mentions)

            ## Existing Profile
        """)

        if existing_data:
            system_prompt += "\nThe user already has these memories saved:\n"
            for entry in existing_data:
                system_prompt += f"- [{entry['id']}] {entry['content']}\n"
            system_prompt += "\nYou can update or delete these if the conversation indicates changes.\n"
        else:
            system_prompt += "\nNo existing memories for this user.\n"

        system_prompt += dedent("""\

            ## Available Actions
        """)

        if self.config.enable_add:
            system_prompt += "- `add_memory`: Add a new memory about the user\n"
        if self.config.enable_update:
            system_prompt += "- `update_memory`: Update an existing memory by its ID\n"
        if self.config.enable_delete:
            system_prompt += "- `delete_memory`: Delete a memory that is no longer accurate\n"
        if self.config.enable_clear:
            system_prompt += "- `clear_all_memories`: Remove all memories (use sparingly)\n"

        system_prompt += dedent("""\

            ## Important
            - Only take action if there's genuinely useful information to save
            - It's fine to do nothing if the conversation has no profile-relevant content
            - Quality over quantity - fewer accurate memories beats many vague ones
        """)

        if self.config.additional_instructions:
            system_prompt += f"\n{self.config.additional_instructions}"

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
                profile = self.get(user_id, agent_id=agent_id, team_id=team_id)
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

                self.save(user_id, profile, agent_id=agent_id, team_id=team_id)
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
                profile = self.get(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                if hasattr(profile, "memories"):
                    for mem in profile.memories:
                        if isinstance(mem, dict) and mem.get("id") == memory_id:
                            mem["content"] = memory
                            mem["source"] = input_string[:200] if input_string else None
                            self.save(user_id, profile, agent_id=agent_id, team_id=team_id)
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
                profile = self.get(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                if hasattr(profile, "memories"):
                    original_len = len(profile.memories)
                    profile.memories = [
                        mem for mem in profile.memories if not (isinstance(mem, dict) and mem.get("id") == memory_id)
                    ]
                    if len(profile.memories) < original_len:
                        self.save(user_id, profile, agent_id=agent_id, team_id=team_id)
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
                self.clear(user_id, agent_id=agent_id, team_id=team_id)
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
                profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)
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

                await self.asave(user_id, profile, agent_id=agent_id, team_id=team_id)
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
                profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                if hasattr(profile, "memories"):
                    for mem in profile.memories:
                        if isinstance(mem, dict) and mem.get("id") == memory_id:
                            mem["content"] = memory
                            mem["source"] = input_string[:200] if input_string else None
                            await self.asave(user_id, profile, agent_id=agent_id, team_id=team_id)
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
                profile = await self.aget(user_id, agent_id=agent_id, team_id=team_id)
                if profile is None:
                    return "No profile found"

                if hasattr(profile, "memories"):
                    original_len = len(profile.memories)
                    profile.memories = [
                        mem for mem in profile.memories if not (isinstance(mem, dict) and mem.get("id") == memory_id)
                    ]
                    if len(profile.memories) < original_len:
                        await self.asave(user_id, profile, agent_id=agent_id, team_id=team_id)
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
                await self.aclear(user_id, agent_id=agent_id, team_id=team_id)
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
