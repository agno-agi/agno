from copy import deepcopy
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, cast

from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.memory.v2.schema import UserMemory
from agno.models.base import Model
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_warning


@dataclass
class MemoryManager:
    """Model for Memory Manager"""

    # Model used for memory management
    model: Optional[Model] = None

    # Provide the system message for the manager as a string. If not provided, a default prompt will be used.
    system_message: Optional[str] = None

    # Provide the memory capture instructions for the manager as a string. If not provided, a default prompt will be used.
    memory_capture_instructions: Optional[str] = None

    # Additional instructions for the manager
    additional_instructions: Optional[str] = None

    # Whether memories were created in the last run
    memories_updated: bool = False

    def __init__(
        self,
        model: Optional[Model] = None,
        system_message: Optional[str] = None,
        memory_capture_instructions: Optional[str] = None,
        additional_instructions: Optional[str] = None,
    ):
        self.model = model
        if self.model is not None and isinstance(self.model, str):
            raise ValueError("Model must be a Model object, not a string")
        self.system_message = system_message
        self.memory_capture_instructions = memory_capture_instructions
        self.additional_instructions = additional_instructions

    def add_tools_to_model(self, model: Model, tools: List[Callable]) -> None:
        model = cast(Model, model)
        model.reset_tools_and_functions()

        _tools_for_model = []
        _functions_for_model = {}

        for tool in tools:
            try:
                function_name = tool.__name__
                if function_name not in _functions_for_model:
                    func = Function.from_callable(tool, strict=True)  # type: ignore
                    func.strict = True
                    _functions_for_model[func.name] = func
                    _tools_for_model.append({"type": "function", "function": func.to_dict()})
                    log_debug(f"Added function {func.name}")
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

        # Set tools on the model
        model.set_tools(tools=_tools_for_model)
        # Set functions on the model
        model.set_functions(functions=_functions_for_model)

    def get_system_message(
        self,
        existing_memories: Optional[List[Dict[str, Any]]] = None,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
    ) -> Message:
        if self.system_message is not None:
            return Message(role="system", content=self.system_message)

        memory_capture_instructions = self.memory_capture_instructions or dedent("""\
            Memories should include details that could personalize ongoing interactions with the user, such as:
              - Personal facts: name, age, occupation, location, interests, preferences, etc.
              - Significant life events or experiences shared by the user
              - Important context about the user's current situation, challenges or goals
              - What the user likes or dislikes, their opinions, beliefs, values, etc.
              - Any other details that provide valuable insights into the user's personality, perspective or needs\
        """)

        # -*- Return a system message for the memory manager
        system_prompt_lines = [
            "You are a MemoryManager that is responsible for manging key information about the user. "
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
            "  1. Decide to make no changes.",
            "  2. Decide to add a new memory, using the `add_memory` tool.",
            "  3. Decide to update an existing memory, using the `update_memory` tool.",
        ]
        if enable_delete_memory:
            system_prompt_lines.append("  4. Decide to delete an existing memory, using the `delete_memory` tool.")
        if enable_clear_memory:
            system_prompt_lines.append("  5. Decide to clear all memories, using the `clear_memory` tool.")
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
        db: MemoryDb,
        delete_memories: bool = True,
        clear_memories: bool = True,
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
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(
                user_id, db, input_string, enable_delete_memory=delete_memories, enable_clear_memory=clear_memories
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories=existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(messages=messages_for_model)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    async def acreate_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryDb,
        delete_memories: bool = True,
        clear_memories: bool = True,
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
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(
                user_id, db, input_string, enable_delete_memory=delete_memories, enable_clear_memory=clear_memories
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories=existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(messages=messages_for_model)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    def run_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryDb,
        delete_memories: bool = True,
        clear_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(
                user_id, db, task, enable_delete_memory=delete_memories, enable_clear_memory=clear_memories
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories, enable_delete_memory=delete_memories, enable_clear_memory=clear_memories
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(messages=messages_for_model)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    async def arun_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryDb,
        delete_memories: bool = True,
        clear_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(
                user_id, db, task, enable_delete_memory=delete_memories, enable_clear_memory=clear_memories
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories, enable_delete_memory=delete_memories, enable_clear_memory=clear_memories
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(messages=messages_for_model)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    # -*- DB Functions
    def _get_db_tools(
        self,
        user_id: str,
        db: MemoryDb,
        input_string: str,
        enable_add_memory: bool = True,
        enable_update_memory: bool = True,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
    ) -> List[Callable]:
        from datetime import datetime

        def add_memory(memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to add a memory to the database.
            Args:
                memory (str): The memory to be added.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was added successfully or not.
            """
            from uuid import uuid4

            try:
                last_updated = datetime.now()
                memory_id = str(uuid4())
                db.upsert_memory(
                    MemoryRow(
                        id=memory_id,
                        user_id=user_id,
                        memory=UserMemory(
                            memory_id=memory_id,
                            memory=memory,
                            topics=topics,
                            last_updated=last_updated,
                            input=input_string,
                        ).to_dict(),
                        last_updated=last_updated,
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
            try:
                last_updated = datetime.now()
                db.upsert_memory(
                    MemoryRow(
                        id=memory_id,
                        user_id=user_id,
                        memory=UserMemory(
                            memory_id=memory_id,
                            memory=memory,
                            topics=topics,
                            last_updated=last_updated,
                            input=input_string,
                        ).to_dict(),
                        last_updated=last_updated,
                    )
                )
                log_debug("Memory updated")
                return "Memory updated successfully"
            except Exception as e:
                log_warning("Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def delete_memory(memory_id: str) -> str:
            """Use this function to delete a single memory from the database.
            Args:
                memory_id (str): The id of the memory to be deleted.
            Returns:
                str: A message indicating if the memory was deleted successfully or not.
            """
            try:
                db.delete_memory(memory_id=memory_id)
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
            db.clear()
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
