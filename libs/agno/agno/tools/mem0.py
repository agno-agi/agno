import json
from os import getenv
from typing import Any, Dict, Optional, Union

from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from mem0 import (
        Memory,
        MemoryClient,
    )
except ImportError:
    raise ImportError("`mem0ai` package not found. Please install it with `pip install mem0ai`")


class Mem0Toolkit(Toolkit):
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            name="mem0_tools",
            tools=[
                self.add_memory,
                self.search_memory,
                self.get_memory,
                self.update_memory,
                self.delete_memory,
                self.get_all_memories,
                self.delete_all_memories,
                self.get_memory_history,
            ],
            **kwargs,
        )
        self.api_key = api_key or getenv("MEM0_API_KEY")
        self.user_id = user_id
        self.client: Union[Memory, MemoryClient]

        try:
            if self.api_key:
                log_debug("Using Mem0 Platform API key.")
                self.client = MemoryClient(api_key=self.api_key)
            elif config is not None:
                log_debug("Using Mem0 with config.")
                self.client = Memory.from_config(config)
            else:
                log_debug("Initializing Mem0 with default settings.")
                self.client = Memory()
        except Exception as e:
            log_error(f"Failed to initialize Mem0 client: {e}")
            raise ConnectionError("Failed to initialize Mem0 client. Ensure API keys/config are set.") from e

    def _get_user_id(self, method_name: str, user_id: Optional[str] = None) -> str:
        """Gets the user ID from kwargs or defaults, raising ValueError if none found."""
        resolved_user_id = user_id or self.user_id

        if not resolved_user_id:
            error_msg = f"Error in {method_name}: A user_id must be provided in the method call."
            log_error(error_msg)
            raise ValueError(error_msg)
        return resolved_user_id

    def add_memory(
        self,
        messages: Any,
        user_id: Optional[str] = None,
    ) -> str:
        """Adds information to the memory for a specific user. Requires user_id.
        Args:
            messages (Any): Data to add.
            user_id (Optional[str]): User ID to associate the memory with
        Returns:
            str: JSON string of the result from Mem0, or an error message.
        """
        try:
            resolved_user_id = self._get_user_id("add_memory", user_id)
            log_debug(f"Adding memory for user_id: {resolved_user_id}")

            if isinstance(messages, dict):
                messages_list = [messages]
            elif isinstance(messages, list):
                messages_list = messages
            elif isinstance(messages, str):
                messages_list = [{"role": "user", "content": messages}]
            else:
                log_error(f"Invalid type for messages: {type(messages)}. Expected str, dict, or list of dicts.")
                return "Error: Invalid input type for messages. Expected str, dict, or list of dicts."

            result = self.client.add(
                messages_list,
                user_id=resolved_user_id,
            )
            return json.dumps(result)
        except Exception as e:
            log_error(f"Error adding memory: {e}")
            return f"Error adding memory: {e}"

    def search_memory(
        self,
        query: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Searches the memory for a specific user
        Args:
            query (str): The search query.
            user_id (Optional[str]): Filter results by user ID
        Returns:
            str: JSON string containing a list of relevant memories found, or an error message.
        """
        try:
            resolved_user_id = self._get_user_id("search_memory", user_id)
            log_debug(f"Searching memory for user_id: {resolved_user_id} with query '{query}'")

            results = self.client.search(query=query, user_id=resolved_user_id)

            if isinstance(results, dict) and "results" in results:
                search_results_list = results.get("results", [])
            elif isinstance(results, list):
                search_results_list = results
            else:
                log_warning(f"Unexpected return type from mem0.search: {type(results)}. Returning empty list.")
                search_results_list = []

            return json.dumps(search_results_list)
        except ValueError as ve:
            log_error(str(ve))
            return str(ve)
        except Exception as e:
            log_error(f"Error searching memory: {e}")
            return f"Error searching memory: {e}"

    def get_memory(self, memory_id: str) -> str:
        """Retrieves a specific memory entry by its unique ID.

        Args:
            memory_id (str): The ID of the memory to retrieve.

        Returns:
            str: JSON string containing the details of the retrieved memory, or an error message.
        """
        try:
            log_debug(f"Getting memory with ID: {memory_id}")
            result = self.client.get(memory_id=memory_id)
            if result:
                return json.dumps(result)
            else:
                not_found_msg = f"Memory with ID '{memory_id}' not found."
                log_warning(not_found_msg)
                return not_found_msg
        except Exception as e:
            log_error(f"Error getting memory {memory_id}: {e}")
            return f"Error getting memory {memory_id}: {e}"

    def update_memory(self, memory_id: str, data: str) -> str:
        """Updates an existing memory entry.

        Args:
            memory_id (str): The ID of the memory to update.
            data (str): The new data/content for the memory.

        Returns:
            str: Confirmation message or error string.
        """
        try:
            log_debug(f"Updating memory with ID: {memory_id}")
            result = self.client.update(memory_id=memory_id, data=data)
            return (
                json.dumps(result)
                if result is not None
                else f"Memory {memory_id} updated successfully (no detailed response)."
            )
        except Exception as e:
            log_error(f"Error updating memory {memory_id}: {e}")
            return f"Error updating memory {memory_id}: {e}"

    def delete_memory(self, memory_id: str) -> str:
        """Deletes a specific memory entry by its unique ID.

        Args:
            memory_id (str): The ID of the memory to delete.

        Returns:
            str: Confirmation message indicating success or failure.
        """
        try:
            log_debug(f"Deleting memory with ID: {memory_id}")
            self.client.delete(memory_id=memory_id)
            return f"Memory with ID '{memory_id}' deleted successfully."
        except Exception as e:
            log_error(f"Error deleting memory {memory_id}: {e}")
            return f"Error deleting memory {memory_id}: {e}"

    def get_memory_history(self, memory_id: str) -> str:
        """Retrieves the modification history of a specific memory entry.

        Args:
            memory_id (str): The ID of the memory to retrieve history for.

        Returns:
            str: JSON string containing the list of history events, or an error message.
        """
        try:
            log_debug(f"Getting history for memory ID: {memory_id}")
            result = self.client.history(memory_id=memory_id)
            return json.dumps(result)
        except Exception as e:
            log_error(f"Error getting history for memory {memory_id}: {e}")
            return f"Error getting history for memory {memory_id}: {e}"

    def get_all_memories(self, user_id: Optional[str] = None, limit: int = 100) -> str:
        """Retrieves all memories for a specific user. Requires user_id.
        Args:
            user_id (Optional[str]): Filter by User ID
        Returns:
            str: JSON string containing a list of all memories found, or an error message.
        """
        try:
            resolved_user_id = self._get_user_id("get_all_memories", user_id)
            log_debug(f"Getting all memories for user_id: {resolved_user_id}, limit: {limit}")

            results = self.client.get_all(user_id=resolved_user_id)

            if isinstance(results, dict) and "results" in results:
                memories_list = results.get("results", [])
            elif isinstance(results, list):
                memories_list = results
            else:
                log_warning(f"Unexpected return type from mem0.get_all: {type(results)}. Returning empty list.")
                memories_list = []
            return json.dumps(memories_list)
        except ValueError as ve:
            log_error(str(ve))
            return str(ve)
        except Exception as e:
            log_error(f"Error getting all memories: {e}")
            return f"Error getting all memories: {e}"

    def delete_all_memories(
        self,
        user_id: Optional[str] = None,
    ) -> str:
        """Deletes ALL memories associated with the specified user. Requires user_id. Use with caution!

        Args:
            user_id: Delete memories for this User ID

        Returns:
            str: Confirmation message or error string.
        """
        try:
            resolved_user_id = self._get_user_id("delete_all_memories", user_id)
            log_debug(f"Attempting to delete ALL memories associated with user_id: {resolved_user_id}")

            self.client.delete_all(user_id=resolved_user_id)
            return f"Successfully deleted all memories associated with user_id: {resolved_user_id}."
        except Exception as e:
            log_error(f"Error deleting all memories: {e}")
            return f"Error deleting all memories: {e}"
