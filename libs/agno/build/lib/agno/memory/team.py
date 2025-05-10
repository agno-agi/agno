from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ConfigDict

from agno.media import AudioArtifact, ImageArtifact, VideoArtifact
from agno.memory.agent import AgentRun, MemoryRetrieval
from agno.memory.classifier import MemoryClassifier
from agno.memory.db import MemoryDb
from agno.memory.manager import MemoryManager
from agno.memory.memory import Memory
from agno.models.message import Message
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.utils.log import log_debug, log_info, log_warning


@dataclass
class TeamRun:
    message: Optional[Message] = None
    member_runs: Optional[List[AgentRun]] = None
    response: Optional[TeamRunResponse] = None

    def to_dict(self) -> Dict[str, Any]:
        message = self.message.to_dict() if self.message else None
        member_responses = [run.to_dict() for run in self.member_runs] if self.member_runs else None
        response = self.response.to_dict() if self.response else None
        return {
            "message": message,
            "member_responses": member_responses,
            "response": response,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeamRun":
        message = Message.model_validate(data.get("message")) if data.get("message") else None
        member_runs = (
            [AgentRun.model_validate(run) for run in data.get("member_runs", [])] if data.get("member_runs") else None
        )
        response = TeamRunResponse.from_dict(data.get("response", {})) if data.get("response") else None
        return cls(message=message, member_runs=member_runs, response=response)


@dataclass
class TeamMemberInteraction:
    member_name: str
    task: str
    response: RunResponse


@dataclass
class TeamContext:
    # List of team member interaction, represented as a request and a response
    member_interactions: List[TeamMemberInteraction] = field(default_factory=list)
    text: Optional[str] = None


@dataclass
class TeamMemory:
    # Runs between the user and agent
    runs: List[TeamRun] = field(default_factory=list)
    # List of messages sent to the model
    messages: List[Message] = field(default_factory=list)
    # If True, update the system message when it changes
    update_system_message_on_change: bool = True

    team_context: Optional[TeamContext] = None

    # Create and store personalized memories for this user
    create_user_memories: bool = False
    # Update memories for the user after each run
    update_user_memories_after_run: bool = True

    # MemoryDb to store personalized memories
    db: Optional[MemoryDb] = None
    # User ID for the personalized memories
    user_id: Optional[str] = None
    retrieval: MemoryRetrieval = MemoryRetrieval.last_n
    memories: Optional[List[Memory]] = None
    classifier: Optional[MemoryClassifier] = None
    manager: Optional[MemoryManager] = None

    num_memories: Optional[int] = None

    # True when memory is being updated
    updating_memory: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_dict(self) -> Dict[str, Any]:
        _memory_dict = {}
        for key, value in self.__dict__.items():
            if value is not None and key in [
                "update_system_message_on_change",
                "create_user_memories",
                "update_user_memories_after_run",
                "user_id",
                "num_memories",
            ]:
                _memory_dict[key] = value

        # Add messages if they exist
        if self.messages is not None:
            _memory_dict["messages"] = [message.to_dict() for message in self.messages]
        # Add memories if they exist
        if self.memories is not None:
            _memory_dict["memories"] = [memory.to_dict() for memory in self.memories]
        # Add runs if they exist
        if self.runs is not None:
            _memory_dict["runs"] = [run.to_dict() for run in self.runs]
        return _memory_dict

    def add_interaction_to_team_context(self, member_name: str, task: str, run_response: RunResponse) -> None:
        if self.team_context is None:
            self.team_context = TeamContext()
        self.team_context.member_interactions.append(
            TeamMemberInteraction(
                member_name=member_name,
                task=task,
                response=run_response,
            )
        )
        log_debug(f"Updated team context with member name: {member_name}")

    def set_team_context_text(self, text: str) -> None:
        if self.team_context:
            self.team_context.text = text
        else:
            self.team_context = TeamContext(text=text)

    def get_team_context_str(self) -> str:
        if self.team_context and self.team_context.text:
            return f"<team_context>\n{self.team_context.text}\n</team_context>"
        return ""

    def get_team_member_interactions_str(self) -> str:
        team_member_interactions_str = ""
        if self.team_context and self.team_context.member_interactions:
            team_member_interactions_str += "<member_interactions>\n"

            for interaction in self.team_context.member_interactions:
                team_member_interactions_str += f"Member: {interaction.member_name}\n"
                team_member_interactions_str += f"Task: {interaction.task}\n"
                team_member_interactions_str += f"Response: {interaction.response.to_dict().get('content', '')}\n"
                team_member_interactions_str += "\n"
            team_member_interactions_str += "</member_interactions>\n"
        return team_member_interactions_str

    def get_team_context_images(self) -> List[ImageArtifact]:
        images = []
        if self.team_context and self.team_context.member_interactions:
            for interaction in self.team_context.member_interactions:
                if interaction.response.images:
                    images.extend(interaction.response.images)
        return images

    def get_team_context_videos(self) -> List[VideoArtifact]:
        videos = []
        if self.team_context and self.team_context.member_interactions:
            for interaction in self.team_context.member_interactions:
                if interaction.response.videos:
                    videos.extend(interaction.response.videos)
        return videos

    def get_team_context_audio(self) -> List[AudioArtifact]:
        audio = []
        if self.team_context and self.team_context.member_interactions:
            for interaction in self.team_context.member_interactions:
                if interaction.response.audio:
                    audio.extend(interaction.response.audio)
        return audio

    def add_team_run(self, team_run: TeamRun) -> None:
        """Adds an TeamRun to the runs list."""
        self.runs.append(team_run)
        log_debug("Added TeamRun to TeamMemory")

    def add_system_message(self, message: Message, system_message_role: str = "system") -> None:
        """Add the system messages to the messages list"""
        # If this is the first run in the session, add the system message to the messages list
        if len(self.messages) == 0:
            if message is not None:
                self.messages.append(message)
        # If there are messages in the memory, check if the system message is already in the memory
        # If it is not, add the system message to the messages list
        # If it is, update the system message if content has changed and update_system_message_on_change is True
        else:
            system_message_index = next((i for i, m in enumerate(self.messages) if m.role == system_message_role), None)
            # Update the system message in memory if content has changed
            if system_message_index is not None:
                if (
                    self.messages[system_message_index].content != message.content
                    and self.update_system_message_on_change
                ):
                    log_info("Updating system message in memory with new content")
                    self.messages[system_message_index] = message
            else:
                # Add the system message to the messages list
                self.messages.insert(0, message)

    def add_messages(self, messages: List[Message]) -> None:
        """Add a list of messages to the messages list."""
        self.messages.extend(messages)
        log_debug(f"Added {len(messages)} Messages to TeamMemory")

    def get_messages(self) -> List[Dict[str, Any]]:
        """Returns the messages list as a list of dictionaries."""
        return [message.model_dump() for message in self.messages]

    def get_messages_from_last_n_runs(
        self, last_n: Optional[int] = None, skip_role: Optional[str] = None
    ) -> List[Message]:
        """Returns the messages from the last_n runs, excluding previously tagged history messages.

        Args:
            last_n: The number of runs to return from the end of the conversation.
            skip_role: Skip messages with this role.

        Returns:
            A list of Messages from the specified runs, excluding history messages.
        """
        if not self.runs:
            return []

        runs_to_process = self.runs if last_n is None else self.runs[-last_n:]
        messages_from_history = []

        for run in runs_to_process:
            if not (run.response and run.response.messages):
                continue

            for message in run.response.messages:
                # Skip messages with specified role
                if skip_role and message.role == skip_role:
                    continue
                # Skip messages that were tagged as history in previous runs
                if hasattr(message, "from_history") and message.from_history:
                    continue

                messages_from_history.append(message)

        log_debug(f"Getting messages from previous runs: {len(messages_from_history)}")
        return messages_from_history

    def get_all_messages(self) -> List[Tuple[Message, Message]]:
        """Returns a list of tuples of (user message, assistant response)."""

        assistant_role = ["assistant", "model", "CHATBOT"]

        runs_as_message_pairs: List[Tuple[Message, Message]] = []
        for run in self.runs:
            if run.response and run.response.messages:
                user_message_from_run = None
                assistant_message_from_run = None

                # Start from the beginning to look for the user message
                for message in run.response.messages:
                    if message.role == "user":
                        user_message_from_run = message
                        break

                # Start from the end to look for the assistant response
                for message in run.response.messages[::-1]:
                    if message.role in assistant_role:
                        assistant_message_from_run = message
                        break

                if user_message_from_run and assistant_message_from_run:
                    runs_as_message_pairs.append((user_message_from_run, assistant_message_from_run))
        return runs_as_message_pairs

    def load_user_memories(self) -> None:
        """Load memories from memory db for this user."""

        if self.db is None:
            return

        try:
            if self.retrieval in (MemoryRetrieval.last_n, MemoryRetrieval.first_n):
                memory_rows = self.db.read_memories(
                    user_id=self.user_id,
                    limit=self.num_memories,
                    sort="asc" if self.retrieval == MemoryRetrieval.first_n else "desc",
                )
            else:
                raise NotImplementedError("Semantic retrieval not yet supported.")
        except Exception as e:
            log_debug(f"Error reading memory: {e}")
            return

        # Clear the existing memories
        self.memories = []

        # No memories to load
        if memory_rows is None or len(memory_rows) == 0:
            return

        for row in memory_rows:
            try:
                self.memories.append(Memory.model_validate(row.memory))
            except Exception as e:
                log_warning(f"Error loading memory: {e}")
                continue

    def should_update_memory(self, input: str) -> bool:
        """Determines if a message should be added to the memory db."""
        from agno.memory.classifier import MemoryClassifier

        if self.classifier is None:
            self.classifier = MemoryClassifier()

        self.classifier.existing_memories = self.memories
        classifier_response = self.classifier.run(input)
        if classifier_response == "yes":
            return True
        return False

    async def ashould_update_memory(self, input: str) -> bool:
        """Determines if a message should be added to the memory db."""
        from agno.memory.classifier import MemoryClassifier

        if self.classifier is None:
            self.classifier = MemoryClassifier()

        self.classifier.existing_memories = self.memories
        classifier_response = await self.classifier.arun(input)
        if classifier_response == "yes":
            return True
        return False

    def update_memory(self, input: str, force: bool = False) -> Optional[str]:
        """Creates a memory from a message and adds it to the memory db."""

        if input is None or not isinstance(input, str):
            return "Invalid message content"

        if self.db is None:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        self.updating_memory = True

        # Check if this user message should be added to long term memory
        should_update_memory = force or self.should_update_memory(input=input)
        log_debug(f"Update memory: {should_update_memory}")

        if not should_update_memory:
            log_debug("Memory update not required")
            return "Memory update not required"

        if self.manager is None:
            self.manager = MemoryManager(user_id=self.user_id, db=self.db)

        else:
            self.manager.db = self.db
            self.manager.user_id = self.user_id

        response = self.manager.run(input)
        self.load_user_memories()
        self.updating_memory = False
        return response

    async def aupdate_memory(self, input: str, force: bool = False) -> Optional[str]:
        """Creates a memory from a message and adds it to the memory db."""
        if input is None or not isinstance(input, str):
            return "Invalid message content"

        if self.db is None:
            log_warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        self.updating_memory = True

        # Check if this user message should be added to long term memory
        should_update_memory = force or await self.ashould_update_memory(input=input)
        log_debug(f"Async update memory: {should_update_memory}")

        if not should_update_memory:
            log_debug("Memory update not required")
            return "Memory update not required"

        if self.manager is None:
            self.manager = MemoryManager(user_id=self.user_id, db=self.db)

        else:
            self.manager.db = self.db
            self.manager.user_id = self.user_id

        response = await self.manager.arun(input)
        self.load_user_memories()
        self.updating_memory = False
        return response

    def deep_copy(self) -> "TeamMemory":
        from copy import deepcopy

        # Create a shallow copy of the object
        copied_obj = self.__class__(**self.to_dict())

        # Manually deepcopy fields that are known to be safe
        for field_name, field_value in self.__dict__.items():
            if field_name not in ["db", "classifier", "manager"]:
                try:
                    setattr(copied_obj, field_name, deepcopy(field_value))
                except Exception as e:
                    log_warning(f"Failed to deepcopy field: {field_name} - {e}")
                    setattr(copied_obj, field_name, field_value)

        copied_obj.db = self.db
        copied_obj.classifier = self.classifier
        copied_obj.manager = self.manager

        return copied_obj
