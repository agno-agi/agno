from typing import Any, Dict, List, Optional, cast

from pydantic import BaseModel, ConfigDict

from agno.memory.db import MemoryDb
from agno.memory.memory import Memory
from agno.memory.row import MemoryRow
from agno.models.base import Model
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_debug, logger


class MemoryManager(BaseModel):
    model: Optional[Model] = None
    user_id: Optional[str] = None
    limit: Optional[int] = None
    # Provide the system prompt for the manager as a string
    system_prompt: Optional[str] = None
    # Memory Database
    db: Optional[MemoryDb] = None

    # Do not set the input message here, it will be set by the run method
    input_message: Optional[str] = None
    _tools_for_model: Optional[List[Dict]] = None
    _functions_for_model: Optional[Dict[str, Function]] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def update_model(self) -> None:
        # Use the default Model (OpenAIChat) if no model is provided
        if self.model is None:
            try:
                from agno.models.openai import OpenAIChat
            except ModuleNotFoundError as e:
                logger.exception(e)
                logger.error(
                    "Agno uses `openai` as the default model provider. Please provide a `model` or install `openai`."
                )
                exit(1)
            self.model = OpenAIChat(id="gpt-4o")

    def determine_tools_for_model(self) -> None:
        if self._tools_for_model is None:
            self._tools_for_model = []
        if self._functions_for_model is None:
            self._functions_for_model = {}

        for tool in [
            self.add_memory,
            self.update_memory,
            self.delete_memory,
            self.clear_memory,
        ]:
            try:
                function_name = tool.__name__
                if function_name not in self._functions_for_model:
                    func = Function.from_callable(tool)  # type: ignore
                    self._functions_for_model[func.name] = func
                    self._tools_for_model.append({"type": "function", "function": func.to_dict()})
                    log_debug(f"Added function {func.name}")
            except Exception as e:
                logger.warning(f"Could not add function {tool}: {e}")

    def get_existing_memories(self) -> Optional[List[MemoryRow]]:
        if self.db is None:
            return None

        return self.db.read_memories(user_id=self.user_id, limit=self.limit)

    def add_memory(self, memory: str) -> str:
        """Use this function to add a memory to the database.
        Args:
            memory (str): The memory to be stored.
        Returns:
            str: A message indicating if the memory was added successfully or not.
        """
        try:
            if self.db:
                self.db.upsert_memory(
                    MemoryRow(user_id=self.user_id, memory=Memory(memory=memory, input=self.input_message).to_dict())
                )
            return "Memory added successfully"
        except Exception as e:
            logger.warning(f"Error storing memory in db: {e}")
            return f"Error adding memory: {e}"

    def delete_memory(self, id: str) -> str:
        """Use this function to delete a memory from the database.
        Args:
            id (str): The id of the memory to be deleted.
        Returns:
            str: A message indicating if the memory was deleted successfully or not.
        """
        try:
            if self.db:
                self.db.delete_memory(id=id)
            return "Memory deleted successfully"
        except Exception as e:
            logger.warning(f"Error deleting memory in db: {e}")
            return f"Error deleting memory: {e}"

    def update_memory(self, id: str, memory: str) -> str:
        """Use this function to update a memory in the database.
        Args:
            id (str): The id of the memory to be updated.
            memory (str): The updated memory.
        Returns:
            str: A message indicating if the memory was updated successfully or not.
        """
        try:
            if self.db:
                self.db.upsert_memory(
                    MemoryRow(
                        id=id, user_id=self.user_id, memory=Memory(memory=memory, input=self.input_message).to_dict()
                    )
                )
            return "Memory updated successfully"
        except Exception as e:
            logger.warning(f"Error updating memory in db: {e}")
            return f"Error updating memory: {e}"

    def clear_memory(self) -> str:
        """Use this function to clear all memories from the database.

        Returns:
            str: A message indicating if the memory was cleared successfully or not.
        """
        try:
            if self.db:
                self.db.clear()
            return "Memory cleared successfully"
        except Exception as e:
            logger.warning(f"Error clearing memory in db: {e}")
            return f"Error clearing memory: {e}"

    def get_system_message(self) -> Message:
        # -*- Return a system message for the memory manager
        system_prompt_lines = [
            "Your task is to generate a concise memory for the user's message. "
            "Create a memory that captures the key information provided by the user, as if you were storing it for future reference. "
            "The memory should be a brief, third-person statement that encapsulates the most important aspect of the user's input, without adding any extraneous details. "
            "This memory will be used to enhance the user's experience in subsequent conversations.",
            "You will also be provided with a list of existing memories. You may:",
            "  1. Add a new memory using the `add_memory` tool.",
            "  2. Update a memory using the `update_memory` tool.",
            "  3. Delete a memory using the `delete_memory` tool.",
            "  4. Clear all memories using the `clear_memory` tool. Use this with extreme caution, as it will remove all memories from the database.",
        ]
        existing_memories = self.get_existing_memories()
        if existing_memories and len(existing_memories) > 0:
            system_prompt_lines.extend(
                [
                    "\nExisting memories:",
                    "<existing_memories>\n"
                    + "\n".join([f"  - id: {m.id} | memory: {m.memory}" for m in existing_memories])
                    + "\n</existing_memories>",
                ]
            )
        return Message(role="system", content="\n".join(system_prompt_lines))

    def run(
        self,
        message: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        log_debug("*********** MemoryManager Start ***********")

        # Update the Model (set defaults, add logit etc.)
        self.update_model()
        self.determine_tools_for_model()

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [self.get_system_message()]

        # Add the user prompt message
        user_prompt_message = Message(role="user", content=message, **kwargs) if message else None
        if user_prompt_message is not None:
            messages_for_model += [user_prompt_message]

        # Set input message added with the memory
        self.input_message = message

        # Generate a response from the Model (includes running function calls)
        self.model = cast(Model, self.model)
        response = self.model.response(
            messages=messages_for_model, tools=self._tools_for_model, functions=self._functions_for_model
        )
        log_debug("*********** MemoryManager End ***********")
        return response.content

    async def arun(
        self,
        message: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        log_debug("*********** Async MemoryManager Start ***********")

        # Update the Model (set defaults, add logit etc.)
        self.update_model()

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [self.get_system_message()]
        # Add the user prompt message
        user_prompt_message = Message(role="user", content=message, **kwargs) if message else None
        if user_prompt_message is not None:
            messages_for_model += [user_prompt_message]

        # Set input message added with the memory
        self.input_message = message

        # Generate a response from the Model (includes running function calls)
        self.model = cast(Model, self.model)
        response = await self.model.aresponse(
            messages=messages_for_model, tools=self._tools_for_model, functions=self._functions_for_model
        )
        log_debug("*********** Async MemoryManager End ***********")
        return response.content
