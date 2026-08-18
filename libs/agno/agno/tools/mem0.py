import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Union

from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from mem0.client.main import MemoryClient
    from mem0.memory.main import Memory
except ImportError:
    raise ImportError("`mem0ai` package not found. Please install it with `pip install mem0ai`")


class Mem0Tools(Toolkit):
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        host: Optional[str] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        infer: bool = True,
        add_memory: bool = True,
        search_memory: bool = True,
        get_all_memories: bool = True,
        delete_all_memories: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Mem0 memory toolkit.

        Args:
            config: Custom Mem0 config dict for self-hosted. Ignored if api_key set.
            api_key: Mem0 Platform API key. Defaults to MEM0_API_KEY env var.
            host: Mem0 Platform host URL. Defaults to MEM0_HOST env var.
            user_id: Default user ID for memory operations.
            org_id: Mem0 Platform organization ID. Defaults to MEM0_ORG_ID env var.
            project_id: Mem0 Platform project ID. Defaults to MEM0_PROJECT_ID env var.
            infer: Whether to use Mem0's inference when adding memories.
            add_memory: Enable the add_memory tool.
            search_memory: Enable the search_memory tool.
            get_all_memories: Enable the get_all_memories tool.
            delete_all_memories: Enable the delete_all_memories tool. Disabled by default (destructive).
            all: Enable all tools.
        """
        tools: List[Callable] = []
        if all or add_memory:
            tools.append(self.mem0_add_memory)
        if all or search_memory:
            tools.append(self.mem0_search_memory)
        if all or get_all_memories:
            tools.append(self.get_all_memories)
        if all or delete_all_memories:
            tools.append(self.delete_all_memories)

        super().__init__(name="mem0_tools", tools=tools, **kwargs)
        self.api_key = api_key or getenv("MEM0_API_KEY")
        self.host = host or getenv("MEM0_HOST")
        self.user_id = user_id
        self.org_id = org_id or getenv("MEM0_ORG_ID")
        self.project_id = project_id or getenv("MEM0_PROJECT_ID")
        self.client: Union[Memory, MemoryClient]
        self.infer = infer

        try:
            if self.api_key:
                log_debug("Using Mem0 Platform API key.")
                client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
                if self.host:
                    client_kwargs["host"] = self.host
                if self.org_id:
                    client_kwargs["org_id"] = self.org_id
                if self.project_id:
                    client_kwargs["project_id"] = self.project_id
                self.client = MemoryClient(**client_kwargs)
            elif config is not None:
                log_debug("Using Mem0 with config.")
                self.client = Memory.from_config(config)
            else:
                log_debug("Initializing Mem0 with default settings.")
                self.client = Memory()
        except Exception as e:
            log_error(f"Failed to initialize Mem0 client: {str(e)}")
            raise ConnectionError("Failed to initialize Mem0 client. Ensure API keys/config are set.") from e

    def _get_user_id(self, method_name: str, run_context: RunContext) -> str:
        """Resolve the user ID from toolkit default or run context."""
        resolved_user_id = self.user_id
        if not resolved_user_id:
            try:
                resolved_user_id = run_context.user_id
            except Exception:
                pass
        if not resolved_user_id:
            error_msg = f"Error in {method_name}: A user_id must be provided in the method call."
            log_error(error_msg)
            return error_msg
        return resolved_user_id

    def mem0_add_memory(
        self,
        run_context: RunContext,
        content: Union[str, Dict[str, str]],
    ) -> str:
        """Add facts to the user's memory.

        Args:
            run_context: The run context (auto-injected).
            content: Facts to store. Can be a string ("I live in NYC") or dict.

        Returns:
            JSON with Mem0 response or error.
        """

        resolved_user_id = self._get_user_id("add_memory", run_context=run_context)
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in add_memory:"):
            return json.dumps({"error": resolved_user_id})
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
            log_error(f"Error adding memory: {str(e)}")
            return json.dumps({"error": f"Error adding memory: {e}"})

    def mem0_search_memory(
        self,
        run_context: RunContext,
        query: str,
    ) -> str:
        """Semantic search across the user's stored memories.

        Args:
            run_context: The run context (auto-injected).
            query: Search query string.

        Returns:
            JSON list of matching memories.
        """

        resolved_user_id = self._get_user_id("search_memory", run_context=run_context)
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in search_memory:"):
            return json.dumps({"error": resolved_user_id})
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
            return json.dumps({"error": str(ve)})
        except Exception as e:
            log_error(f"Error searching memory: {str(e)}")
            return json.dumps({"error": f"Error searching memory: {e}"})

    def get_all_memories(self, run_context: RunContext) -> str:
        """Return all memories for the current user.

        Args:
            run_context: The run context (auto-injected).

        Returns:
            JSON list of all user memories.
        """

        resolved_user_id = self._get_user_id("get_all_memories", run_context=run_context)
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in get_all_memories:"):
            return json.dumps({"error": resolved_user_id})
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
            return json.dumps({"error": str(ve)})
        except Exception as e:
            log_error(f"Error getting all memories: {str(e)}")
            return json.dumps({"error": f"Error getting all memories: {e}"})

    def delete_all_memories(self, run_context: RunContext) -> str:
        """Delete all memories for the current user.

        Args:
            run_context: The run context (auto-injected).

        Returns:
            JSON with status and message on success.
        """

        resolved_user_id = self._get_user_id("delete_all_memories", run_context=run_context)
        if isinstance(resolved_user_id, str) and resolved_user_id.startswith("Error in delete_all_memories:"):
            error_msg = resolved_user_id
            log_error(error_msg)
            return json.dumps({"error": f"Error deleting all memories: {error_msg}"})
        try:
            self.client.delete_all(user_id=resolved_user_id)
            return json.dumps(
                {"status": "success", "message": f"Successfully deleted all memories for user_id: {resolved_user_id}"}
            )
        except Exception as e:
            log_error(f"Error deleting all memories: {str(e)}")
            return json.dumps({"error": f"Error deleting all memories: {e}"})
