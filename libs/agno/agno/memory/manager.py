from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Literal, Optional, Type, Union

from pydantic import BaseModel, Field

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas import UserMemory
from agno.models.base import Model
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_warning, set_log_level_to_debug, set_log_level_to_info
from agno.utils.prompts import get_json_output_prompt
from agno.utils.string import parse_response_model_str


class MemorySearchResponse(BaseModel):
    """Model for Memory Search Response."""

    memory_ids: List[str] = Field(
        ..., description="The IDs of the memories that are most semantically similar to the query."
    )


@dataclass
class MemoryManager:
    """Memory Manager"""

    # Model used for memory management
    model: Optional[Model] = None

    # Provide the system message for the manager as a string. If not provided, a default prompt will be used.
    system_message: Optional[str] = None
    # Provide the memory capture instructions for the manager as a string. If not provided, a default prompt will be used.
    memory_capture_instructions: Optional[str] = None
    # Additional instructions for the manager. These instructions are appended to the default system prompt.
    additional_instructions: Optional[str] = None

    # Whether memories were created in the last run
    memories_updated: bool = False

    # ----- db tools ---------
    # Whether to delete memories
    delete_memories: bool = True
    # Whether to clear memories
    clear_memories: bool = True
    # Whether to update memories
    update_memories: bool = True
    # whether to add memories
    add_memories: bool = True

    # The database to store memories
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None

    debug_mode: bool = False

    def __init__(
        self,
        model: Optional[Model] = None,
        system_message: Optional[str] = None,
        memory_capture_instructions: Optional[str] = None,
        additional_instructions: Optional[str] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        delete_memories: bool = False,
        update_memories: bool = True,
        add_memories: bool = True,
        clear_memories: bool = False,
        debug_mode: bool = False,
    ):
        self.model = model
        if self.model is not None and isinstance(self.model, str):
            raise ValueError("Model must be a Model object, not a string")
        self.system_message = system_message
        self.memory_capture_instructions = memory_capture_instructions
        self.additional_instructions = additional_instructions
        self.db = db
        self.delete_memories = delete_memories
        self.update_memories = update_memories
        self.add_memories = add_memories
        self.clear_memories = clear_memories
        self.debug_mode = debug_mode
        self._tools_for_model: Optional[List[Dict[str, Any]]] = None
        self._functions_for_model: Optional[Dict[str, Function]] = None

    def get_model(self) -> Model:
        if self.model is None:
            try:
                from agno.models.openai import OpenAIChat
            except ModuleNotFoundError as e:
                log_error(e)
                log_error(
                    "Agno uses `openai` as the default model provider. Please provide a `model` or install `openai`."
                )
                exit(1)
            self.model = OpenAIChat(id="gpt-4o")
        return self.model

    def read_from_db(self, user_id: Optional[str] = None):
        if self.db:
            # If no user_id is provided, read all memories
            if user_id is None:
                all_memories: List[UserMemory] = self.db.get_user_memories()  # type: ignore
            else:
                all_memories = self.db.get_user_memories(user_id=user_id)  # type: ignore

            memories: Dict[str, List[UserMemory]] = {}
            for memory in all_memories:
                if memory.user_id is not None and memory.memory_id is not None:
                    memories.setdefault(memory.user_id, []).append(memory)

            return memories
        return None

    async def aread_from_db(self, user_id: Optional[str] = None):
        if self.db:
            if isinstance(self.db, AsyncBaseDb):
                # If no user_id is provided, read all memories
                if user_id is None:
                    all_memories: List[UserMemory] = await self.db.get_user_memories()  # type: ignore
                else:
                    all_memories = await self.db.get_user_memories(user_id=user_id)  # type: ignore
            else:
                if user_id is None:
                    all_memories = self.db.get_user_memories()  # type: ignore
                else:
                    all_memories = self.db.get_user_memories(user_id=user_id)  # type: ignore

            memories: Dict[str, List[UserMemory]] = {}
            for memory in all_memories:
                if memory.user_id is not None and memory.memory_id is not None:
                    memories.setdefault(memory.user_id, []).append(memory)

            return memories
        return None

    def set_log_level(self):
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    def initialize(self, user_id: Optional[str] = None):
        self.set_log_level()

    # -*- Public Functions
    def get_user_memories(self, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
        """Get the user memories for a given user id"""
        if self.db:
            if user_id is None:
                user_id = "default"
            # Refresh from the Db
            memories = self.read_from_db(user_id=user_id)
            if memories is None:
                return []
            return memories.get(user_id, [])
        else:
            log_warning("Memory Db not provided.")
            return []

    async def aget_user_memories(self, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
        """Get the user memories for a given user id"""
        if self.db:
            if user_id is None:
                user_id = "default"
            # Refresh from the Db
            memories = await self.aread_from_db(user_id=user_id)
            if memories is None:
                return []
            return memories.get(user_id, [])
        else:
            log_warning("Memory Db not provided.")
            return []

    def get_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> Optional[UserMemory]:
        """Get the user memory for a given user id"""
        if self.db:
            if user_id is None:
                user_id = "default"
            # Refresh from the DB
            memories = self.read_from_db(user_id=user_id)
            if memories is None:
                return None
            memories_for_user = memories.get(user_id, [])
            for memory in memories_for_user:
                if memory.memory_id == memory_id:
                    return memory
            return None
        else:
            log_warning("Memory Db not provided.")
            return None

    def add_user_memory(
        self,
        memory: UserMemory,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """Add a user memory for a given user id
        Args:
            memory (UserMemory): The memory to add
            user_id (Optional[str]): The user id to add the memory to. If not provided, the memory is added to the "default" user.
        Returns:
            str: The id of the memory
        """
        if self.db:
            if memory.memory_id is None:
                from uuid import uuid4

                memory_id = memory.memory_id or str(uuid4())
                memory.memory_id = memory_id

            if user_id is None:
                user_id = "default"
            memory.user_id = user_id

            if not memory.updated_at:
                memory.updated_at = datetime.now()

            self._upsert_db_memory(memory=memory)
            return memory.memory_id

        else:
            log_warning("Memory Db not provided.")
            return None

    def replace_user_memory(
        self,
        memory_id: str,
        memory: UserMemory,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """Replace a user memory for a given user id
        Args:
            memory_id (str): The id of the memory to replace
            memory (UserMemory): The memory to add
            user_id (Optional[str]): The user id to add the memory to. If not provided, the memory is added to the "default" user.
        Returns:
            str: The id of the memory
        """
        if self.db:
            if user_id is None:
                user_id = "default"

            if not memory.updated_at:
                memory.updated_at = datetime.now()

            memory.memory_id = memory_id
            memory.user_id = user_id

            self._upsert_db_memory(memory=memory)

            return memory.memory_id
        else:
            log_warning("Memory Db not provided.")
            return None

    def clear(self) -> None:
        """Clears the memory."""
        if self.db:
            self.db.clear_memories()

    def delete_user_memory(
        self,
        memory_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Delete a user memory for a given user id
        Args:
            memory_id (str): The id of the memory to delete
            user_id (Optional[str]): The user id to delete the memory from. If not provided, the memory is deleted from the "default" user.
        """
        if user_id is None:
            user_id = "default"

        if self.db:
            self._delete_db_memory(memory_id=memory_id, user_id=user_id)
        else:
            log_warning("Memory DB not provided.")
            return None

    # -*- Agent Functions
    def create_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Creates memories from multiple messages and adds them to the memory db."""
        self.set_log_level()

        if self.db is None:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "create_user_memories() is not supported with an async DB. Please use acreate_user_memories() instead."
            )

        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        if user_id is None:
            user_id = "default"

        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        existing_memories = memories.get(user_id, [])  # type: ignore
        existing_memories = [{"memory_id": memory.memory_id, "memory": memory.memory} for memory in existing_memories]
        response = self.create_or_update_memories(  # type: ignore
            messages=messages,
            existing_memories=existing_memories,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            db=self.db,
            update_memories=self.update_memories,
            add_memories=self.add_memories,
        )

        # We refresh from the DB
        self.read_from_db(user_id=user_id)
        return response

    async def acreate_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Creates memories from multiple messages and adds them to the memory db."""
        self.set_log_level()

        if self.db is None:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        if user_id is None:
            user_id = "default"

        if isinstance(self.db, AsyncBaseDb):
            memories = await self.aread_from_db(user_id=user_id)
        else:
            memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        existing_memories = memories.get(user_id, [])  # type: ignore
        existing_memories = [{"memory_id": memory.memory_id, "memory": memory.memory} for memory in existing_memories]

        response = await self.acreate_or_update_memories(  # type: ignore
            messages=messages,
            existing_memories=existing_memories,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            db=self.db,
            update_memories=self.update_memories,
            add_memories=self.add_memories,
        )

        # We refresh from the DB
        if isinstance(self.db, AsyncBaseDb):
            memories = await self.aread_from_db(user_id=user_id)
        else:
            memories = self.read_from_db(user_id=user_id)

        return response

    def update_memory_task(self, task: str, user_id: Optional[str] = None) -> str:
        """Updates the memory with a task"""

        if not self.db:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if not isinstance(self.db, BaseDb):
            raise ValueError(
                "update_memory_task() is not supported with an async DB. Please use aupdate_memory_task() instead."
            )

        if user_id is None:
            user_id = "default"

        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        existing_memories = memories.get(user_id, [])  # type: ignore
        existing_memories = [{"memory_id": memory.memory_id, "memory": memory.memory} for memory in existing_memories]
        # The memory manager updates the DB directly
        response = self.run_memory_task(  # type: ignore
            task=task,
            existing_memories=existing_memories,
            user_id=user_id,
            db=self.db,
            delete_memories=self.delete_memories,
            update_memories=self.update_memories,
            add_memories=self.add_memories,
            clear_memories=self.clear_memories,
        )

        # We refresh from the DB
        self.read_from_db(user_id=user_id)

        return response

    async def aupdate_memory_task(self, task: str, user_id: Optional[str] = None) -> str:
        """Updates the memory with a task"""
        self.set_log_level()

        if not self.db:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if user_id is None:
            user_id = "default"

        if isinstance(self.db, AsyncBaseDb):
            memories = await self.aread_from_db(user_id=user_id)
        else:
            memories = self.read_from_db(user_id=user_id)

        if memories is None:
            memories = {}

        existing_memories = memories.get(user_id, [])  # type: ignore
        existing_memories = [{"memory_id": memory.memory_id, "memory": memory.memory} for memory in existing_memories]
        # The memory manager updates the DB directly
        response = await self.arun_memory_task(  # type: ignore
            task=task,
            existing_memories=existing_memories,
            user_id=user_id,
            db=self.db,
            delete_memories=self.delete_memories,
            update_memories=self.update_memories,
            add_memories=self.add_memories,
            clear_memories=self.clear_memories,
        )

        # We refresh from the DB
        if isinstance(self.db, AsyncBaseDb):
            await self.aread_from_db(user_id=user_id)
        else:
            self.read_from_db(user_id=user_id)

        return response

    # -*- Memory Db Functions
    def _upsert_db_memory(self, memory: UserMemory) -> str:
        """Use this function to add a memory to the database."""
        try:
            if not self.db:
                raise ValueError("Memory db not initialized")
            self.db.upsert_user_memory(memory=memory)
            return "Memory added successfully"
        except Exception as e:
            log_warning(f"Error storing memory in db: {e}")
            return f"Error adding memory: {e}"

    def _delete_db_memory(self, memory_id: str, user_id: Optional[str] = None) -> str:
        """Use this function to delete a memory from the database."""
        try:
            if not self.db:
                raise ValueError("Memory db not initialized")

            if user_id is None:
                user_id = "default"

            self.db.delete_user_memory(memory_id=memory_id, user_id=user_id)
            return "Memory deleted successfully"
        except Exception as e:
            log_warning(f"Error deleting memory in db: {e}")
            return f"Error deleting memory: {e}"

    # -*- Utility Functions
    def search_user_memories(
        self,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        retrieval_method: Optional[Literal["last_n", "first_n", "agentic"]] = None,
        user_id: Optional[str] = None,
    ) -> List[UserMemory]:
        """Search through user memories using the specified retrieval method.

        Args:
            query: The search query for agentic search. Required if retrieval_method is "agentic".
            limit: Maximum number of memories to return. Defaults to self.retrieval_limit if not specified. Optional.
            retrieval_method: The method to use for retrieving memories. Defaults to self.retrieval if not specified.
                - "last_n": Return the most recent memories
                - "first_n": Return the oldest memories
                - "agentic": Return memories most similar to the query, but using an agentic approach
            user_id: The user to search for. Optional.

        Returns:
            A list of UserMemory objects matching the search criteria.
        """

        if user_id is None:
            user_id = "default"

        self.set_log_level()

        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        if not memories:
            return []

        # Use default retrieval method if not specified
        retrieval_method = retrieval_method
        # Use default limit if not specified
        limit = limit

        # Handle different retrieval methods
        if retrieval_method == "agentic":
            if not query:
                raise ValueError("Query is required for agentic search")

            return self._search_user_memories_agentic(user_id=user_id, query=query, limit=limit)

        elif retrieval_method == "first_n":
            return self._get_first_n_memories(user_id=user_id, limit=limit)

        else:  # Default to last_n
            return self._get_last_n_memories(user_id=user_id, limit=limit)

    def _get_response_format(self) -> Union[Dict[str, Any], Type[BaseModel]]:
        model = self.get_model()
        if model.supports_native_structured_outputs:
            return MemorySearchResponse

        elif model.supports_json_schema_outputs:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": MemorySearchResponse.__name__,
                    "schema": MemorySearchResponse.model_json_schema(),
                },
            }
        else:
            return {"type": "json_object"}

    def _search_user_memories_agentic(self, user_id: str, query: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Search through user memories using agentic search."""
        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        if not memories:
            return []

        model = self.get_model()

        response_format = self._get_response_format()

        log_debug("Searching for memories", center=True)

        # Get all memories as a list
        user_memories: List[UserMemory] = memories[user_id]
        system_message_str = "Your task is to search through user memories and return the IDs of the memories that are related to the query.\n"
        system_message_str += "\n<user_memories>\n"
        for memory in user_memories:
            system_message_str += f"ID: {memory.memory_id}\n"
            system_message_str += f"Memory: {memory.memory}\n"
            if memory.topics:
                system_message_str += f"Topics: {','.join(memory.topics)}\n"
            system_message_str += "\n"
        system_message_str = system_message_str.strip()
        system_message_str += "\n</user_memories>\n\n"
        system_message_str += "REMEMBER: Only return the IDs of the memories that are related to the query."

        if response_format == {"type": "json_object"}:
            system_message_str += "\n" + get_json_output_prompt(MemorySearchResponse)  # type: ignore

        messages_for_model = [
            Message(role="system", content=system_message_str),
            Message(
                role="user",
                content=f"Return the IDs of the memories related to the following query: {query}",
            ),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model.response(messages=messages_for_model, response_format=response_format)
        log_debug("Search for memories complete", center=True)

        memory_search: Optional[MemorySearchResponse] = None
        # If the model natively supports structured outputs, the parsed value is already in the structured format
        if (
            model.supports_native_structured_outputs
            and response.parsed is not None
            and isinstance(response.parsed, MemorySearchResponse)
        ):
            memory_search = response.parsed

        # Otherwise convert the response to the structured format
        if isinstance(response.content, str):
            try:
                memory_search = parse_response_model_str(response.content, MemorySearchResponse)  # type: ignore

                # Update RunOutput
                if memory_search is None:
                    log_warning("Failed to convert memory_search response to MemorySearchResponse")
                    return []
            except Exception as e:
                log_warning(f"Failed to convert memory_search response to MemorySearchResponse: {e}")
                return []

        memories_to_return = []
        if memory_search:
            for memory_id in memory_search.memory_ids:
                for memory in user_memories:
                    if memory.memory_id == memory_id:
                        memories_to_return.append(memory)
        return memories_to_return[:limit]

    def _get_last_n_memories(self, user_id: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Get the most recent user memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            A list of the most recent UserMemory objects.
        """
        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        memories_list = memories.get(user_id, [])

        # Sort memories by updated_at timestamp if available
        if memories_list:
            # Sort memories by updated_at timestamp (newest first)
            # If updated_at is None, place at the beginning of the list
            sorted_memories_list = sorted(
                memories_list,
                key=lambda memory: memory.updated_at or datetime.min,
            )
        else:
            sorted_memories_list = []

        if limit is not None and limit > 0:
            sorted_memories_list = sorted_memories_list[-limit:]

        return sorted_memories_list

    def _get_first_n_memories(self, user_id: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Get the oldest user memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            A list of the oldest UserMemory objects.
        """
        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        memories_list = memories.get(user_id, [])
        # Sort memories by updated_at timestamp if available
        if memories_list:
            # Sort memories by updated_at timestamp (oldest first)
            # If updated_at is None, place at the end of the list
            sorted_memories_list = sorted(
                memories_list,
                key=lambda memory: memory.updated_at or datetime.max,
            )

        else:
            sorted_memories_list = []

        if limit is not None and limit > 0:
            sorted_memories_list = sorted_memories_list[:limit]

        return sorted_memories_list

    # --Memory Manager Functions--
    def determine_tools_for_model(self, tools: List[Callable]) -> None:
        # Have to reset each time, because of different user IDs
        self._tools_for_model = []
        self._functions_for_model = {}

        for tool in tools:
            try:
                function_name = tool.__name__
                if function_name not in self._functions_for_model:
                    func = Function.from_callable(tool, strict=True)  # type: ignore
                    func.strict = True
                    self._functions_for_model[func.name] = func
                    self._tools_for_model.append({"type": "function", "function": func.to_dict()})
                    log_debug(f"Added function {func.name}")
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

    def get_system_message(
        self,
        existing_memories: Optional[List[Dict[str, Any]]] = None,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
        enable_update_memory: bool = True,
        enable_add_memory: bool = True,
    ) -> Message:
        if self.system_message is not None:
            return Message(role="system", content=self.system_message)

        memory_capture_instructions = self.memory_capture_instructions or dedent("""\
            Memories should capture personal information about the user that is relevant to the current conversation, such as:
            - Personal facts: name, age, occupation, location, interests, and preferences
            - Opinions and preferences: what the user likes, dislikes, enjoys, or finds frustrating
            - Significant life events or experiences shared by the user
            - Important context about the user's current situation, challenges, or goals
            - Any other details that offer meaningful insight into the user's personality, perspective, or needs
        """)

        # -*- Return a system message for the memory manager
        system_prompt_lines = [
            "You are a Memory Manager that is responsible for managing information and preferences about the user. "
            "You will be provided with a criteria for memories to capture in the <memories_to_capture> section and a list of existing memories in the <existing_memories> section.",
            "",
            "## When to add or update memories",
            "- Your first task is to decide if a memory needs to be added, updated, or deleted based on the user's message OR if no changes are needed.",
            "- If the user's message meets the criteria in the <memories_to_capture> section and that information is not already captured in the <existing_memories> section, you should capture it as a memory.",
            "- If the users messages does not meet the criteria in the <memories_to_capture> section, no memory updates are needed.",
            "- If the existing memories in the <existing_memories> section capture all relevant information, no memory updates are needed.",
            "",
            "## How to add or update memories",
            "- If you decide to add a new memory, create memories that captures key information, as if you were storing it for future reference.",
            "- Memories should be a brief, third-person statements that encapsulate the most important aspect of the user's input, without adding any extraneous information.",
            "  - Example: If the user's message is 'I'm going to the gym', a memory could be `John Doe goes to the gym regularly`.",
            "  - Example: If the user's message is 'My name is John Doe', a memory could be `User's name is John Doe`.",
            "- Don't make a single memory too long or complex, create multiple memories if needed to capture all the information.",
            "- Don't repeat the same information in multiple memories. Rather update existing memories if needed.",
            "- If a user asks for a memory to be updated or forgotten, remove all reference to the information that should be forgotten. Don't say 'The user used to like ...`",
            "- When updating a memory, append the existing memory with new information rather than completely overwriting it.",
            "- When a user's preferences change, update the relevant memories to reflect the new preferences but also capture what the user's preferences used to be and what has changed.",
            "",
            "## Criteria for creating memories",
            "Use the following criteria to determine if a user's message should be captured as a memory.",
            "",
            "<memories_to_capture>",
            memory_capture_instructions,
            "</memories_to_capture>",
            "",
            "## Updating memories",
            "You will also be provided with a list of existing memories in the <existing_memories> section. You can:",
            "  - Decide to make no changes.",
        ]
        if enable_add_memory:
            system_prompt_lines.append("  - Decide to add a new memory, using the `add_memory` tool.")
        if enable_update_memory:
            system_prompt_lines.append("  - Decide to update an existing memory, using the `update_memory` tool.")
        if enable_delete_memory:
            system_prompt_lines.append("  - Decide to delete an existing memory, using the `delete_memory` tool.")
        if enable_clear_memory:
            system_prompt_lines.append("  - Decide to clear all memories, using the `clear_memory` tool.")

        system_prompt_lines += [
            "You can call multiple tools in a single response if needed. ",
            "Only add or update memories if it is necessary to capture key information provided by the user.",
        ]

        if existing_memories and len(existing_memories) > 0:
            system_prompt_lines.append("\n<existing_memories>")
            for existing_memory in existing_memories:
                system_prompt_lines.append(f"ID: {existing_memory['memory_id']}")
                system_prompt_lines.append(f"Memory: {existing_memory['memory']}")
                system_prompt_lines.append("")
            system_prompt_lines.append("</existing_memories>")

        if self.additional_instructions:
            system_prompt_lines.append(self.additional_instructions)

        return Message(role="system", content="\n".join(system_prompt_lines))

    def create_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: BaseDb,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        update_memories: bool = True,
        add_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        if len(messages) == 1:
            input_string = messages[0].get_content_string()
        else:
            input_string = f"{', '.join([m.get_content_string() for m in messages if m.role == 'user' and m.content])}"

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.determine_tools_for_model(
            self._get_db_tools(
                user_id,
                db,
                input_string,
                agent_id=agent_id,
                team_id=team_id,
                enable_add_memory=add_memories,
                enable_update_memory=update_memories,
                enable_delete_memory=False,
                enable_clear_memory=False,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories=existing_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
                enable_delete_memory=False,
                enable_clear_memory=False,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(
            messages=messages_for_model, tools=self._tools_for_model, functions=self._functions_for_model
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    async def acreate_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: Union[BaseDb, AsyncBaseDb],
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        update_memories: bool = True,
        add_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        if len(messages) == 1:
            input_string = messages[0].get_content_string()
        else:
            input_string = f"{', '.join([m.get_content_string() for m in messages if m.role == 'user' and m.content])}"

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        if isinstance(db, AsyncBaseDb):
            self.determine_tools_for_model(
                await self._aget_db_tools(
                    user_id,
                    db,
                    input_string,
                    agent_id=agent_id,
                    team_id=team_id,
                    enable_add_memory=add_memories,
                    enable_update_memory=update_memories,
                    enable_delete_memory=False,
                    enable_clear_memory=False,
                ),
            )
        else:
            self.determine_tools_for_model(
                self._get_db_tools(
                    user_id,
                    db,
                    input_string,
                    agent_id=agent_id,
                    team_id=team_id,
                    enable_add_memory=add_memories,
                    enable_update_memory=update_memories,
                    enable_delete_memory=False,
                    enable_clear_memory=False,
                ),
            )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories=existing_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
                enable_delete_memory=False,
                enable_clear_memory=False,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(
            messages=messages_for_model, tools=self._tools_for_model, functions=self._functions_for_model
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    def run_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: BaseDb,
        delete_memories: bool = True,
        update_memories: bool = True,
        add_memories: bool = True,
        clear_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.determine_tools_for_model(
            self._get_db_tools(
                user_id,
                db,
                task,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(
            messages=messages_for_model, tools=self._tools_for_model, functions=self._functions_for_model
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    async def arun_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: Union[BaseDb, AsyncBaseDb],
        delete_memories: bool = True,
        clear_memories: bool = True,
        update_memories: bool = True,
        add_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        if isinstance(db, AsyncBaseDb):
            self.determine_tools_for_model(
                await self._aget_db_tools(
                    user_id,
                    db,
                    task,
                    enable_delete_memory=delete_memories,
                    enable_clear_memory=clear_memories,
                    enable_update_memory=update_memories,
                    enable_add_memory=add_memories,
                ),
            )
        else:
            self.determine_tools_for_model(
                self._get_db_tools(
                    user_id,
                    db,
                    task,
                    enable_delete_memory=delete_memories,
                    enable_clear_memory=clear_memories,
                    enable_update_memory=update_memories,
                    enable_add_memory=add_memories,
                ),
            )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(
            messages=messages_for_model, tools=self._tools_for_model, functions=self._functions_for_model
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    # -*- DB Functions
    def _get_db_tools(
        self,
        user_id: str,
        db: BaseDb,
        input_string: str,
        enable_add_memory: bool = True,
        enable_update_memory: bool = True,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        def add_memory(memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to add a memory to the database.
            Args:
                memory (str): The memory to be added.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was added successfully or not.
            """
            from uuid import uuid4

            from agno.db.base import UserMemory

            try:
                memory_id = str(uuid4())
                db.upsert_user_memory(
                    UserMemory(
                        memory_id=memory_id,
                        user_id=user_id,
                        agent_id=agent_id,
                        team_id=team_id,
                        memory=memory,
                        topics=topics,
                        input=input_string,
                    )
                )
                log_debug(f"Memory added: {memory_id}")
                return "Memory added successfully"
            except Exception as e:
                log_warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def update_memory(memory_id: str, memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to update an existing memory in the database.
            Args:
                memory_id (str): The id of the memory to be updated.
                memory (str): The updated memory.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was updated successfully or not.
            """
            from agno.db.base import UserMemory

            try:
                db.upsert_user_memory(
                    UserMemory(
                        memory_id=memory_id,
                        memory=memory,
                        topics=topics,
                        user_id=user_id,
                        input=input_string,
                    )
                )
                log_debug("Memory updated")
                return "Memory updated successfully"
            except Exception as e:
                log_warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def delete_memory(memory_id: str) -> str:
            """Use this function to delete a single memory from the database.
            Args:
                memory_id (str): The id of the memory to be deleted.
            Returns:
                str: A message indicating if the memory was deleted successfully or not.
            """
            try:
                db.delete_user_memory(memory_id=memory_id, user_id=user_id)
                log_debug("Memory deleted")
                return "Memory deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting memory in db: {e}")
                return f"Error deleting memory: {e}"

        def clear_memory() -> str:
            """Use this function to remove all (or clear all) memories from the database.

            Returns:
                str: A message indicating if the memory was cleared successfully or not.
            """
            db.clear_memories()
            log_debug("Memory cleared")
            return "Memory cleared successfully"

        functions: List[Callable] = []
        if enable_add_memory:
            functions.append(add_memory)
        if enable_update_memory:
            functions.append(update_memory)
        if enable_delete_memory:
            functions.append(delete_memory)
        if enable_clear_memory:
            functions.append(clear_memory)
        return functions

    async def _aget_db_tools(
        self,
        user_id: str,
        db: Union[BaseDb, AsyncBaseDb],
        input_string: str,
        enable_add_memory: bool = True,
        enable_update_memory: bool = True,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        async def add_memory(memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to add a memory to the database.
            Args:
                memory (str): The memory to be added.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was added successfully or not.
            """
            from uuid import uuid4

            from agno.db.base import UserMemory

            try:
                memory_id = str(uuid4())
                if isinstance(db, AsyncBaseDb):
                    await db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            user_id=user_id,
                            agent_id=agent_id,
                            team_id=team_id,
                            memory=memory,
                            topics=topics,
                            input=input_string,
                        )
                    )
                else:
                    db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            user_id=user_id,
                            agent_id=agent_id,
                            team_id=team_id,
                            memory=memory,
                            topics=topics,
                            input=input_string,
                        )
                    )
                log_debug(f"Memory added: {memory_id}")
                return "Memory added successfully"
            except Exception as e:
                log_warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        async def update_memory(memory_id: str, memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to update an existing memory in the database.
            Args:
                memory_id (str): The id of the memory to be updated.
                memory (str): The updated memory.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was updated successfully or not.
            """
            from agno.db.base import UserMemory

            try:
                if isinstance(db, AsyncBaseDb):
                    await db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            memory=memory,
                            topics=topics,
                            input=input_string,
                        )
                    )
                else:
                    db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            memory=memory,
                            topics=topics,
                            input=input_string,
                        )
                    )
                log_debug("Memory updated")
                return "Memory updated successfully"
            except Exception as e:
                log_warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        async def delete_memory(memory_id: str) -> str:
            """Use this function to delete a single memory from the database.
            Args:
                memory_id (str): The id of the memory to be deleted.
            Returns:
                str: A message indicating if the memory was deleted successfully or not.
            """
            try:
                if isinstance(db, AsyncBaseDb):
                    await db.delete_user_memory(memory_id=memory_id)
                else:
                    db.delete_user_memory(memory_id=memory_id)
                log_debug("Memory deleted")
                return "Memory deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting memory in db: {e}")
                return f"Error deleting memory: {e}"

        async def clear_memory() -> str:
            """Use this function to remove all (or clear all) memories from the database.

            Returns:
                str: A message indicating if the memory was cleared successfully or not.
            """
            if isinstance(db, AsyncBaseDb):
                await db.clear_memories()
            else:
                db.clear_memories()
            log_debug("Memory cleared")
            return "Memory cleared successfully"

        functions: List[Callable] = []
        if enable_add_memory:
            functions.append(add_memory)
        if enable_update_memory:
            functions.append(update_memory)
        if enable_delete_memory:
            functions.append(delete_memory)
        if enable_clear_memory:
            functions.append(clear_memory)
        return functions
