import json
from os import getenv
from typing import Any, Dict, Optional, Union

from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from mem0 import (
        Memory,  # type: ignore
        MemoryClient,  # type: ignore
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
                self.get_all_memories,
                self.delete_all_memories,
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

    def _get_user_id(self, method_name: str, user_id: Optional[str] = None, agent: Any = None) -> str:
        """Gets the user ID from kwargs, defaults, or session_state, returning an error message if none found."""
        resolved_user_id = user_id or self.user_id
        if not resolved_user_id and agent is not None:
            try:
                session_state = getattr(agent, "session_state", None)
                if isinstance(session_state, dict):
                    resolved_user_id = session_state.get("current_user_id")
            except Exception:
                pass
        if not resolved_user_id:
            error_msg = f"Error in {method_name}: A user_id must be provided in the method call."
            log_error(error_msg)
            return error_msg
        return resolved_user_id

    def _get_run_id(self, agent: Any = None) -> Optional[str]:
        """Extracts the current session_id (run_id) from agent session state"""
        try:
            if agent is not None:
                session_state = getattr(agent, "session_state", None)
                if isinstance(session_state, dict):
                    return session_state.get("current_session_id")
        except Exception:
            pass
        return None

    def add_memory(
        self,
        messages: Any,
        agent: Any = None,
    ) -> str:
        """Adds information to the memory for a specific user. Requires user_id.
        Args:
            messages (Any): Data to add.
            agent (Any): Agent object to extract user_id from session_state
        Returns:
            str: JSON string of the result from Mem0, or an error message.
        """
        resolved_user_id = self._get_user_id("add_memory", agent=agent)
        # Early-return on missing user_id error
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in add_memory:"):
            return resolved_user_id
        try:
            # Extract run_id from agent session_state
            run_id = self._get_run_id(agent)
            log_debug(f"Adding memory for user_id: {resolved_user_id}, run_id: {run_id}")

            # Normalize messages into a list of {role, content} dicts
            if isinstance(messages, list):
                messages_list = messages
            else:
                # Convert message to string content; JSON-dump dicts
                if isinstance(messages, dict):
                    log_debug("Wrapping dict message into content string")
                    content = json.dumps(messages)
                else:
                    content = str(messages)
                messages_list = [{"role": "user", "content": content}]

            result = self.client.add(
                messages_list,
                user_id=resolved_user_id,
                run_id=run_id,
            )
            return json.dumps(result)
        except Exception as e:
            log_error(f"Error adding memory: {e}")
            return f"Error adding memory: {e}"

    def search_memory(
        self,
        query: str,
        agent: Any = None,
    ) -> str:
        """Searches the memory for a specific user
        Args:
            query (str): The search query.
            agent (Any): Agent object to extract user_id from session_state
        Returns:
            str: JSON string containing a list of relevant memories found, or an error message.
        """
        resolved_user_id = self._get_user_id("search_memory", agent=agent)
        # Early-return on missing user_id error
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in search_memory:"):
            return resolved_user_id
        try:
            # Search across all sessions for user-level memories
            results = self.client.search(
                query=query,
                user_id=resolved_user_id,
            )

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

    def get_all_memories(self, agent: Any = None) -> str:
        """Retrieves all memories for a specific user and session.
        Args:
            agent (Any): Agent object to extract user_id and session_id from session_state
        Returns:
            str: JSON string containing a list of all memories found, or an error message.
        """
        resolved_user_id = self._get_user_id("get_all_memories", agent=agent)
        # Early-return on missing user_id error
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in get_all_memories:"):
            return resolved_user_id
        try:
            # Retrieve all memories for the user across sessions
            results = self.client.get_all(
                user_id=resolved_user_id,
            )

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

    def delete_all_memories(self, agent: Any = None) -> str:
        """Deletes ALL memories associated with the specified user and session. Use with caution!

        Args:
            agent (Any): Agent object to extract user_id and session_id from session_state

        Returns:
            str: Confirmation message or error string.
        """
        resolved_user_id = self._get_user_id("delete_all_memories", agent=agent)
        # Early-return on missing user_id error with prefix
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in delete_all_memories:"):
            error_msg = resolved_user_id
            log_error(error_msg)
            return f"Error deleting all memories: {error_msg}"
        try:
            # Extract run_id from agent session_state
            run_id = self._get_run_id(agent)
            log_debug(f"Attempting to delete ALL memories for user_id: {resolved_user_id}, run_id: {run_id}")

            self.client.delete_all(user_id=resolved_user_id, run_id=run_id)
            return f"Successfully deleted all memories for user_id: {resolved_user_id}, run_id: {run_id}."
        except Exception as e:
            log_error(f"Error deleting all memories: {e}")
            return f"Error deleting all memories: {e}"
