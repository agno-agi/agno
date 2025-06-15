import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Type, Union

from pydantic import BaseModel, Field

from agno.media import AudioArtifact, ImageArtifact, VideoArtifact
from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.memory.v2.manager import MemoryManager
from agno.memory.v2.schema import SessionSummary, UserMemory
from agno.memory.v2.summarizer import SessionSummarizer
from agno.models.base import Model
from agno.models.message import Message
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.utils.log import log_debug, log_warning, logger, set_log_level_to_debug, set_log_level_to_info
from agno.utils.prompts import get_json_output_prompt
from agno.utils.string import parse_response_model_str


class MemorySearchResponse(BaseModel):
    """Model for Memory Search Response."""

    memory_ids: List[str] = Field(
        ..., description="The IDs of the memories that are most semantically similar to the query."
    )


@dataclass
class TeamMemberInteraction:
    member_name: str
    task: str
    response: Union[RunResponse, TeamRunResponse]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "member_name": self.member_name,
            "task": self.task,
            "response": self.response.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeamMemberInteraction":
        if data["response"].get("agent_id"):
            return cls(
                member_name=data["member_name"], task=data["task"], response=RunResponse.from_dict(data["response"])
            )
        else:
            return cls(
                member_name=data["member_name"], task=data["task"], response=TeamRunResponse.from_dict(data["response"])
            )


@dataclass
class TeamContext:
    # List of team member interaction, represented as a request and a response
    member_interactions: List[TeamMemberInteraction] = field(default_factory=list)
    text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "member_interactions": [interaction.to_dict() for interaction in self.member_interactions],
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeamContext":
        return cls(
            member_interactions=[
                TeamMemberInteraction.from_dict(interaction) for interaction in data["member_interactions"]
            ],
            text=data["text"],
        )


