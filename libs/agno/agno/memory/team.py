from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ConfigDict

from agno.media import AudioArtifact, ImageArtifact, VideoArtifact
from agno.memory.agent import AgentRun
from agno.models.message import Message
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.utils.log import get_logger, logger

@dataclass
class TeamRun:
    message: Optional[Message] = None
    member_runs: Optional[List[AgentRun]] = None
    response: Optional[TeamRunResponse] = None

    def to_dict(self) -> Dict[str, Any]:
        response = {
            "message": self.message.to_dict() if self.message else None,
            "member_responses": [run.to_dict() for run in self.member_runs] if self.member_runs else None,
            "response": self.response.to_dict() if self.response else None,
        }
        return {k: v for k, v in response.items() if v is not None}


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

    team_context: Optional[TeamContext] = None

    # True when memory is being updated
    updating_memory: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_dict(self) -> Dict[str, Any]:
        _memory_dict = {}
        # Add messages if they exist
        if self.messages is not None:
            _memory_dict["messages"] = [message.to_dict() for message in self.messages]
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
        get_logger().debug(f"Updated team context with member name: {member_name}")

    def set_team_context_text(self, text: str) -> None:
        if self.team_context:
            self.team_context.text = text
        else:
            self.team_context = TeamContext(text=text)

    def get_team_context_str(self, include_member_interactions: bool = False) -> str:
        team_context_str = ""
        if self.team_context:
            if self.team_context.text:
                team_context_str += f"<team context>\n{self.team_context.text}\n</team context>\n"

            if include_member_interactions and self.team_context.member_interactions:
                team_context_str += "<member interactions>\n"
                for interaction in self.team_context.member_interactions:
                    response_dict = interaction.response.to_dict()

                    team_context_str += f"Member: {interaction.member_name}\n"
                    team_context_str += f"Task: {interaction.task}\n"
                    team_context_str += f"Response: {response_dict.get('content', '')}\n"
                    team_context_str += "\n"
                team_context_str += "</member interactions>\n"
        return team_context_str

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

    def add_team_run(self, agent_run: TeamRun) -> None:
        """Adds an AgentRun to the runs list."""
        self.runs.append(agent_run)
        get_logger().debug("Added AgentRun to AgentMemory")

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
                    get_logger().info("Updating system message in memory with new content")
                    self.messages[system_message_index] = message
            else:
                # Add the system message to the messages list
                self.messages.insert(0, message)

    def add_messages(self, messages: List[Message]) -> None:
        """Add a list of messages to the messages list."""
        self.messages.extend(messages)
        get_logger().debug(f"Added {len(messages)} Messages to AgentMemory")

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

        get_logger().debug(f"Getting messages from previous runs: {len(messages_from_history)}")
        return messages_from_history

    def get_all_messages(
        self
    ) -> List[Tuple[Message, Message]]:
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

