from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.summary import SessionSummary
from agno.utils.log import log_debug, log_warning


@dataclass
class AgentSession:
    """Agent Session that is stored in the database"""

    # Session UUID
    session_id: str

    # ID of the agent that this session is associated with
    agent_id: Optional[str] = None
    # ID of the team that this session is associated with
    team_id: Optional[str] = None
    # # ID of the user interacting with this agent
    user_id: Optional[str] = None
    # ID of the workflow that this session is associated with
    workflow_id: Optional[str] = None

    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Metadata stored with this agent
    metadata: Optional[Dict[str, Any]] = None
    # Agent Data: agent_id, name and model
    agent_data: Optional[Dict[str, Any]] = None
    # List of all runs in the session
    runs: Optional[List[RunOutput]] = None
    # Summary of the session
    summary: Optional["SessionSummary"] = None

    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        session_dict = asdict(self)

        session_dict["runs"] = [run.to_dict() for run in self.runs] if self.runs else None
        session_dict["summary"] = self.summary.to_dict() if self.summary else None

        return session_dict

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[AgentSession]:
        if data is None or data.get("session_id") is None:
            log_warning("AgentSession is missing session_id")
            return None

        runs = data.get("runs")
        if runs is not None and isinstance(runs[0], dict):
            runs = [RunOutput.from_dict(run) for run in runs]

        summary = data.get("summary")
        if summary is not None and isinstance(summary, dict):
            summary = SessionSummary.from_dict(summary)

        metadata = data.get("metadata")

        return cls(
            session_id=data.get("session_id"),  # type: ignore
            agent_id=data.get("agent_id"),
            user_id=data.get("user_id"),
            workflow_id=data.get("workflow_id"),
            team_id=data.get("team_id"),
            agent_data=data.get("agent_data"),
            session_data=data.get("session_data"),
            metadata=metadata,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            runs=runs,
            summary=summary,
        )

    def upsert_run(self, run: RunOutput):
        """Adds a RunOutput, together with some calculated data, to the runs list."""
        messages = run.messages
        for m in messages or []:
            if m.metrics is not None:
                m.metrics.duration = None

        if not self.runs:
            self.runs = []

        for i, existing_run in enumerate(self.runs or []):
            if existing_run.run_id == run.run_id:
                self.runs[i] = run
                break
        else:
            self.runs.append(run)

        log_debug("Added RunOutput to Agent Session")

    def get_run(self, run_id: str) -> Optional[RunOutput]:
        for run in self.runs or []:
            if run.run_id == run_id:
                return run
        return None

    def get_messages_from_last_n_runs(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        last_n: Optional[int] = None,
        skip_role: Optional[str] = None,
        skip_status: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Returns the messages from the last_n runs, excluding previously tagged history messages.
        Args:
            agent_id: The id of the agent to get the messages from.
            team_id: The id of the team to get the messages from.
            last_n: The number of runs to return from the end of the conversation. Defaults to all runs.
            skip_role: Skip messages with this role.
            skip_status: Skip messages with this status.
            skip_history_messages: Skip messages that were tagged as history in previous runs.
        Returns:
            A list of Messages from the specified runs, excluding history messages.
        """
        if not self.runs:
            return []

        if skip_status is None:
            skip_status = [RunStatus.paused, RunStatus.cancelled, RunStatus.error]

        session_runs = self.runs
        # Filter by agent_id and team_id
        if agent_id:
            session_runs = [run for run in session_runs if hasattr(run, "agent_id") and run.agent_id == agent_id]  # type: ignore
        if team_id:
            session_runs = [run for run in session_runs if hasattr(run, "team_id") and run.team_id == team_id]  # type: ignore

        # Filter by status
        session_runs = [run for run in session_runs if hasattr(run, "status") and run.status not in skip_status]  # type: ignore

        # Filter by last_n
        runs_to_process = session_runs[-last_n:] if last_n is not None else session_runs
        messages_from_history = []
        system_message = None
        for run_response in runs_to_process:
            if not (run_response and run_response.messages):
                continue

            for message in run_response.messages or []:
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

    def get_tool_calls(self, num_calls: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns a list of tool calls from the messages"""

        tool_calls = []
        if self.runs:
            session_runs = self.runs
            for run_response in session_runs[::-1]:
                if run_response and run_response.messages:
                    for message in run_response.messages or []:
                        if message.tool_calls:
                            for tool_call in message.tool_calls:
                                tool_calls.append(tool_call)
                                if num_calls and len(tool_calls) >= num_calls:
                                    return tool_calls
        return tool_calls

    def get_messages_for_session(
        self,
        user_role: str = "user",
        assistant_role: Optional[List[str]] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Returns a list of messages for the session that iterate through user message and assistant response."""

        if assistant_role is None:
            # TODO: Check if we still need CHATBOT as a role
            assistant_role = ["assistant", "model", "CHATBOT"]

        final_messages: List[Message] = []
        session_runs = self.runs
        if not session_runs:
            return []

        for run_response in session_runs:
            if run_response and run_response.messages:
                user_message_from_run = None
                assistant_message_from_run = None

                # Start from the beginning to look for the user message
                for message in run_response.messages or []:
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

    def get_session_summary(self) -> Optional[SessionSummary]:
        """Get the session summary for the session"""

        if self.summary is None:
            return None
        return self.summary

    # Chat History functions
    def get_chat_history(self) -> List[Message]:
        """Get the chat history for the session"""

        messages = []
        for run in self.runs or []:
            messages.extend([msg for msg in run.messages or [] if not msg.from_history])
        return messages