@dataclass
class Memory:
    # Model used for memories and summaries
    model: Optional[Model] = None

    # Memories per memory ID per user
    memories: Optional[Dict[str, Dict[str, UserMemory]]] = None
    # Manager to manage memories
    memory_manager: Optional[MemoryManager] = None

    # Session summaries per session per user
    summaries: Optional[Dict[str, Dict[str, SessionSummary]]] = None
    # Summarizer to generate session summaries
    summary_manager: Optional[SessionSummarizer] = None

    db: Optional[MemoryDb] = None

    # runs per session
    runs: Optional[Dict[str, List[Union[RunResponse, TeamRunResponse]]]] = None

    # Team context per session
    team_context: Optional[Dict[str, TeamContext]] = None

    # Whether to delete memories
    delete_memories: bool = False
    # Whether to clear memories
    clear_memories: bool = False

    debug_mode: bool = False
    version: int = 2

    def __init__(
        self,
        model: Optional[Model] = None,
        memory_manager: Optional[MemoryManager] = None,
        summarizer: Optional[SessionSummarizer] = None,
        db: Optional[MemoryDb] = None,
        memories: Optional[Dict[str, Dict[str, UserMemory]]] = None,
        summaries: Optional[Dict[str, Dict[str, SessionSummary]]] = None,
        runs: Optional[Dict[str, List[Union[RunResponse, TeamRunResponse]]]] = None,
        debug_mode: bool = False,
        delete_memories: bool = False,
        clear_memories: bool = False,
    ):
        self.memories = memories or {}
        self.summaries = summaries or {}
        self.runs = runs or {}

        self.debug_mode = debug_mode

        self.delete_memories = delete_memories
        self.clear_memories = clear_memories

        self.model = model

        if self.model is not None and isinstance(self.model, str):
            raise ValueError("Model must be a Model object, not a string")

        self.memory_manager = memory_manager

        self.summary_manager = summarizer

        self.db = db

        # We are making memories
        if self.model is not None:
            if self.memory_manager is None:
                self.memory_manager = MemoryManager(model=deepcopy(self.model))
            # Set the model on the memory manager if it is not set
            if self.memory_manager.model is None:
                self.memory_manager.model = deepcopy(self.model)

        # We are making session summaries
        if self.model is not None:
            if self.summary_manager is None:
                self.summary_manager = SessionSummarizer(model=deepcopy(self.model))
            # Set the model on the summary_manager if it is not set
            elif self.summary_manager.model is None:
                self.summary_manager.model = deepcopy(self.model)

        self.debug_mode = debug_mode

    def set_model(self, model: Model) -> None:
        if self.memory_manager is None:
            self.memory_manager = MemoryManager(model=deepcopy(model))
        if self.memory_manager.model is None:
            self.memory_manager.model = deepcopy(model)
        if self.summary_manager is None:
            self.summary_manager = SessionSummarizer(model=deepcopy(model))
        if self.summary_manager.model is None:
            self.summary_manager.model = deepcopy(model)

    def get_model(self) -> Model:
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
        return self.model

    def refresh_from_db(self, user_id: Optional[str] = None):
        if self.db:
            # If no user_id is provided, read all memories
            if user_id is None:
                all_memories = self.db.read_memories()
            else:
                all_memories = self.db.read_memories(user_id=user_id)
            # Reset the memories
            self.memories = {}
            for memory in all_memories:
                if memory.user_id is not None and memory.id is not None:
                    self.memories.setdefault(memory.user_id, {})[memory.id] = UserMemory.from_dict(memory.memory)

    def set_log_level(self):
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    def initialize(self, user_id: Optional[str] = None):
        self.set_log_level()
        self.refresh_from_db(user_id=user_id)

    def to_dict(self) -> Dict[str, Any]:
        _memory_dict = {}
        # Add summary if it exists
        if self.summaries is not None:
            _memory_dict["summaries"] = {
                user_id: {session_id: summary.to_dict() for session_id, summary in session_summaries.items()}
                for user_id, session_summaries in self.summaries.items()
            }
        # Add memories if they exist
        if self.memories is not None:
            _memory_dict["memories"] = {
                user_id: {memory_id: memory.to_dict() for memory_id, memory in user_memories.items()}
                for user_id, user_memories in self.memories.items()
            }
        # Add runs if they exist
        if self.runs is not None:
            _memory_dict["runs"] = {}
            for session_id, runs in self.runs.items():
                if session_id is not None:
                    _memory_dict["runs"][session_id] = [run.to_dict() for run in runs]  # type: ignore

        if self.team_context is not None:
            _memory_dict["team_context"] = {}
            for session_id, team_context in self.team_context.items():
                if session_id is not None:
                    _memory_dict["team_context"][session_id] = team_context.to_dict()

        _memory_dict = {k: v for k, v in _memory_dict.items() if v is not None}
        return _memory_dict

    # -*- Public Functions
    def get_user_memories(self, user_id: Optional[str] = None, refresh_from_db: bool = True) -> List[UserMemory]:
        """Get the user memories for a given user id"""
        if user_id is None:
            user_id = "default"
        # Refresh from the DB
        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        if self.memories is None:
            return []
        return list(self.memories.get(user_id, {}).values())

    def get_session_summaries(self, user_id: Optional[str] = None) -> List[SessionSummary]:
        """Get the session summaries for a given user id"""
        if user_id is None:
            user_id = "default"
        if self.summaries is None:
            return []
        return list(self.summaries.get(user_id, {}).values())

    def get_user_memory(
        self, memory_id: str, user_id: Optional[str] = None, refresh_from_db: bool = True
    ) -> Optional[UserMemory]:
        """Get the user memory for a given user id"""
        if user_id is None:
            user_id = "default"
        # Refresh from the DB
        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)
        if self.memories is None:
            return None
        return self.memories.get(user_id, {}).get(memory_id, None)

    def get_session_summary(self, session_id: str, user_id: Optional[str] = None) -> Optional[SessionSummary]:
        """Get the session summary for a given user id"""
        if user_id is None:
            user_id = "default"
        if self.summaries is None:
            return None
        return self.summaries.get(user_id, {}).get(session_id, None)

    def add_user_memory(
        self,
        memory: UserMemory,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> str:
        """Add a user memory for a given user id
        Args:
            memory (UserMemory): The memory to add
            user_id (Optional[str]): The user id to add the memory to. If not provided, the memory is added to the "default" user.
        Returns:
            str: The id of the memory
        """
        from uuid import uuid4

        memory_id = memory.memory_id or str(uuid4())
        if memory.memory_id is None:
            memory.memory_id = memory_id
        if user_id is None:
            user_id = "default"

        # Refresh from the DB
        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        if not memory.last_updated:
            memory.last_updated = datetime.now()

        self.memories.setdefault(user_id, {})[memory_id] = memory  # type: ignore
        if self.db:
            self._upsert_db_memory(
                memory=MemoryRow(
                    id=memory_id,
                    user_id=user_id,
                    memory=memory.to_dict(),
                    last_updated=memory.last_updated or datetime.now(),
                )
            )

        return memory_id

    def replace_user_memory(
        self,
        memory_id: str,
        memory: UserMemory,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> Optional[str]:
        """Replace a user memory for a given user id
        Args:
            memory_id (str): The id of the memory to replace
            memory (UserMemory): The memory to add
            user_id (Optional[str]): The user id to add the memory to. If not provided, the memory is added to the "default" user.
        Returns:
            str: The id of the memory
        """

        if user_id is None:
            user_id = "default"

        # Refresh from the DB
        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        if not memory.last_updated:
            memory.last_updated = datetime.now()

        if memory_id not in self.memories[user_id]:  # type: ignore
            log_warning(f"Memory {memory_id} not found for user {user_id}")
            return None

        self.memories.setdefault(user_id, {})[memory_id] = memory  # type: ignore
        if self.db:
            self._upsert_db_memory(
                memory=MemoryRow(
                    id=memory_id,
                    user_id=user_id,
                    memory=memory.to_dict(),
                    last_updated=memory.last_updated or datetime.now(),
                )
            )

        return memory_id

    def delete_user_memory(
        self,
        memory_id: str,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> None:
        """Delete a user memory for a given user id
        Args:
            memory_id (str): The id of the memory to delete
            user_id (Optional[str]): The user id to delete the memory from. If not provided, the memory is deleted from the "default" user.
        """
        if user_id is None:
            user_id = "default"

        # Refresh from the DB
        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        if memory_id not in self.memories[user_id]:  # type: ignore
            log_warning(f"Memory {memory_id} not found for user {user_id}")
            return None

        del self.memories[user_id][memory_id]  # type: ignore
        if self.db:
            self._delete_db_memory(memory_id=memory_id)

    def delete_session_summary(self, user_id: str, session_id: str) -> None:
        """Delete a session summary for a given user id
        Args:
            user_id (str): The user id to delete the memory from
            session_id (str): The id of the session to delete
        """
        del self.summaries[user_id][session_id]  # type: ignore

    def get_runs(self, session_id: str) -> List[Union[RunResponse, TeamRunResponse]]:
        """Get all runs for a given session id"""
        if self.runs is None:
            return []
        return self.runs.get(session_id, [])

    # -*- Agent Functions
    def create_session_summary(self, session_id: str, user_id: Optional[str] = None) -> Optional[SessionSummary]:
        """Creates a summary of the session"""

        if not self.summary_manager:
            raise ValueError("Summarizer not initialized")

        self.set_log_level()

        if user_id is None:
            user_id = "default"

        summary_response = self.summary_manager.run(conversation=self.get_messages_for_session(session_id=session_id))
        if summary_response is None:
            return None
        session_summary = SessionSummary(
            summary=summary_response.summary, topics=summary_response.topics, last_updated=datetime.now()
        )
        self.summaries.setdefault(user_id, {})[session_id] = session_summary  # type: ignore

        return session_summary

    async def acreate_session_summary(self, session_id: str, user_id: Optional[str] = None) -> Optional[SessionSummary]:
        """Creates a summary of the session"""
        if not self.summary_manager:
            raise ValueError("Summarizer not initialized")

        self.set_log_level()

        if user_id is None:
            user_id = "default"

        summary_response = await self.summary_manager.arun(
            conversation=self.get_messages_for_session(session_id=session_id)
        )
        if summary_response is None:
            return None
        session_summary = SessionSummary(
            summary=summary_response.summary, topics=summary_response.topics, last_updated=datetime.now()
        )
        self.summaries.setdefault(user_id, {})[session_id] = session_summary  # type: ignore
        return session_summary

    def create_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> str:
        """Creates memories from multiple messages and adds them to the memory db."""
        self.set_log_level()
        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        if not self.memory_manager:
            raise ValueError("Memory manager not initialized")

        if self.db is None:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if user_id is None:
            user_id = "default"

        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        existing_memories = self.memories.get(user_id, {})  # type: ignore
        existing_memories = [
            {"memory_id": memory_id, "memory": memory.memory} for memory_id, memory in existing_memories.items()
        ]
        response = self.memory_manager.create_or_update_memories(  # type: ignore
            messages=messages,
            existing_memories=existing_memories,
            user_id=user_id,
            db=self.db,
            delete_memories=self.delete_memories,
            clear_memories=self.clear_memories,
        )

        # We refresh from the DB
        self.refresh_from_db(user_id=user_id)
        return response

    async def acreate_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> str:
        """Creates memories from multiple messages and adds them to the memory db."""
        self.set_log_level()
        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        if not self.memory_manager:
            raise ValueError("Memory manager not initialized")

        if self.db is None:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if user_id is None:
            user_id = "default"

        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        existing_memories = self.memories.get(user_id, {})  # type: ignore
        existing_memories = [
            {"memory_id": memory_id, "memory": memory.memory} for memory_id, memory in existing_memories.items()
        ]

        response = await self.memory_manager.acreate_or_update_memories(  # type: ignore
            messages=messages,
            existing_memories=existing_memories,
            user_id=user_id,
            db=self.db,
            delete_memories=self.delete_memories,
            clear_memories=self.clear_memories,
        )

        # We refresh from the DB
        self.refresh_from_db()

        return response

    def update_memory_task(self, task: str, user_id: Optional[str] = None) -> str:
        """Updates the memory with a task"""
        if not self.memory_manager:
            raise ValueError("Memory manager not initialized")

        if not self.db:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if user_id is None:
            user_id = "default"

        self.refresh_from_db(user_id=user_id)

        existing_memories = self.memories.get(user_id, {})  # type: ignore
        existing_memories = [
            {"memory_id": memory_id, "memory": memory.memory} for memory_id, memory in existing_memories.items()
        ]
        # The memory manager updates the DB directly
        response = self.memory_manager.run_memory_task(  # type: ignore
            task=task,
            existing_memories=existing_memories,
            user_id=user_id,
            db=self.db,
            delete_memories=self.delete_memories,
            clear_memories=self.clear_memories,
        )

        # We refresh from the DB
        self.refresh_from_db(user_id=user_id)

        return response

    async def aupdate_memory_task(self, task: str, user_id: Optional[str] = None) -> str:
        """Updates the memory with a task"""
        self.set_log_level()
        if not self.memory_manager:
            raise ValueError("Memory manager not initialized")

        if not self.db:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if user_id is None:
            user_id = "default"

        self.refresh_from_db(user_id=user_id)

        existing_memories = self.memories.get(user_id, {})  # type: ignore
        existing_memories = [
            {"memory_id": memory_id, "memory": memory.memory} for memory_id, memory in existing_memories.items()
        ]
        # The memory manager updates the DB directly
        response = await self.memory_manager.arun_memory_task(  # type: ignore
            task=task,
            existing_memories=existing_memories,
            user_id=user_id,
            db=self.db,
            delete_memories=self.delete_memories,
            clear_memories=self.clear_memories,
        )

        # We refresh from the DB
        self.refresh_from_db(user_id=user_id)

        return response

    # -*- DB Functions
    def _upsert_db_memory(self, memory: MemoryRow) -> str:
        """Use this function to add a memory to the database."""
        try:
            if not self.db:
                raise ValueError("Memory db not initialized")
            self.db.upsert_memory(memory)
            return "Memory added successfully"
        except Exception as e:
            logger.warning(f"Error storing memory in db: {e}")
            return f"Error adding memory: {e}"

    def _delete_db_memory(self, memory_id: str) -> str:
        """Use this function to delete a memory from the database."""
        try:
            if not self.db:
                raise ValueError("Memory db not initialized")
            self.db.delete_memory(memory_id=memory_id)
            return "Memory deleted successfully"
        except Exception as e:
            logger.warning(f"Error deleting memory in db: {e}")
            return f"Error deleting memory: {e}"

    # -*- Utility Functions
    def get_messages_for_session(
        self,
        session_id: str,
        user_role: str = "user",
        assistant_role: Optional[List[str]] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Returns a list of messages for the session that iterate through user message and assistant response."""

        if assistant_role is None:
            assistant_role = ["assistant", "model", "CHATBOT"]

        final_messages: List[Message] = []
        session_runs = self.runs.get(session_id, []) if self.runs else []
        for run_response in session_runs:
            if run_response and run_response.messages:
                user_message_from_run = None
                assistant_message_from_run = None

                # Start from the beginning to look for the user message
                for message in run_response.messages:
                    if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                        continue
                    if message.role == user_role:
                        user_message_from_run = message
                        break

                # Start from the end to look for the assistant response
                for message in run_response.messages[::-1]:
                    if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                        continue
                    if message.role in assistant_role:
                        assistant_message_from_run = message
                        break

                if user_message_from_run and assistant_message_from_run:
                    final_messages.append(user_message_from_run)
                    final_messages.append(assistant_message_from_run)
        return final_messages

    def add_run(self, session_id: str, run: Union[RunResponse, TeamRunResponse]) -> None:
        """Adds a RunResponse to the runs list."""
        if not self.runs:
            self.runs = {}

        if session_id not in self.runs:
            self.runs[session_id] = []

        # Check if run already exists with the same run_id
        if hasattr(run, "run_id") and run.run_id:
            run_id = run.run_id
            # Look for existing run with same ID
            for i, existing_run in enumerate(self.runs[session_id]):
                if hasattr(existing_run, "run_id") and existing_run.run_id == run_id:
                    # Replace existing run
                    self.runs[session_id][i] = run
                    log_debug(f"Replaced existing run with run_id {run_id} in memory")
                    return

        self.runs[session_id].append(run)
        log_debug("Added RunResponse to Memory")

    def get_messages_from_last_n_runs(
        self,
        session_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        last_n: Optional[int] = None,
        skip_role: Optional[str] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Returns the messages from the last_n runs, excluding previously tagged history messages.
        Args:
            session_id: The session id to get the messages from.
            agent_id: The id of the agent to get the messages from.
            team_id: The id of the team to get the messages from.
            last_n: The number of runs to return from the end of the conversation. Defaults to all runs.
            skip_role: Skip messages with this role.
            skip_history_messages: Skip messages that were tagged as history in previous runs.
        Returns:
            A list of Messages from the specified runs, excluding history messages.
        """
        if not self.runs:
            return []

        session_runs = self.runs.get(session_id, [])
        if agent_id:
            session_runs = [run for run in session_runs if hasattr(run, "agent_id") and run.agent_id == agent_id]  # type: ignore
        if team_id:
            session_runs = [run for run in session_runs if hasattr(run, "team_id") and run.team_id == team_id]  # type: ignore
        runs_to_process = session_runs[-last_n:] if last_n is not None else session_runs
        messages_from_history = []
        system_message = None
        for run_response in runs_to_process:
            if not (run_response and run_response.messages):
                continue

            for message in run_response.messages:
                # Skip messages with specified role
                if skip_role and message.role == skip_role:
                    continue
                # Skip messages that were tagged as history in previous runs
                if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                    continue
                if message.role == "system":
                    # Only add the system message once
                    if system_message is None:
                        system_message = message
                        messages_from_history.append(system_message)
                else:
                    messages_from_history.append(message)

        log_debug(f"Getting messages from previous runs: {len(messages_from_history)}")
        return messages_from_history

    def get_tool_calls(self, session_id: str, num_calls: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns a list of tool calls from the messages"""

        tool_calls = []
        session_runs = self.runs.get(session_id, []) if self.runs else []
        for run_response in session_runs[::-1]:
            if run_response and run_response.messages:
                for message in run_response.messages:
                    if message.tool_calls:
                        for tool_call in message.tool_calls:
                            tool_calls.append(tool_call)
                            if num_calls and len(tool_calls) >= num_calls:
                                return tool_calls
        return tool_calls

    def search_user_memories(
        self,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        retrieval_method: Optional[Literal["last_n", "first_n", "agentic"]] = None,
        user_id: Optional[str] = None,
        refresh_from_db: bool = True,
    ) -> List[UserMemory]:
        """Search through user memories using the specified retrieval method.

        Args:
            query: The search query for agentic search. Required if retrieval_method is "agentic".
            limit: Maximum number of memories to return. Defaults to self.retrieval_limit if not specified. Optional.
            retrieval_method: The method to use for retrieving memories. Defaults to self.retrieval if not specified.
                - "last_n": Return the most recent memories
                - "first_n": Return the oldest memories
                - "agentic": Return memories most similar to the query, but using an agentic approach
            user_id: The user to search for. Optional.

        Returns:
            A list of UserMemory objects matching the search criteria.
        """

        if user_id is None:
            user_id = "default"

        self.set_log_level()

        if refresh_from_db:
            self.refresh_from_db(user_id=user_id)

        if not self.memories:
            return []

        # Use default retrieval method if not specified
        retrieval_method = retrieval_method
        # Use default limit if not specified
        limit = limit

        # Handle different retrieval methods
        if retrieval_method == "agentic":
            if not query:
                raise ValueError("Query is required for agentic search")

            return self._search_user_memories_agentic(user_id=user_id, query=query, limit=limit)

        elif retrieval_method == "first_n":
            return self._get_first_n_memories(user_id=user_id, limit=limit)

        else:  # Default to last_n
            return self._get_last_n_memories(user_id=user_id, limit=limit)

    def get_response_format(self) -> Union[Dict[str, Any], Type[BaseModel]]:
        model = self.get_model()
        if model.supports_native_structured_outputs:
            return MemorySearchResponse

        elif model.supports_json_schema_outputs:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": MemorySearchResponse.__name__,
                    "schema": MemorySearchResponse.model_json_schema(),
                },
            }
        else:
            return {"type": "json_object"}

    def _search_user_memories_agentic(self, user_id: str, query: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Search through user memories using agentic search."""
        if not self.memories:
            return []

        model = self.get_model()

        response_format = self.get_response_format()

        log_debug("Searching for memories", center=True)

        # Get all memories as a list
        user_memories: Dict[str, UserMemory] = self.memories[user_id]
        system_message_str = "Your task is to search through user memories and return the IDs of the memories that are related to the query.\n"
        system_message_str += "\n<user_memories>\n"
        for memory in user_memories.values():
            system_message_str += f"ID: {memory.memory_id}\n"
            system_message_str += f"Memory: {memory.memory}\n"
            if memory.topics:
                system_message_str += f"Topics: {','.join(memory.topics)}\n"
            system_message_str += "\n"
        system_message_str = system_message_str.strip()
        system_message_str += "\n</user_memories>\n\n"
        system_message_str += "REMEMBER: Only return the IDs of the memories that are related to the query."

        if response_format == {"type": "json_object"}:
            system_message_str += "\n" + get_json_output_prompt(MemorySearchResponse)  # type: ignore

        messages_for_model = [
            Message(role="system", content=system_message_str),
            Message(
                role="user",
                content=f"Return the IDs of the memories related to the following query: {query}",
            ),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model.response(messages=messages_for_model, response_format=response_format)
        log_debug("Search for memories complete", center=True)

        memory_search: Optional[MemorySearchResponse] = None
        # If the model natively supports structured outputs, the parsed value is already in the structured format
        if (
            model.supports_native_structured_outputs
            and response.parsed is not None
            and isinstance(response.parsed, MemorySearchResponse)
        ):
            memory_search = response.parsed

        # Otherwise convert the response to the structured format
        if isinstance(response.content, str):
            try:
                memory_search = parse_response_model_str(response.content, MemorySearchResponse)  # type: ignore

                # Update RunResponse
                if memory_search is None:
                    log_warning("Failed to convert memory_search response to MemorySearchResponse")
                    return []
            except Exception as e:
                log_warning(f"Failed to convert memory_search response to MemorySearchResponse: {e}")
                return []

        memories_to_return = []
        if memory_search:
            for memory_id in memory_search.memory_ids:
                memories_to_return.append(user_memories[memory_id])
        return memories_to_return[:limit]

    def _get_last_n_memories(self, user_id: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Get the most recent user memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            A list of the most recent UserMemory objects.
        """
        if not self.memories:
            return []

        memories_dict = self.memories.get(user_id, {})

        # Sort memories by last_updated timestamp if available
        if memories_dict:
            # Convert to list of values for sorting
            memories_list = list(memories_dict.values())

            # Sort memories by last_updated timestamp (newest first)
            # If last_updated is None, place at the beginning of the list
            sorted_memories_list = sorted(
                memories_list,
                key=lambda memory: memory.last_updated or datetime.min,
            )
        else:
            sorted_memories_list = []

        if limit is not None and limit > 0:
            sorted_memories_list = sorted_memories_list[-limit:]

        return sorted_memories_list

    def _get_first_n_memories(self, user_id: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Get the oldest user memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            A list of the oldest UserMemory objects.
        """
        if not self.memories:
            return []

        memories_dict = self.memories.get(user_id, {})
        # Sort memories by last_updated timestamp if available
        if memories_dict:
            # Convert to list of values for sorting
            memories_list = list(memories_dict.values())

            # Sort memories by last_updated timestamp (oldest first)
            # If last_updated is None, place at the end of the list
            sorted_memories_list = sorted(
                memories_list,
                key=lambda memory: memory.last_updated or datetime.max,
            )

        else:
            sorted_memories_list = []

        if limit is not None and limit > 0:
            sorted_memories_list = sorted_memories_list[:limit]

        return sorted_memories_list

    def clear(self) -> None:
        """Clears the memory."""
        if self.db:
            self.db.clear()
        self.memories = {}
        self.summaries = {}
        self.runs = {}

    def deep_copy(self) -> "Memory":
        from copy import deepcopy

        # Create a shallow copy of the object
        copied_obj = self.__class__(**self.to_dict())

        # Manually deepcopy fields that are known to be safe
        for field_name, field_value in self.__dict__.items():
            if field_name not in ["db", "memory_manager", "summary_manager"]:
                try:
                    setattr(copied_obj, field_name, deepcopy(field_value))
                except Exception as e:
                    logger.warning(f"Failed to deepcopy field: {field_name} - {e}")
                    setattr(copied_obj, field_name, field_value)

        copied_obj.db = self.db
        copied_obj.memory_manager = self.memory_manager
        copied_obj.summary_manager = self.summary_manager

        return copied_obj

    # -*- Team Functions
    def add_interaction_to_team_context(
        self, session_id: str, member_name: str, task: str, run_response: Union[RunResponse, TeamRunResponse]
    ) -> None:
        if self.team_context is None:
            self.team_context = {}
        if session_id not in self.team_context:
            self.team_context[session_id] = TeamContext()
        self.team_context[session_id].member_interactions.append(
            TeamMemberInteraction(
                member_name=member_name,
                task=task,
                response=run_response,
            )
        )
        log_debug(f"Updated team context with member name: {member_name}")

    def set_team_context_text(self, session_id: str, text: Union[dict, str]) -> None:
        if self.team_context is None:
            self.team_context = {}
        if session_id not in self.team_context:
            self.team_context[session_id] = TeamContext()
        if isinstance(text, dict):
            if self.team_context[session_id].text is not None:
                try:
                    current_context = json.loads(self.team_context[session_id].text)  # type: ignore
                except Exception:
                    current_context = {}
            else:
                current_context = {}
            current_context.update(text)
            self.team_context[session_id].text = json.dumps(current_context)
        else:
            # If string then we overwrite the current context
            self.team_context[session_id].text = text

    def get_team_context_str(self, session_id: str) -> str:
        if not self.team_context:
            return ""
        session_team_context = self.team_context.get(session_id, None)
        if session_team_context and session_team_context.text:
            return f"<team context>\n{session_team_context.text}\n</team context>\n"
        return ""

    def get_team_member_interactions_str(self, session_id: str) -> str:
        if not self.team_context:
            return ""
        team_member_interactions_str = ""
        session_team_context = self.team_context.get(session_id, None)
        if session_team_context and session_team_context.member_interactions:
            team_member_interactions_str += "<member interactions>\n"

            for interaction in session_team_context.member_interactions:
                response_dict = interaction.response.to_dict()
                response_content = (
                    response_dict.get("content")
                    or ",".join([tool.get("content", "") for tool in response_dict.get("tools", [])])
                    or ""
                )
                team_member_interactions_str += f"Member: {interaction.member_name}\n"
                team_member_interactions_str += f"Task: {interaction.task}\n"
                team_member_interactions_str += f"Response: {response_content}\n"
                team_member_interactions_str += "\n"
            team_member_interactions_str += "</member interactions>\n"
        return team_member_interactions_str

    def get_team_context_images(self, session_id: str) -> List[ImageArtifact]:
        if not self.team_context:
            return []
        images = []
        session_team_context = self.team_context.get(session_id, None)
        if session_team_context and session_team_context.member_interactions:
            for interaction in session_team_context.member_interactions:
                if interaction.response.images:
                    images.extend(interaction.response.images)
        return images

    def get_team_context_videos(self, session_id: str) -> List[VideoArtifact]:
        if not self.team_context:
            return []
        videos = []
        session_team_context = self.team_context.get(session_id, None)
        if session_team_context and session_team_context.member_interactions:
            for interaction in session_team_context.member_interactions:
                if interaction.response.videos:
                    videos.extend(interaction.response.videos)
        return videos

    def get_team_context_audio(self, session_id: str) -> List[AudioArtifact]:
        if not self.team_context:
            return []
        audio = []
        session_team_context = self.team_context.get(session_id, None)
        if session_team_context and session_team_context.member_interactions:
            for interaction in session_team_context.member_interactions:
                if interaction.response.audio:
                    audio.extend(interaction.response.audio)
        return audio

    def __deepcopy__(self, memo):
        from copy import deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        copied_obj = cls.__new__(cls)
        memo[id(self)] = copied_obj

        # Deep copy attributes
        for k, v in self.__dict__.items():
            # Reuse db
            if k in {"db", "memory_manager", "summary_manager"}:
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        return copied_obj
