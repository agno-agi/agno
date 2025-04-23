import uuid
from os import getenv
from textwrap import dedent
from typing import List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from zep_cloud import BadRequestError, NotFoundError
    from zep_cloud.client import AsyncZep, Zep
    from zep_cloud.types import MemorySearchResult
    from zep_cloud.types import Message as ZepMessage
except ImportError:
    raise ImportError("`zep-cloud` package not found. Please install it with `pip install zep-cloud`")

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to the users memories stored in Zep. You can interact with them using the following tools:
    - `add_zep_message`: Add a message to the Zep session memory. Use this to add messages to the Zep session memory.
    - `get_zep_memory`: Get the memory for the current Zep session. Use this to get the memory for the current Zep session.
    - `search_zep_memory`: Search the Zep user graph for relevant facts. Use this to search the Zep user graph for relevant facts.

    Guidelines:
    - Use `add_zep_message` tool to add relevant messages to the users memories. You can use this tool multiple times to add multiple messages.
    - Use `get_zep_memory` tool to get the memory for the current Zep session for additional context. This will give you a summary of the users memories.
    - Use `search_zep_memory` tool to search the Zep user memories for relevant facts. This will give you a list of relevant facts.
    """
)


class ZepTools(Toolkit):
    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        ignore_assistant_messages: bool = False,
        add_zep_message: bool = True,
        get_zep_memory: bool = True,
        search_zep_memory: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        **kwargs,
    ):
        super().__init__(name="zep_tools", instructions=instructions, add_instructions=add_instructions, **kwargs)

        self._api_key = api_key or getenv("ZEP_API_KEY")
        if not self._api_key:
            raise ValueError(
                "No Zep API key provided. Please set the ZEP_API_KEY environment variable or pass it to the ZepTools constructor."
            )

        if instructions is None:
            self.instructions = "<Memory Instructions>\n" + DEFAULT_INSTRUCTIONS + "\n</Memory Instructions>"

        self.zep_client: Optional[Zep] = None
        self._initialized = False

        self.session_id_provided = session_id
        self.user_id_provided = user_id
        self.ignore_assistant_messages = ignore_assistant_messages

        self.session_id: Optional[str] = None
        self.user_id: Optional[str] = None

        self.initialize()

        # Register methods as tools conditionally
        if add_zep_message:
            self.register(self.add_zep_message)
        if get_zep_memory:
            self.register(self.get_zep_memory)
        if search_zep_memory:
            self.register(self.search_zep_memory)

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
                    except BadRequestError as add_err:
                        log_error(f"Failed to create provided user {self.user_id}: {add_err}")
                        self.zep_client = None  # Reset client on failure
                        return False  # Initialization failed

            self._initialized = True
            return True

        except Exception as e:
            log_error(f"Failed to initialize ZepTools: {e}")
            self.zep_client = None
            self._initialized = False
            return False

    def add_zep_message(self, role: str, content: str) -> str:
        """
        Adds a message to the current Zep session memory.
        Args:
            role (str): The role of the message sender (e.g., 'user', 'assistant', 'system').
            content (str): The text content of the message.

        Returns:
            A confirmation message or an error string.
        """
        if not self.zep_client or not self.session_id:
            log_error("Zep client or session ID not initialized. Cannot add message.")
            return "Error: Zep client/session not initialized."

        try:
            zep_message = ZepMessage(
                role_type=role,
                content=content,
            )

            # Prepare ignore_roles if needed
            ignore_roles_list = ["assistant"] if self.ignore_assistant_messages else None

            # Add message to Zep memory
            self.zep_client.memory.add(  # type: ignore
                session_id=self.session_id,
                messages=[zep_message],
                ignore_roles=ignore_roles_list,
            )
            return f"Message from '{role}' added successfully to session {self.session_id}."
        except Exception as e:
            error_msg = f"Failed to add message to Zep session {self.session_id}: {e}"
            log_error(error_msg)
            return f"Error adding message: {e}"

    def get_zep_memory(self, memory_type: str = "context") -> str:
        """
        Retrieves the memory for the current Zep session.
        Args:
            memory_type: The type of memory to retrieve ('context', 'summary', 'messages').
        Returns:
            The requested memory content as a string, or an error string.
        """
        if not self.zep_client or not self.session_id:
            log_error("Zep client or session ID not initialized. Cannot get memory.")
            return "Error: Zep client/session not initialized."

        try:
            log_debug(f"Getting Zep memory for session {self.session_id}")
            memory_data = self.zep_client.memory.get(session_id=self.session_id)  # type: ignore

            if memory_type == "context":
                # Ensure context is a string
                return memory_data.context or "No context available."
            elif memory_type == "summary":
                # Ensure summary content is a string, checking both summary and its content
                return (
                    (memory_data.summary.content or "Summary content not available.")
                    if memory_data.summary
                    else "No summary available."
                )
            elif memory_type == "messages":
                # Ensure messages string representation is returned
                return str(memory_data.messages) if memory_data.messages else "No messages available."
            else:
                warning_msg = f"Unsupported memory_type requested: {memory_type}. Returning empty string."
                log_warning(warning_msg)
                return warning_msg

        except Exception as e:
            log_error(f"Failed to get Zep memory for session {self.session_id}: {e}")
            return f"Error getting memory for session {self.session_id}"

    def search_zep_memory(self, query: str, search_scope: str = "messages") -> str:
        """
        Searches the Zep memory store for relevant messages or summaries associated with the configured user_id.
        Args:
            query: The search term to find relevant facts.
            search_scope: The scope of the search to perform. Can be "messages" or "summary".
        Returns:
            A string of the search result
        """
        results: List = []
        search_result = ""
        if not self.zep_client or not self.user_id or not self.session_id:
            log_error("Zep client or user ID or session ID not initialized. Cannot search memory.")
            return "Error: Zep client/user/session not initialized."

        try:
            search_response: List[MemorySearchResult] = self.zep_client.memory.search(
                text=query, session_id=self.session_id, search_scope=search_scope
            )
            results = [
                {
                    "content": response.message.content,
                    "created_at": response.message.created_at,
                    "uuid": response.message.uuid_,
                    "score": response.score,
                    "summary": response.summary,
                }
                for response in search_response
                if response.message is not None
            ]
            log_debug(f"Memory search found {len(results)} relevant messages.")
        except Exception as e:
            log_error(f"Failed to search Zep graph memory for user {self.user_id}: {e}")

        if results is not None and results != []:
            if search_scope == "summary":
                search_result = " ".join(
                    [result.get("summary", "") for result in results if result.get("summary") is not None]
                )
                if search_result == "":
                    return "No relevant summary found."
                else:
                    return search_result
            else:
                search_result = " ".join(
                    [result.get("content", "") for result in results if result.get("content") is not None]
                )
                if search_result == "":
                    return "No relevant content found."
                else:
                    return search_result
        else:
            return "No relevant messages found."


class ZepAsyncTools(Toolkit):
    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        ignore_assistant_messages: bool = False,
        add_zep_message: bool = True,
        get_zep_memory: bool = True,
        search_zep_memory: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        **kwargs,
    ):
        super().__init__(name="zep_tools", instructions=instructions, add_instructions=add_instructions, **kwargs)

        self._api_key = api_key or getenv("ZEP_API_KEY")
        if not self._api_key:
            raise ValueError(
                "No Zep API key provided. Please set the ZEP_API_KEY environment variable or pass it to the ZepTools constructor."
            )

        if instructions is None:
            self.instructions = "<Memory Instructions>\n" + DEFAULT_INSTRUCTIONS + "\n</Memory Instructions>"

        self.zep_client: Optional[AsyncZep] = None
        self._initialized = False

        self.session_id_provided = session_id
        self.user_id_provided = user_id
        self.ignore_assistant_messages = ignore_assistant_messages

        self.session_id: Optional[str] = None
        self.user_id: Optional[str] = None

        self._initialized = False

        # Register methods as tools conditionally
        if add_zep_message:
            self.register(self.add_zep_message)
        if get_zep_memory:
            self.register(self.get_zep_memory)
        if search_zep_memory:
            self.register(self.search_zep_memory)

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
                    except BadRequestError as add_err:
                        log_error(f"Failed to create provided user {self.user_id}: {add_err}")
                        self.zep_client = None  # Reset client on failure
                        return False  # Initialization failed

            self._initialized = True
            return True

        except Exception as e:
            log_error(f"Failed to initialize ZepTools: {e}")
            self.zep_client = None
            self._initialized = False
            return False

    async def add_zep_message(self, role: str, content: str) -> str:
        """
        Adds a message to the current Zep session memory.
        Args:
            role (str): The role of the message sender (e.g., 'user', 'assistant', 'system').
            content (str): The text content of the message.

        Returns:
            A confirmation message or an error string.
        """
        if not self._initialized:
            await self.initialize()

        if not self.zep_client or not self.session_id:
            log_error("Zep client or session ID not initialized. Cannot add message.")
            return "Error: Zep client/session not initialized."

        try:
            zep_message = ZepMessage(
                role_type=role,
                content=content,
            )

            # Prepare ignore_roles if needed
            ignore_roles_list = ["assistant"] if self.ignore_assistant_messages else None

            # Add message to Zep memory
            await self.zep_client.memory.add(  # type: ignore
                session_id=self.session_id,
                messages=[zep_message],
                ignore_roles=ignore_roles_list,
            )
            return f"Message from '{role}' added successfully to session {self.session_id}."
        except Exception as e:
            error_msg = f"Failed to add message to Zep session {self.session_id}: {e}"
            log_error(error_msg)
            return f"Error adding message: {e}"

    async def get_zep_memory(self, memory_type: str = "context") -> str:
        """
        Retrieves the memory for the current Zep session.
        Args:
            memory_type: The type of memory to retrieve ('context', 'summary', 'messages').
        Returns:
            The requested memory content as a string, or an error string.
        """
        if not self._initialized:
            await self.initialize()

        if not self.zep_client or not self.session_id:
            log_error("Zep client or session ID not initialized. Cannot get memory.")
            return "Error: Zep client/session not initialized."

        try:
            memory_data = await self.zep_client.memory.get(session_id=self.session_id)  # type: ignore

            if memory_type == "context":
                # Ensure context is a string
                return memory_data.context or "No context available."
            elif memory_type == "summary":
                # Ensure summary content is a string, checking both summary and its content
                return (
                    (memory_data.summary.content or "Summary content not available.")
                    if memory_data.summary
                    else "No summary available."
                )
            elif memory_type == "messages":
                # Ensure messages string representation is returned
                return str(memory_data.messages) if memory_data.messages else "No messages available."
            else:
                warning_msg = f"Unsupported memory_type requested: {memory_type}. Returning empty string."
                log_warning(warning_msg)
                return warning_msg

        except Exception as e:
            error_msg = f"Failed to get Zep memory for session {self.session_id}: {e}"
            log_error(error_msg)
            return f"Error getting memory: {e}"

    async def search_zep_memory(self, query: str, search_scope: str = "messages") -> str:
        """
        Searches the Zep memory store for relevant messages or summaries associated with the configured user_id.
        Args:
            query: The search term to find relevant facts.
            search_scope: The scope of the search to perform. Can be "messages" or "summary".
        Returns:
            A string of the search result
        """
        if not self._initialized:
            await self.initialize()

        results: List = []
        search_result = ""

        if not self.zep_client or not self.user_id or not self.session_id:
            log_error("Zep client or user ID or session ID not initialized. Cannot search memory.")
            return "Error: Zep client/user/session not initialized."

        try:
            search_response: List[MemorySearchResult] = await self.zep_client.memory.search(
                text=query, session_id=self.session_id, search_scope=search_scope
            )

            results = [
                {
                    "content": response.message.content,
                    "created_at": response.message.created_at,
                    "uuid": response.message.uuid_,
                    "score": response.score,
                    "summary": response.summary,
                }
                for response in search_response
                if response.message is not None
            ]

            log_debug(f"Memory search found {len(results)} relevant messages.")
        except Exception as e:
            log_error(f"Failed to search Zep graph memory for user {self.user_id}: {e}")

        if results is not None and results != []:
            if search_scope == "summary":
                search_result = " ".join(
                    [result.get("summary", "") for result in results if result.get("summary") is not None]
                )
                if search_result == "":
                    return "No relevant summary found."
                else:
                    return search_result
            else:
                search_result = " ".join(
                    [result.get("content", "") for result in results if result.get("content") is not None]
                )
                if search_result == "":
                    return "No relevant content found."
                else:
                    return search_result
        else:
            return "No relevant messages found."
