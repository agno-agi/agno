import io
import os
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Union, cast

try:
    from mem0 import Memory, MemoryClient
except ImportError:
    raise ImportError(
        "`mem0ai` not installed. Please install it with `pip install mem0ai`"
    )

from agno.memory.v2.manager import MemoryManager
from agno.memory.v2.memory import Memory as AgnoMemory
from agno.memory.v2.schema import UserMemory
from agno.memory.v2.summarizer import SessionSummarizer
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_error, log_warning
from openai import OpenAIError


def process_messages(
    message: Optional[Union[str, Message]] = None,
    messages: Optional[List[Message]] = None,
) -> List[Dict[str, Any]]:
    """Process message to Mem0 format.
        Do NOT pass `message` and `messages` at the same time.
        Currently only process texts - mem0 supports audio, images and files.
    Args:
        message (Optional[Union[str, Message]]): Message to process.
        messages (Optional[List[Message]]): Messages to process.
    Returns:
        List[Dict[str, Any]]: List of processed message of format:
            {
                'role': 'user' or 'assistnat' or ...,
                'content': 'Content of the message',
            }
    """
    if (not messages and not message) or (message and messages):
        raise ValueError(
            "You must provide either a message or a list of messages - not both."
        )

    if messages is not None and messages:
        return [
            {"role": message.role, "content": message.content} for message in messages
        ]

    if isinstance(message, str):
        return [{"role": "user", "content": message}]

    if isinstance(message, Message):
        return [{"role": message.role, "content": message.content}]

    raise ValueError(
        "Either message or messages must be provided with required format."
    )


