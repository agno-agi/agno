import json
from os import getenv
from typing import Any, Dict, Optional, Union

from agno.agent import Agent
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from mem0 import Memory, MemoryClient
except ImportError:
    raise ImportError("`mem0ai` package not found. Please install it with `pip install mem0ai`")


class Mem0Tools(Toolkit):
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        user_id: Optional[str] = None,
        infer: bool = True,
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
        self.infer = infer

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

    def _get_user_id(
        self,
        method_name: str,
        agent: Optional[Agent] = None,
    ) -> str:
        """Resolve the user ID"""
        resolved_user_id = self.user_id
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

    def add_memory(
        self,
        agent: Agent,
        content: Union[str, Dict[str, str]],
    ) -> str:
        """Add facts to the user's memory.
        Args:
            content(Union[str, Dict[str, str]]): The facts that should be stored.
            Example:
                content = "I live in NYC"
                content = {"Name": "John", "Age": 30, "Location": "New York"}
        Returns:
            str: JSON-encoded Mem0 response or an error message.
        """

        resolved_user_id = self._get_user_id("add_memory", agent=agent)
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in add_memory:"):
            return resolved_user_id
        try:
            if isinstance(content, dict):
                log_debug("Wrapping dict message into content string")
                content = json.dumps(content)
            elif not isinstance(content, str):
                content = str(content)
            messages_list = [{"role": "user", "content": content}]

            result = self.client.add(
                messages_list,
                user_id=resolved_user_id,
                infer=self.infer,
            )
            return json.dumps(result)
        except Exception as e:
            log_error(f"Error adding memory: {e}")
            return f"Error adding memory: {e}"

    def search_memory(
        self,
        agent: Agent,
        query: str,
    ) -> str:
        """Semantic search for *query* across the user's stored memories."""

        resolved_user_id = self._get_user_id("search_memory", agent=agent)
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in search_memory:"):
            return resolved_user_id
        try:
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

    def get_all_memories(self, agent: Agent) -> str:
        """Return **all** memories for the current user as a JSON string."""

        resolved_user_id = self._get_user_id("get_all_memories", agent=agent)
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in get_all_memories:"):
            return resolved_user_id
        try:
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

    def delete_all_memories(self, agent: Agent) -> str:
        """Delete *all* memories associated with the current user"""

        resolved_user_id = self._get_user_id("delete_all_memories", agent=agent)
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in delete_all_memories:"):
            error_msg = resolved_user_id
            log_error(error_msg)
            return f"Error deleting all memories: {error_msg}"
        try:
            self.client.delete_all(user_id=resolved_user_id)
            return f"Successfully deleted all memories for user_id: {resolved_user_id}."
        except Exception as e:
            log_error(f"Error deleting all memories: {e}")
            return f"Error deleting all memories: {e}"
