from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, cast

from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.memory.v2.schema import UserMemory
from agno.models.base import Model
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_info, log_warning

# class MemoryUpdate(BaseModel):
#     """Model for updates to the user's memory."""

#     memory: str = Field(
#         ...,
#         description="The user memory to be stored or updated.",
#     )
#     topics: Optional[List[str]] = Field(None, description="The topics of the memory.")
#     id: Optional[str] = Field(
#         None, description="The id of the memory to update. ONLY use if you want to update an existing memory."
#     )


# class MemoryUpdatesResponse(BaseModel):
#     """Model for updates to the user's memory."""

#     updates: List[MemoryUpdate] = Field(
#         ...,
#         description="The updates to the user's memory.",
#     )


@dataclass
class MemoryManager:
    """Model for Memory Manager"""

    model: Optional[Model] = None

    # Provide the system prompt for the manager as a string
    system_prompt: Optional[str] = None

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

    # def update_model(self) -> None:
    #     self.model = cast(Model, self.model)
    #     self.model.reset_tools_and_functions()

    #     if self.use_json_mode is not None and self.use_json_mode is True:
    #         self.model.response_format = {"type": "json_object"}

    #     elif self.model.supports_native_structured_outputs:
    #         self.model.response_format = MemoryUpdatesResponse
    #         self.model.structured_outputs = True

    #     elif self.model.supports_json_schema_outputs:
    #         self.model.response_format = {
    #             "type": "json_schema",
    #             "json_schema": {
    #                 "name": MemoryUpdatesResponse.__name__,
    #                 "schema": MemoryUpdatesResponse.model_json_schema(),
    #             },
    #         }
    #     else:
    #         self.model.response_format = {"type": "json_object"}

    # def get_update_memories_system_message(
    #     self, messages: List[Message], existing_memories: Optional[List[Dict[str, Any]]] = None
    # ) -> Message:
    #     if self.system_prompt is not None:
    #         return Message(role="system", content=self.system_prompt)
    #     self.model = cast(Model, self.model)

    #     # -*- Return a system message for the memory manager
    #     system_prompt_lines = [
    #         "Your task is to generate concise memories for the user's messages. "
    #         "You can also decide that no new memories are needed."
    #         "If you do create new memories, create one or more memories that captures the key information provided by the user, as if you were storing it for future reference. "
    #         "Each memory should be a brief, third-person statement that encapsulates the most important aspect of the user's input, without adding any extraneous information. "
    #         "Memories should include details that could personalize ongoing interactions with the user, such as:\n"
    #         "  - Personal facts: name, age, occupation, location, interests, preferences, etc.\n"
    #         "  - Significant life events or experiences shared by the user\n"
    #         "  - Important context about the user's current situation, challenges or goals\n"
    #         "  - What the user likes or dislikes, their opinions, beliefs, values, etc.\n"
    #         "  - Any other details that provide valuable insights into the user's personality, perspective or needs",
    #         "You will also be provided with a list of existing memories. You may:",
    #         "  1. Decide to make no changes to the existing memories.",
    #         "  2. Decide to add new memories.",
    #         "  3. Decide to update existing memories.",
    #     ]

    #     system_prompt_lines.append("<user_messages>")
    #     user_messages = []
    #     for message in messages:
    #         if message.role == "user":
    #             user_messages.append(message.get_content_string())
    #     system_prompt_lines.append("\n".join(user_messages))
    #     system_prompt_lines.append("</user_messages>")

    #     if existing_memories and len(existing_memories) > 0:
    #         system_prompt_lines.append("<existing_memories>")
    #         for existing_memory in existing_memories:
    #             system_prompt_lines.append(f"ID: {existing_memory['memory_id']}")
    #             system_prompt_lines.append(f"Memory: {existing_memory['memory']}")
    #             system_prompt_lines.append("\n")
    #         system_prompt_lines.append("</existing_memories>")

    #     if self.model.response_format == {"type": "json_object"}:
    #         system_prompt_lines.append(get_json_output_prompt(MemoryUpdatesResponse))  # type: ignore

    #     return Message(role="system", content="\n".join(system_prompt_lines))

    def get_system_message(
        self, existing_memories: Optional[List[Dict[str, Any]]] = None, messages: Optional[List[Message]] = None
    ) -> Message:
        # -*- Return a system message for the memory manager
        system_prompt_lines = [
            "Your task is to add, update, or delete memories based on the user's task."
            "You can also decide that no new memories or other changes are needed."
            "If you do create new memories, create one or more memories that captures the key information provided by the user, as if you were storing it for future reference."
            "Memories should be a brief, third-person statement that encapsulates the most important aspect of the user's input, without adding any extraneous information."
            "Don't make a single memory too long, but do create multiple memories if needed to capture all the information."
            "Memories should include details that could personalize ongoing interactions with the user, such as:"
            "  - Personal facts: name, age, occupation, location, interests, preferences, etc."
            "  - Significant life events or experiences shared by the user"
            "  - Important context about the user's current situation, challenges or goals"
            "  - What the user likes or dislikes, their opinions, beliefs, values, etc."
            "  - Any other details that provide valuable insights into the user's personality, perspective or needs",
            "You will also be provided with a list of existing memories. You may:",
            "  1. Decide to make no changes to the existing memories.",
            "  2. Decide to add a new memory using the `add_memory` tool.",
            "  3. Decide to update an existing memory using the `update_memory` tool.",
            "  4. Decide to delete an existing memory using the `delete_memory` tool.",
            "  5. Decide to clear all memories using the `clear_memory` tool. Use this with extreme caution, as it will remove all memories from the database.",
            "You can call multiple of these tools in a single response if needed.",
        ]

        if messages:
            system_prompt_lines.append("<user_messages>")
            user_messages = []
            for message in messages:
                if message.role == "user":
                    user_messages.append(message.get_content_string())
            system_prompt_lines.append("\n".join(user_messages))
            system_prompt_lines.append("</user_messages>")

        if existing_memories and len(existing_memories) > 0:
            system_prompt_lines.append("<existing_memories>")
            for existing_memory in existing_memories:
                system_prompt_lines.append(f"ID: {existing_memory['memory_id']}")
                system_prompt_lines.append(f"Memory: {existing_memory['memory']}")
                system_prompt_lines.append("\n")
            system_prompt_lines.append("</existing_memories>")

        return Message(role="system", content="\n".join(system_prompt_lines))

    def create_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryDb,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        if len(messages) == 1:
            input_string = messages[0].get_content_string()
        else:
            input_string = (
                f"[{', '.join([m.get_content_string() for m in messages if m.role == 'user' and m.content])}]"
            )

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(user_id, db, input_string, enable_delete_memory=False, enable_clear_memory=False),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(existing_memories, messages=messages),
            # For models that require a non-system message
            Message(role="user", content="Create or update memories based on the user's messages."),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(messages=messages_for_model)
        log_debug("MemoryManager End", center=True)

        return response.content

    async def acreate_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryDb,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        if len(messages) == 1:
            input_string = messages[0].get_content_string()
        else:
            input_string = (
                f"[{', '.join([m.get_content_string() for m in messages if m.role == 'user' and m.content])}]"
            )

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(user_id, db, input_string, enable_delete_memory=False, enable_clear_memory=False),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(existing_memories, messages=messages),
            # For models that require a non-system message
            Message(role="user", content="Create or update memories based on the user's messages."),
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(messages=messages_for_model)
        log_debug("MemoryManager End", center=True)

        return response.content

    def run_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryDb,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(model_copy, self._get_db_tools(user_id, db, task))

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(existing_memories),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(messages=messages_for_model)
        log_debug("MemoryManager End", center=True)

        return response.content

    async def arun_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryDb,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        log_debug("MemoryManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(model_copy, self._get_db_tools(user_id, db, task))

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(existing_memories),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(messages=messages_for_model)
        log_debug("MemoryManager End", center=True)

        return response.content

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
                topics (Optional[List[str]]): The topics of the memory.
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
                log_info(f"Memory added: {memory_id}")
                return "Memory added successfully"
            except Exception as e:
                log_warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def update_memory(memory_id: str, memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to update a memory in the database.
            Args:
                memory_id (str): The id of the memory to be updated.
                memory (str): The updated memory.
                topics (Optional[List[str]]): The topics of the memory.
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
                log_info(f"Memory updated")
                return "Memory updated successfully"
            except Exception as e:
                log_warning("Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def delete_memory(memory_id: str) -> str:
            """Use this function to delete a memory from the database.
            Args:
                memory_id (str): The id of the memory to be deleted.
            Returns:
                str: A message indicating if the memory was deleted successfully or not.
            """
            try:
                db.delete_memory(memory_id=memory_id)
                log_info("Memory deleted")
                return "Memory deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting memory in db: {e}")
                return f"Error deleting memory: {e}"

        def clear_memory() -> str:
            """Use this function to clear all memories from the database.
            Returns:
                str: A message indicating if the memory was cleared successfully or not.
            """
            db.clear()
            log_info("Memory cleared")
            return "Memory cleared successfully"

        functions = []
        if enable_add_memory:
            functions.append(add_memory)
        if enable_update_memory:
            functions.append(update_memory)
        if enable_delete_memory:
            functions.append(delete_memory)
        if enable_clear_memory:
            functions.append(clear_memory)
        return functions
