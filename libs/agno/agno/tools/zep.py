import json
import uuid
from os import getenv
from textwrap import dedent
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from zep_cloud import (
        BadRequestError,
        NotFoundError,
    )
    from zep_cloud import (
        Message as ZepMessage,
    )
    from zep_cloud.client import AsyncZep, Zep
except ImportError:
    raise ImportError("`zep-cloud` package not found. Please install it with `pip install zep-cloud`")

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to the users memories stored in Zep. You can interact with them using the following tools:
    - `add_message`: Add a message to the Zep session memory.
    - `get_memory`: Get the memory for the current Zep session.
    - `search_memory`: Search the Zep user graph for relevant facts.

    Guidelines:
    - Use `add_message` tool to add relevant messages to the users memories. You can use this tool multiple times to add multiple messages.
    - Use `get_memory` tool to get the memory for the current Zep session for additional context. This will give you the entire context of the user's memories with relevant facts.
    - Use `search_memory` tool to search the Zep user memories for relevant facts. This will give you a list of relevant facts.
    """
)


class ZepTools(Toolkit):
    """Toolkit for managing Zep memory with knowledge graph search.

    Args:
        session_id: Zep session ID. Auto-generated if not provided.
        user_id: Zep user ID. Auto-generated if not provided.
        api_key: Zep API key. Falls back to ZEP_API_KEY env var.
        ignore_assistant_messages: Ignore assistant role messages. Defaults to False.
        add_message: Enable add_message tool. Defaults to False (writes to memory).
        get_memory: Enable get_memory tool. Defaults to True.
        search_memory: Enable search_memory tool. Defaults to True.
        instructions: Custom instructions for the toolkit.
        add_instructions: Add instructions to agent. Defaults to False.
        all: Enable all tools. Defaults to False.
    """

    # Agno 2.x kwarg names accepted for backwards compatibility
    _legacy_param_aliases = {
        "enable_add_zep_message": "add_message",
        "enable_get_zep_memory": "get_memory",
        "enable_search_zep_memory": "search_memory",
    }

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        ignore_assistant_messages: bool = False,
        add_message: bool = False,
        get_memory: bool = True,
        search_memory: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self._api_key = api_key or getenv("ZEP_API_KEY")
        if not self._api_key:
            raise ValueError(
                "No Zep API key provided. Please set the ZEP_API_KEY environment variable or pass it to the ZepTools constructor."
            )

        if instructions is None:
            self.instructions = "<Memory Instructions>\n" + DEFAULT_INSTRUCTIONS + "\n</Memory Instructions>"
        else:
            self.instructions = instructions

        self.zep_client: Optional[Zep] = None
        self._initialized = False

        self.session_id_provided = session_id
        self.user_id_provided = user_id
        self.ignore_assistant_messages = ignore_assistant_messages

        self.session_id: Optional[str] = None
        self.user_id: Optional[str] = None

        self.initialize()

        tools: List[Callable] = []
        if all or add_message:
            tools.append(self.add_message)
        if all or get_memory:
            tools.append(self.get_memory)
        if all or search_memory:
            tools.append(self.search_memory)

        super().__init__(
            name="zep_tools", instructions=self.instructions, add_instructions=add_instructions, tools=tools, **kwargs
        )

    def initialize(self) -> bool:
        """
        Initialize the Zep client and ensure session/user setup.
        """
        if self._initialized:
            return True

        try:
            self.zep_client = Zep(api_key=self._api_key)

            # Handle session_id generation/validation
            self.session_id = self.session_id_provided
            if not self.session_id:
                self.session_id = f"{uuid.uuid4()}"
                log_debug(f"Generated new session ID: {self.session_id}")

            # Handle user_id generation/validation and Zep user check/creation
            self.user_id = self.user_id_provided
            if not self.user_id:
                self.user_id = f"user-{uuid.uuid4()}"
                log_debug(f"Creating new default Zep user: {self.user_id}")
                self.zep_client.user.add(user_id=self.user_id)  # type: ignore
            else:
                try:
                    self.zep_client.user.get(self.user_id)  # type: ignore
                    log_debug(f"Confirmed provided Zep user exists: {self.user_id}")
                except NotFoundError:
                    try:
                        self.zep_client.user.add(user_id=self.user_id)  # type: ignore
                    except BadRequestError as e:
                        log_error(f"Failed to create provided user {self.user_id}: {str(e)}")
                        self.zep_client = None  # Reset client on failure
                        return False  # Initialization failed

            # Create session associated with the user
            try:
                self.zep_client.thread.create(thread_id=self.session_id, user_id=self.user_id)  # type: ignore
                log_debug(f"Created session {self.session_id} for user {self.user_id}")
            except Exception as e:
                log_debug(f"Session may already exist: {e}")

            self._initialized = True
            return True

        except Exception as e:
            log_error(f"Failed to initialize ZepTools: {str(e)}")
            self.zep_client = None
            self._initialized = False
            return False

    def add_message(self, role: str, content: str) -> str:
        """Add a message to the current Zep session memory.

        Args:
            role: The role of the message sender (e.g., 'user', 'assistant', 'system').
            content: The text content of the message.

        Returns:
            JSON with confirmation or error.
        """
        if not self.zep_client or not self.session_id:
            log_error("Zep client or session ID not initialized. Cannot add message.")
            return json.dumps({"error": "Zep client/session not initialized."})

        try:
            zep_message = ZepMessage(
                role=role,
                content=content,
            )

            # Prepare ignore_roles if needed
            ignore_roles_list = ["assistant"] if self.ignore_assistant_messages else None

            # Add message to Zep memory
            self.zep_client.thread.add_messages(  # type: ignore
                thread_id=self.session_id,
                messages=[zep_message],
                ignore_roles=ignore_roles_list,
            )
            return json.dumps(
                {"ok": True, "message": f"Message from '{role}' added successfully to session {self.session_id}."}
            )
        except Exception as e:
            error_msg = f"Failed to add message to Zep session {self.session_id}: {e}"
            log_error(error_msg)
            return json.dumps({"error": f"Error adding message: {e}"})

    def get_memory(self, memory_type: str = "context") -> str:
        """Retrieve memory for the current Zep session.

        Args:
            memory_type: The type of memory to retrieve ('context', 'messages').

        Returns:
            JSON with the requested memory content or error.
        """
        if not self.zep_client or not self.session_id:
            log_error("Zep client or session ID not initialized. Cannot get memory.")
            return json.dumps({"error": "Zep client/session not initialized."})

        try:
            log_debug(f"Getting Zep memory for session {self.session_id}")

            if memory_type == "context":
                # Ensure context is a string
                user_context = self.zep_client.thread.get_user_context(thread_id=self.session_id, mode="basic")  # type: ignore
                log_debug(f"Memory data: {user_context}")
                return json.dumps({"context": user_context.context or "No context available."})
            elif memory_type == "messages":
                messages_list = self.zep_client.thread.get(thread_id=self.session_id)  # type: ignore
                # Ensure messages string representation is returned
                return json.dumps(
                    {"messages": str(messages_list.messages) if messages_list.messages else "No messages available."}
                )
            else:
                warning_msg = f"Unsupported memory_type requested: {memory_type}. Returning empty string."
                log_warning(warning_msg)
                return json.dumps({"error": warning_msg})

        except Exception as e:
            log_error(f"Failed to get Zep memory for session {self.session_id}: {str(e)}")
            return json.dumps({"error": f"Error getting memory for session {self.session_id}"})

    def search_memory(self, query: str, scope: str = "edges", limit: int = 5) -> str:
        """Search the Zep knowledge graph for relevant facts or nodes.

        Args:
            query: The search term to find relevant facts or nodes.
            scope: The scope of the search. Can be "edges" (for facts) or "nodes".
            limit: The maximum number of results to return.

        Returns:
            JSON with matching facts or nodes.
        """
        if not self.zep_client or not self.user_id:
            log_error("Zep client or user ID not initialized. Cannot search graph.")
            return json.dumps({"error": "Zep client/user not initialized."})

        try:
            search_response = self.zep_client.graph.search(
                query=query,
                user_id=self.user_id,
                scope=scope,
                limit=limit,
            )

            if scope == "edges" and search_response.edges:
                # Return facts from edges
                facts = [edge.fact for edge in search_response.edges]
                return json.dumps({"count": len(facts), "facts": facts})
            elif scope == "nodes" and search_response.nodes:
                nodes = [{"name": node.name, "summary": node.summary} for node in search_response.nodes]
                return json.dumps({"count": len(nodes), "nodes": nodes})
            else:
                return json.dumps({"error": f"No {scope} found for query: {query}"})

        except Exception as e:
            log_error(f"Failed to search Zep graph for user {self.user_id}: {str(e)}")
            return json.dumps({"error": f"Error searching graph: {e}"})


class ZepAsyncTools(Toolkit):
    """Async toolkit for managing Zep memory with knowledge graph search.

    Args:
        session_id: Zep session ID. Auto-generated if not provided.
        user_id: Zep user ID. Auto-generated if not provided.
        api_key: Zep API key. Falls back to ZEP_API_KEY env var.
        ignore_assistant_messages: Ignore assistant role messages. Defaults to False.
        add_message: Enable add_message tool. Defaults to False (writes to memory).
        get_memory: Enable get_memory tool. Defaults to True.
        search_memory: Enable search_memory tool. Defaults to True.
        instructions: Custom instructions for the toolkit.
        add_instructions: Add instructions to agent. Defaults to False.
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        ignore_assistant_messages: bool = False,
        add_message: bool = False,
        get_memory: bool = True,
        search_memory: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self._api_key = api_key or getenv("ZEP_API_KEY")
        if not self._api_key:
            raise ValueError(
                "No Zep API key provided. Please set the ZEP_API_KEY environment variable or pass it to the ZepTools constructor."
            )

        if instructions is None:
            self.instructions = "<Memory Instructions>\n" + DEFAULT_INSTRUCTIONS + "\n</Memory Instructions>"
        else:
            self.instructions = instructions

        self.zep_client: Optional[AsyncZep] = None
        self._initialized = False

        self.session_id_provided = session_id
        self.user_id_provided = user_id
        self.ignore_assistant_messages = ignore_assistant_messages

        self.session_id: Optional[str] = None
        self.user_id: Optional[str] = None

        self._initialized = False

        tools: List[Callable] = []
        if all or add_message:
            tools.append(self.add_message)
        if all or get_memory:
            tools.append(self.get_memory)  # type: ignore
        if all or search_memory:
            tools.append(self.search_memory)  # type: ignore

        super().__init__(
            name="zep_async_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            **kwargs,
        )

    async def initialize(self) -> bool:
        """
        Initialize the AsyncZep client and ensure session/user setup.
        """
        if self._initialized:
            return True

        try:
            self.zep_client = AsyncZep(api_key=self._api_key)

            # Handle session_id generation/validation
            self.session_id = self.session_id_provided
            if not self.session_id:
                self.session_id = f"{uuid.uuid4()}"
                log_debug(f"Generated new session ID: {self.session_id}")

            # Handle user_id generation/validation and Zep user check/creation
            self.user_id = self.user_id_provided
            if not self.user_id:
                self.user_id = f"user-{uuid.uuid4()}"
                log_debug(f"Creating new default Zep user: {self.user_id}")
                await self.zep_client.user.add(user_id=self.user_id)  # type: ignore
            else:
                try:
                    await self.zep_client.user.get(self.user_id)  # type: ignore
                    log_debug(f"Confirmed provided Zep user exists: {self.user_id}")
                except NotFoundError:
                    try:
                        await self.zep_client.user.add(user_id=self.user_id)  # type: ignore
                    except BadRequestError as e:
                        log_error(f"Failed to create provided user {self.user_id}: {str(e)}")
                        self.zep_client = None  # Reset client on failure
                        return False  # Initialization failed

            # Create session associated with the user
            try:
                await self.zep_client.thread.create(thread_id=self.session_id, user_id=self.user_id)  # type: ignore
                log_debug(f"Created session {self.session_id} for user {self.user_id}")
            except Exception as e:
                log_debug(f"Session may already exist: {e}")

            self._initialized = True
            return True

        except Exception as e:
            log_error(f"Failed to initialize ZepTools: {str(e)}")
            self.zep_client = None
            self._initialized = False
            return False

    async def add_message(self, role: str, content: str) -> str:
        """Add a message to the current Zep session memory.

        Args:
            role: The role of the message sender (e.g., 'user', 'assistant', 'system').
            content: The text content of the message.

        Returns:
            JSON with confirmation or error.
        """
        if not self._initialized:
            await self.initialize()

        if not self.zep_client or not self.session_id:
            log_error("Zep client or session ID not initialized. Cannot add message.")
            return json.dumps({"error": "Zep client/session not initialized."})

        try:
            zep_message = ZepMessage(
                role=role,
                content=content,
            )

            # Prepare ignore_roles if needed
            ignore_roles_list = ["assistant"] if self.ignore_assistant_messages else None

            # Add message to Zep memory
            await self.zep_client.thread.add_messages(  # type: ignore
                thread_id=self.session_id,
                messages=[zep_message],
                ignore_roles=ignore_roles_list,
            )
            return json.dumps(
                {"ok": True, "message": f"Message from '{role}' added successfully to session {self.session_id}."}
            )
        except Exception as e:
            error_msg = f"Failed to add message to Zep session {self.session_id}: {e}"
            log_error(error_msg)
            return json.dumps({"error": f"Error adding message: {e}"})

    async def get_memory(self, memory_type: str = "context") -> str:
        """Retrieve memory for the current Zep session.

        Args:
            memory_type: The type of memory to retrieve ('context', 'messages').

        Returns:
            JSON with the requested memory content or error.
        """
        if not self._initialized:
            await self.initialize()

        if not self.zep_client or not self.session_id:
            log_error("Zep client or session ID not initialized. Cannot get memory.")
            return json.dumps({"error": "Zep client/session not initialized."})

        try:
            if memory_type == "context":
                # Ensure context is a string
                user_context = await self.zep_client.thread.get_user_context(thread_id=self.session_id, mode="basic")  # type: ignore
                log_debug(f"Memory data: {user_context}")
                return json.dumps({"context": user_context.context or "No context available."})
            elif memory_type == "messages":
                # Ensure messages string representation is returned
                messages_list = await self.zep_client.thread.get(thread_id=self.session_id)  # type: ignore
                return json.dumps(
                    {"messages": str(messages_list.messages) if messages_list.messages else "No messages available."}
                )
            else:
                warning_msg = f"Unsupported memory_type requested: {memory_type}. Returning context."
                log_warning(warning_msg)
                return json.dumps({"error": warning_msg})

        except Exception as e:
            error_msg = f"Failed to get Zep memory for session {self.session_id}: {e}"
            log_error(error_msg)
            return json.dumps({"error": f"Error getting memory: {e}"})

    async def search_memory(self, query: str, scope: str = "edges", limit: int = 5) -> str:
        """Search the Zep knowledge graph for relevant facts or nodes.

        Args:
            query: The search term to find relevant facts or nodes.
            scope: The scope of the search. Can be "edges" (for facts) or "nodes".
            limit: The maximum number of results to return.

        Returns:
            JSON with matching facts or nodes.
        """
        if not self._initialized:
            await self.initialize()

        if not self.zep_client or not self.user_id:
            log_error("Zep client or user ID not initialized. Cannot search graph.")
            return json.dumps({"error": "Zep client/user not initialized."})

        try:
            search_response = await self.zep_client.graph.search(  # type: ignore
                query=query,
                user_id=self.user_id,
                scope=scope,  # Can be "edges" or "nodes"
                limit=limit,
            )

            if scope == "edges" and search_response.edges:
                # Return facts from edges
                facts = [edge.fact for edge in search_response.edges]
                return json.dumps({"count": len(facts), "facts": facts})
            elif scope == "nodes" and search_response.nodes:
                # Return node summaries
                nodes = [{"name": node.name, "summary": node.summary} for node in search_response.nodes]
                return json.dumps({"count": len(nodes), "nodes": nodes})
            else:
                return json.dumps({"error": f"No {scope} found for query: {query}"})

        except Exception as e:
            log_error(f"Failed to search Zep graph for user {self.user_id}: {str(e)}")
            return json.dumps({"error": f"Error searching graph: {e}"})