def add_messages(
    client: Union[Memory, MemoryClient],
    message: Optional[Union[str, Message]] = None,
    messages: Optional[List[Message]] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Add memory to Mem0
    Args:
        metadata (Optional[Dict[str, Any]]): Metadata to store with the memory.
            There's a bug in Chroma DB preventing passing user_id and session_id at the same time:
            https://github.com/chroma-core/chroma/issues/3248
            This affects all mem0 functions - search, get_all, add, and etc.
            If there's error calling mem0 queries, will try again with extra info stored in metadata.
    Returns:
        Dict[str, Any]: List of responses from Mem0 (multiple entries may be created for one message) of format:
            {
                'id': 'Memory ID',
                'event': 'ADD',
                'memory': 'Content of memory',
            }
    """
    # Suppress warning messages from mem0 MemoryClient
    kwargs = {"output_format": "v1.1"} if isinstance(client, MemoryClient) else {}

    # Messages to be added to mem0
    msgs = process_messages(message=message, messages=messages)

    res = []
    if user_id is None:
        user_id = "default"

    # Suppress warning messages from mem0
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            res = client.add(
                messages=msgs,
                user_id=user_id,
                run_id=session_id,
                agent_id=agent_id,
                metadata=metadata,
                **kwargs,
            )
        except ValueError:
            log_warning(
                "Error calling mem0 add. Trying again with extra info stored in metadata."
            )
            try:
                # Use same naming convention as in mem0
                if not isinstance(metadata, dict):
                    metadata = {}
                if session_id:
                    metadata["run_id"] = session_id
                if agent_id:
                    metadata["agent_id"] = agent_id
                res = client.add(
                    messages=msgs,
                    user_id=user_id,
                    metadata=metadata,
                    **kwargs,
                )
            except ValueError:
                log_error("Error calling mem0 add with 2nd trial. Stop adding")

    if isinstance(res, dict):
        return res.get("results", [])
    return res


async def aadd_messages(
    client: Union[Memory, MemoryClient],
    message: Optional[Union[str, Message]] = None,
    messages: Optional[List[Message]] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Add memory to Mem0"""
    return await client.add_messages(
        message=message,
        messages=messages,
        user_id=user_id,
        session_id=session_id,
        agent_id=agent_id,
        metadata=metadata,
    )


def to_user_memory(memory: dict) -> UserMemory:
    """Convert memory to UserMemory"""
    last_updated = memory.get("updated_at", None)
    if last_updated is None:
        last_updated = memory.get("created_at", None)
    if last_updated is not None:
        last_updated = datetime.fromisoformat(last_updated)

    return UserMemory(
        memory=memory.get("memory", ""),
        topics=memory.get("categories", []),
        input=memory.get("input", None),
        last_updated=last_updated,
        memory_id=memory.get("id", None),
    )


@dataclass
class Mem0Memory(AgnoMemory):
    """Mem0 implementation for Memory"""

    client: Optional[Union[Memory, MemoryClient]] = None
    context_length: int = 10

    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None

    def __init__(
        self,
        client: Optional[Union[Memory, MemoryClient]] = None,
        # Mem0 API Key or system environment variable with API Key
        api_key: Optional[str] = None,
        # Initiate client from config dictionary
        config: Optional[Mapping[str, Any]] = None,
        **kwargs,
    ):
        from inspect import signature

        super().__init__(
            **{k: v for k, v in kwargs.items() if k in signature(AgnoMemory).parameters}
        )

        if isinstance(client, (Memory, MemoryClient)):
            self.client = client
        elif api_key:
            try:
                self.client = MemoryClient(api_key=os.getenv(api_key, api_key))
            except ValueError as e:
                raise e
        elif isinstance(config, Mapping) and config:
            try:
                self.client = Memory.from_config(config)
            except OpenAIError:
                raise ValueError(f"Invalid value of config:\n{config}")
        else:
            raise ValueError("Mem0 client is not provided.")

        self.user_id = kwargs.get("user_id", "default")
        self.agent_id = kwargs.get("agent_id", None)
        self.session_id = kwargs.get("session_id", None)

    def set_model(self, model: Model) -> None:
        if self.memory_manager is None:
            self.memory_manager: MemoryManager = Mem0MemoryManager(
                model=deepcopy(model)
            )
        if self.memory_manager.model is None:
            self.memory_manager.model = deepcopy(model)
        # Use the same mem0 client
        self.memory_manager = cast(Mem0MemoryManager, self.memory_manager)
        if self.memory_manager.client is None:
            self.memory_manager.client = self.client
        if self.summary_manager is None:
            self.summary_manager: SessionSummarizer = SessionSummarizer(
                model=deepcopy(model)
            )
        if self.summary_manager.model is None:
            self.summary_manager.model = deepcopy(model)

    def _user_id_(self, user_id: Optional[str] = None) -> str:
        """Get the user id for the memory"""
        if user_id is None:
            user_id = self.user_id if self.user_id else "default"
        return user_id

    def search(
        self,
        query: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: Optional[int] = None,
        filters: Optional[Mapping[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Get the related context for the user.
        Args:
            query (str): The query to search for - if None, all memories will be returned
            user_id (str): The user id to search for
            agent_id (str): The agent id to search for
            session_id (str): The session id to search for
            limit (int): The number of memories to return
            filters (Mapping[str, Any]): Filters to apply to the search
        Returns:
            List[Dict[str, Any]]: The list of memories of format:
                {
                    'id': str,
                    'memory': str,
                    'hash': str, # if available
                    'user_id': str,
                    'run_id': str, # if available
                    'agent_id': str, # if available
                    'metadata': Optional[dict],
                    'categories': List[str], # if available
                    'score': float,
                    'created_at': str,
                    'updated_at': str,
                    'expiration_date': str, # if available,
                }
        """
        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        user_id = self._user_id_(user_id)

        manual_filter = {}
        session_id = self.session_id if session_id is None else session_id
        agent_id = self.agent_id if agent_id is None else agent_id
        limit = self.context_length if limit is None else limit

        # Suppress warning messages from mem0
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                log_debug("Query from mem0 for the 1st trial")
                if query:
                    memories = self.client.search(
                        query=query,
                        user_id=user_id,
                        run_id=session_id,
                        agent_id=agent_id,
                        limit=limit,
                        filters=filters,
                    )
                else:
                    memories = self.client.get_all(
                        user_id=user_id,
                        run_id=session_id,
                        agent_id=agent_id,
                        limit=limit,
                    )
            except ValueError:
                log_warning(
                    f"Cannot read specific memory for user {user_id}, reading all from user then filter manually"
                )
                try:
                    # Use the same naming convension of mem0 when adding memories in `add_user_memory`
                    if session_id:
                        manual_filter["run_id"] = session_id
                    if agent_id:
                        manual_filter["agent_id"] = agent_id
                    for k, v in (filters or {}).items():
                        manual_filter[k] = v
                    if limit:
                        limit = limit * 2

                    log_debug("Query from mem0 for the 2nd trial")
                    if query:
                        memories = self.client.search(
                            query=query, user_id=user_id, limit=limit
                        )
                    else:
                        memories = self.client.get_all(user_id=user_id, limit=limit)
                except ValueError:
                    log_error(f"Cannot read memory for user {user_id}")
                    return []

        if isinstance(memories, dict):
            memories = memories.get("results", [])
        if not isinstance(memories, list):
            return []
        if not manual_filter:
            return memories
        return list(
            filter(
                lambda m: all(
                    (
                        isinstance(m.get("metadata", {}), dict)
                        and m["metadata"].get(k, "") == v
                    )
                    or m.get("run_id" if k == "session_id" else k, "") == v
                    for k, v in manual_filter.items()
                ),
                memories,
            )
        )

    def _refresh_memories_(
        self, memories: List[Dict[str, Any]], user_id: Optional[str] = None
    ) -> str:
        """Refresh memories and return the first non-empty memory id."""
        user_id = self._user_id_(user_id)
        memory_id: str = ""
        # Update memory cache
        if self.memories is None:
            self.memories = {}  # type: ignore
        for memory in memories:
            # Mem0 returns a list of memories and add them to the memory cache
            # Only the first non-empty id will be returned
            if not memory_id:
                memory_id = memory["id"]
            self.memories.setdefault(user_id, {})[memory["id"]] = to_user_memory(memory)
        return memory_id

    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,  # always refresh from mem0
    ) -> List[UserMemory]:
        """Get all memories for the user."""
        return [to_user_memory(memory) for memory in self.search(user_id=user_id)]

    def refresh_from_db(self, user_id: Optional[str] = None) -> None:
        """Mem0 manages database itself - refresh the memory cache from mem0."""
        # Mem0 requires one of the following to be provided: user_id, run_id, and agent_id
        # Need to find workaround to query all memories
        user_id = self._user_id_(user_id)
        memories: List[Dict[str, Any]] = self.search(
            query="Most recent or important history of the user",
            user_id=user_id,
            agent_id=self.agent_id,
            session_id=self.session_id,
        )
        if self.memories is None:
            self.memories = {}  # type: ignore
        for memory in memories:
            self.memories.setdefault(user_id, {})[memory["id"]] = to_user_memory(memory)

    def add_user_memory(
        self,
        memory: Union[str, UserMemory],
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> str:
        """Add a user memory for a given user id
        Args:
            memory (UserMemory): The memory to add
            user_id (Optional[str]): The user id to add the memory to
        Returns:
            str: Memory ID - for mem0 it is possible to return multiple memories from one input.
                Will return the first memory ID from ths list of memories.
        """
        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        user_id = self._user_id_(user_id)

        metadata: Optional[Dict[str, Any]] = None
        if isinstance(memory, UserMemory):
            # Update metadata from UserMemory and self
            message = memory.memory
            if memory.topics or memory.input or memory.last_updated:
                metadata = {}
                if memory.topics:
                    metadata["categories"] = memory.topics
                if memory.input:
                    metadata["input"] = memory.input
                if memory.last_updated:
                    metadata["created_at"] = memory.last_updated.isoformat()
        else:
            message = memory

        # Adding message to mem0
        res: List[Dict[str, Any]] = add_messages(
            client=self.client,
            message=message,
            user_id=user_id,
            session_id=self.session_id,
            agent_id=self.agent_id,
            metadata=metadata,
        )

        if not isinstance(res, list):
            return ""
        return self._refresh_memories_(memories=res, user_id=user_id)

    def create_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> str:
        """Creates memories from message(s) and adds them to mem0.
        Currently Agno only sends user messages to the memory.
        Information would be missing when user and assistant having a back and forth conversation.
        """
        self.set_log_level()

        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        if not isinstance(self.memory_manager, Mem0MemoryManager):
            raise ValueError("`memory_manager` is not properly initiated.")

        user_id = self._user_id_(user_id)

        # Adding message(s) to mem0
        res: List[Dict[str, Any]] = add_messages(
            client=self.client,
            message=message,
            messages=messages,
            user_id=user_id,
            session_id=self.session_id,
            agent_id=self.agent_id,
        )

        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        existing_memories = self.memories.get(user_id, {})  # type: ignore
        existing_memories = [
            {"memory_id": memory_id, "memory": memory.memory}
            for memory_id, memory in existing_memories.items()
        ]
        if isinstance(messages, list) and messages and isinstance(messages[0], Message):
            msgs = messages
        else:
            msgs = [Message(role="user", content=message)]

        self.memory_manager.create_or_update_memories(  # type: ignore
            messages=msgs,
            existing_memories=existing_memories,
            user_id=user_id,
            delete_memories=self.delete_memories,
            clear_memories=self.clear_memories,
        )

        if not isinstance(res, list):
            return ""
        return self._refresh_memories_(memories=res, user_id=user_id)

    async def acreate_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[list[Message]] = None,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> str:
        """Creates memories from multiple messages and adds them to mem0."""
        self.set_log_level()

        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        if not isinstance(self.memory_manager, Mem0MemoryManager):
            raise ValueError("`memory_manager` is not properly initiated.")

        user_id = self._user_id_(user_id)

        # Adding message(s) to mem0
        res: List[Dict[str, Any]] = await aadd_messages(
            client=self.client,
            message=message,
            messages=messages,
            user_id=user_id,
            session_id=self.session_id,
            agent_id=self.agent_id,
        )

        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        existing_memories = self.memories.get(user_id, {})  # type: ignore
        existing_memories = [
            {"memory_id": memory_id, "memory": memory.memory}
            for memory_id, memory in existing_memories.items()
        ]
        if isinstance(messages, list) and messages and isinstance(messages[0], Message):
            msgs = messages
        else:
            msgs = [Message(role="user", content=message)]

        await self.memory_manager.acreate_or_update_memories(  # type: ignore
            messages=msgs,
            existing_memories=existing_memories,
            user_id=user_id,
            delete_memories=self.delete_memories,
            clear_memories=self.clear_memories,
        )

        if not isinstance(res, list):
            return ""
        return self._refresh_memories_(memories=res, user_id=user_id)

    def delete_user_memory(
        self,
        memory_id: str,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> None:
        """Delete a user memory for a given mememory id - user id is not required for mem0
        Args:
            memory_id (str): The id of the memory to delete
        """
        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        try:
            self.client.delete(memory_id=memory_id)
        except IndexError:
            log_error(f"Cannot delete memory for memory id: {memory_id}")

    def update_memory_task(self, task: str, user_id: Optional[str] = None) -> str:
        """Updates the memory with a task"""
        if not self.memory_manager:
            raise ValueError("Memory manager not initialized")

        user_id = self._user_id_(user_id)
        if self.memories is None:
            self.memories = {}  # type: ignore
        existing_memories = [
            {"memory_id": memory_id, "memory": memory.memory}
            for memory_id, memory in self.memories.get(user_id, {}).items()
        ]
        # The memory manager updates the DB directly
        response = self.memory_manager.run_memory_task(  # type: ignore
            task=task,
            existing_memories=existing_memories,
            user_id=user_id,
            delete_memories=self.delete_memories,
            clear_memories=self.clear_memories,
        )

        self.refresh_from_db(user_id=user_id)
        return response

    async def aupdate_memory_task(
        self, task: str, user_id: Optional[str] = None
    ) -> str:
        """Updates the memory with a task"""
        self.set_log_level()
        if not self.memory_manager:
            raise ValueError("Memory manager not initialized")

        user_id = self._user_id_(user_id)
        if self.memories is None:
            self.memories = {}  # type: ignore
        existing_memories = [
            {"memory_id": memory_id, "memory": memory.memory}
            for memory_id, memory in self.memories.get(user_id, {}).items()
        ]
        # The memory manager updates the DB directly
        response = await self.memory_manager.arun_memory_task(  # type: ignore
            task=task,
            existing_memories=existing_memories,
            user_id=user_id,
            delete_memories=self.delete_memories,
            clear_memories=self.clear_memories,
        )

        self.refresh_from_db(user_id=user_id)
        return response


@dataclass
class Mem0MemoryManager(MemoryManager):
    """Model for Mem0 Memory Manager"""

    client: Optional[Union[Memory, MemoryClient]] = None

    def __init__(self, client: Optional[Union[Memory, MemoryClient]] = None, **kwargs):
        super().__init__(**kwargs)
        self.client = client

    def create_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        delete_memories: bool = True,
        clear_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        log_debug("MemoryManager Start", center=True)

        if len(messages) == 1:
            input_string = messages[0].get_content_string()
        else:
            input_string = f"{', '.join([m.get_content_string() for m in messages if m.role == 'user' and m.content])}"

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(
                self.client,
                user_id,
                input_string,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories=existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(messages=messages_for_model)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    async def acreate_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        delete_memories: bool = True,
        clear_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        log_debug("MemoryManager Start", center=True)

        if len(messages) == 1:
            input_string = messages[0].get_content_string()
        else:
            input_string = f"{', '.join([m.get_content_string() for m in messages if m.role == 'user' and m.content])}"

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(
                self.client,
                user_id,
                input_string,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories=existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(messages=messages_for_model)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    def run_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        delete_memories: bool = True,
        clear_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        log_debug("MemoryManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(
                self.client,
                user_id,
                task,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(messages=messages_for_model)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    async def arun_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        delete_memories: bool = True,
        clear_memories: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for memory manager")
            return "No model provided for memory manager"

        if not isinstance(self.client, (Memory, MemoryClient)):
            raise ValueError("`client` is not properly initiated.")

        log_debug("MemoryManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.add_tools_to_model(
            model_copy,
            self._get_db_tools(
                self.client,
                user_id,
                task,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(messages=messages_for_model)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.memories_updated = True
        log_debug("MemoryManager End", center=True)

        return response.content or "No response from model"

    # -*- DB Functions
    def _get_db_tools(
        self,
        client: Union[Memory, MemoryClient],
        user_id: str,
        input_string: str,
        enable_add_memory: bool = True,
        enable_update_memory: bool = True,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
    ) -> List[Callable]:

        def add_memory(memory: str) -> str:
            """Use this function to add a memory to the database.
            Args:
                memory (str): The memory to be added.
            Returns:
                str: A message indicating if the memory was added successfully or not.
            """
            try:
                res: List[Dict[str, Any]] = add_messages(
                    client=client,
                    message=memory,
                    user_id=user_id,
                    metadata={"input": input_string},
                )
                if len(res) == 1:
                    log_debug(f"Memory added: {res[0]['id']}")
                elif len(res) > 1:
                    log_debug("Memory added:\n" + "\n".join([r["id"] for r in res]))
                return "Memory added successfully"
            except Exception as e:
                log_warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def update_memory(memory_id: str, memory: str) -> str:
            """Use this function to update an existing memory in the database.
            Args:
                memory_id (str): The id of the memory to be updated.
                memory (str): The updated memory.
            Returns:
                str: A message indicating if the memory was updated successfully or not.
            """
            try:
                res: dict = client.update(memory_id=memory_id, data=memory)
                log_debug("Memory updated")
                return res.get("message", "Memory updated successfully")
            except Exception as e:
                log_warning("Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def delete_memory(memory_id: str) -> str:
            """Use this function to delete a single memory from the database.
            Args:
                memory_id (str): The id of the memory to be deleted.
            Returns:
                str: A message indicating if the memory was deleted successfully or not.
            """
            try:
                client.delete(memory_id=memory_id)
                log_debug("Memory deleted")
                return "Memory deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting memory in db: {e}")
                return f"Error deleting memory: {e}"

        def clear_memory() -> str:
            """Use this function to remove all (or clear all) memories from the database.

            Returns:
                str: A message indicating if the memory was cleared successfully or not.
            """
            log_debug("Memory cleared")
            return "Memory cleared successfully"

        functions: List[Callable] = []
        if enable_add_memory:
            functions.append(add_memory)
        if enable_update_memory:
            functions.append(update_memory)
        if enable_delete_memory:
            functions.append(delete_memory)
        if enable_clear_memory:
            functions.append(clear_memory)
        return functions
