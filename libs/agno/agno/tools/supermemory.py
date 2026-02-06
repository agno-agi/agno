import json
from os import getenv
from typing import Any, Dict, List, Optional, Union

from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from supermemory import Supermemory
except ImportError:
    raise ImportError("`supermemory` package not found. Please install it with `pip install supermemory`")


class SupermemoryTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        user_id: Optional[str] = None,
        search_limit: int = 5,
        threshold: Optional[float] = None,
        enable_add_memory: bool = True,
        enable_search_memory: bool = True,
        enable_get_user_profile: bool = True,
        enable_forget_memory: bool = True,
        all: bool = False,
        **kwargs,
    ):
        tools: List[Any] = []
        if enable_add_memory or all:
            tools.append(self.add_memory)
        if enable_search_memory or all:
            tools.append(self.search_memory)
        if enable_get_user_profile or all:
            tools.append(self.get_user_profile)
        if enable_forget_memory or all:
            tools.append(self.forget_memory)

        super().__init__(name="supermemory_tools", tools=tools, **kwargs)
        self.api_key = api_key or getenv("SUPERMEMORY_API_KEY")
        self.user_id = user_id
        self.search_limit = search_limit
        self.threshold = threshold
        self.client: Supermemory

        try:
            client_kwargs: Dict[str, Any] = {}
            if self.api_key:
                client_kwargs["api_key"] = self.api_key
            self.client = Supermemory(**client_kwargs)
            log_debug("Initialized Supermemory client.")
        except Exception as e:
            log_error(f"Failed to initialize Supermemory client: {e}")
            raise ConnectionError("Failed to initialize Supermemory client. Ensure SUPERMEMORY_API_KEY is set.") from e

    def _get_user_id(
        self,
        method_name: str,
        run_context: RunContext,
    ) -> str:
        """Resolve the user ID"""
        resolved_user_id = self.user_id
        if not resolved_user_id:
            try:
                resolved_user_id = run_context.user_id
            except Exception:
                pass
        if not resolved_user_id:
            error_msg = f"Error in {method_name}: A user_id must be provided."
            log_error(error_msg)
            return error_msg
        return resolved_user_id

    def add_memory(
        self,
        run_context: RunContext,
        content: str,
        metadata: Optional[Dict[str, Union[str, float, bool]]] = None,
    ) -> str:
        """Store content in the user's long-term memory. Supermemory will automatically extract
        and index relevant facts.

        Args:
            content(str): The text content to store. Can be a fact, conversation snippet, or any text.
                Example: "I live in NYC and work as a software engineer"
            metadata(Optional[Dict[str, Union[str, float, bool]]]): Optional key-value pairs for filtering.
                Example: {"category": "personal", "source": "conversation"}
        Returns:
            str: JSON-encoded response with document id and status, or an error message.
        """
        resolved_user_id = self._get_user_id("add_memory", run_context=run_context)
        if resolved_user_id.startswith("Error in "):
            return resolved_user_id
        try:
            kwargs: Dict[str, Any] = {
                "content": content,
                "container_tag": resolved_user_id,
            }
            if metadata:
                kwargs["metadata"] = metadata

            result = self.client.add(**kwargs)
            return json.dumps(result.model_dump())
        except Exception as e:
            log_error(f"Error adding memory: {e}")
            return f"Error adding memory: {e}"

    def search_memory(
        self,
        run_context: RunContext,
        query: str,
        limit: Optional[int] = None,
    ) -> str:
        """Search the user's stored memories using semantic search.

        Args:
            query(str): The search query to find relevant memories.
                Example: "What does the user do for work?"
            limit(Optional[int]): Maximum number of results to return.
        Returns:
            str: JSON-encoded list of matching memories with similarity scores, or an error message.
        """
        resolved_user_id = self._get_user_id("search_memory", run_context=run_context)
        if resolved_user_id.startswith("Error in "):
            return resolved_user_id
        try:
            kwargs: Dict[str, Any] = {
                "q": query,
                "container_tag": resolved_user_id,
                "limit": limit or self.search_limit,
            }
            if self.threshold is not None:
                kwargs["threshold"] = self.threshold

            result = self.client.search.memories(**kwargs)
            results_list = [r.model_dump() for r in result.results]
            return json.dumps(results_list)
        except Exception as e:
            log_error(f"Error searching memory: {e}")
            return f"Error searching memory: {e}"

    def get_user_profile(
        self,
        run_context: RunContext,
        query: Optional[str] = None,
    ) -> str:
        """Get the user's profile containing static facts and dynamic context.
        Optionally include a search query to also retrieve relevant memories.

        Args:
            query(Optional[str]): Optional search query to include relevant memories in the response.
                Example: "What are the user's food preferences?"
        Returns:
            str: JSON-encoded profile with static facts, dynamic context, and optional search results.
        """
        resolved_user_id = self._get_user_id("get_user_profile", run_context=run_context)
        if resolved_user_id.startswith("Error in "):
            return resolved_user_id
        try:
            kwargs: Dict[str, Any] = {
                "container_tag": resolved_user_id,
            }
            if query:
                kwargs["q"] = query
            if self.threshold is not None:
                kwargs["threshold"] = self.threshold

            result = self.client.profile(**kwargs)
            return json.dumps(result.model_dump())
        except Exception as e:
            log_error(f"Error getting user profile: {e}")
            return f"Error getting user profile: {e}"

    def forget_memory(
        self,
        run_context: RunContext,
        memory_id: Optional[str] = None,
        content: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> str:
        """Forget (soft-delete) a specific memory. Provide either the memory ID or the exact content.

        Args:
            memory_id(Optional[str]): The ID of the memory to forget (e.g. "mem_abc123").
            content(Optional[str]): The exact content of the memory to forget, if ID is unknown.
            reason(Optional[str]): Optional reason for forgetting the memory.
        Returns:
            str: JSON-encoded response confirming the memory was forgotten, or an error message.
        """
        resolved_user_id = self._get_user_id("forget_memory", run_context=run_context)
        if resolved_user_id.startswith("Error in "):
            return resolved_user_id
        if not memory_id and not content:
            return "Error: Either memory_id or content must be provided to forget a memory."
        try:
            kwargs: Dict[str, Any] = {
                "container_tag": resolved_user_id,
            }
            if memory_id:
                kwargs["id"] = memory_id
            if content:
                kwargs["content"] = content
            if reason:
                kwargs["reason"] = reason

            result = self.client.memories.forget(**kwargs)
            return json.dumps(result.model_dump())
        except Exception as e:
            log_error(f"Error forgetting memory: {e}")
            return f"Error forgetting memory: {e}"
