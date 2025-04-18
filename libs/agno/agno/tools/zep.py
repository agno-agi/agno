import os
import uuid
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from zep_cloud import BadRequestError, NotFoundError
    from zep_cloud.client import AsyncZep
    from zep_cloud.types import Message as ZepMessage
except ImportError:
    raise ImportError("`zep-cloud` package not found. Please install it with `pip install zep-cloud`")


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
        **kwargs,
    ):
        super().__init__(name="zep_tools", **kwargs)

        self._api_key = api_key or os.getenv("ZEP_API_KEY")
        self.zep_client: Optional[AsyncZep] = None
        self._initialized = False

        self.session_id_provided = session_id
        self.user_id_provided = user_id
        self.ignore_assistant_messages = ignore_assistant_messages

        self.session_id: Optional[str] = None
        self.user_id: Optional[str] = None

        # Register methods as tools conditionally
        if add_zep_message:
            self.register(self.add_zep_message)
        if get_zep_memory:
            self.register(self.get_zep_memory)
        if search_zep_memory:
            self.register(self.search_zep_memory)

    async def initialize(self) -> bool:
        """
        Explicitly initialize the AsyncZep client and ensure session/user setup.
        """
        if self._initialized:
            return True

        if not self._api_key:
            raise ValueError("Cannot initialize ZepTools: ZEP_API_KEY is missing.")

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
                        logger.error(f"Failed to create provided user {self.user_id}: {add_err}", exc_info=True)
                        self.zep_client = None  # Reset client on failure
                        return False  # Initialization failed

            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize ZepTools: {e}", exc_info=True)
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
        if not self.zep_client or not self.session_id:
            logger.error("Zep client or session ID not initialized. Cannot add message.")
            return "Error: Zep client/session not initialized."

        try:
            zep_message = ZepMessage(
                role=role,
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
            logger.error(error_msg, exc_info=True)
            return f"Error adding message: {e}"

    async def get_zep_memory(self, memory_type: str = "context") -> str:
        """
        Retrieves the memory for the current Zep session.
        Args:
            memory_type: The type of memory to retrieve ('context', 'summary', 'messages').
        Returns:
            The requested memory content as a string, or an error string.
        """
        if not self.zep_client or not self.session_id:
            logger.error("Zep client or session ID not initialized. Cannot get memory.")
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
                logger.warning(warning_msg)
                return warning_msg

        except Exception as e:
            error_msg = f"Failed to get Zep memory for session {self.session_id}: {e}"
            logger.error(error_msg, exc_info=True)
            return f"Error getting memory: {e}"

    async def search_zep_memory(self, query: str) -> List[Dict[str, Any]]:
        """
        Searches the Zep user graph for relevant facts associated with the configured user_id.
        Args:
            query: The search term to find relevant facts.
        Returns:
            A list of search result dictionaries, or an empty list if an error occurs.
        """
        formatted_results: List[Dict[str, Any]] = []
        if not self.zep_client or not self.user_id:
            logger.error("Zep client or user ID not initialized. Cannot search memory.")
            return formatted_results

        try:
            # Use graph.search as shown in reference examples
            search_response = await self.zep_client.graph.search(query=query, user_id=self.user_id, scope="edges")

            if search_response and search_response.edges:
                # Convert graph search results to the expected format
                formatted_results = [
                    {
                        "role": "fact",  # Mark these as facts found in memory
                        "content": edge.fact,
                    }
                    for edge in search_response.edges
                ]
                log_debug(f"Memory search found {len(formatted_results)} relevant facts.")
            else:
                log_debug("Memory search found no relevant facts.")
        except Exception as e:
            logger.error(f"Failed to search Zep graph memory for user {self.user_id}: {e}", exc_info=True)
        return formatted_results
