from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional

from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.response import RunResponse
from agno.session.summarizer import SessionSummarizer, SessionSummary
from agno.utils.log import log_debug, log_warning


@dataclass
class AgentSession:
    """Agent Session that is stored in the database"""

    # Session UUID
    session_id: str
    # ID of the team session this agent session is associated with
    team_session_id: Optional[str] = None

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
    # Extra Data stored with this agent
    extra_data: Optional[Dict[str, Any]] = None
    # Agent Data: agent_id, name and model
    agent_data: Optional[Dict[str, Any]] = None
    # List of all messages in the session
    chat_history: Optional[list[Message]] = None
    # List of all runs in the session
    runs: Optional[list[Dict[str, Any]]] = None
    # Summary of the session
    summary: Optional[SessionSummary] = None

    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def telemetry_data(self) -> Dict[str, Any]:
        return {
            "model": self.agent_data.get("model") if self.agent_data else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[AgentSession]:
        if data is None or data.get("session_id") is None:
            log_warning("AgentSession is missing session_id")
            return None
        return cls(
            session_id=data.get("session_id"),  # type: ignore
            agent_id=data.get("agent_id"),
            team_session_id=data.get("team_session_id"),
            user_id=data.get("user_id"),
            workflow_id=data.get("workflow_id"),
            team_id=data.get("team_id"),
            agent_data=data.get("agent_data"),
            session_data=data.get("session_data"),
            extra_data=data.get("extra_data"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            chat_history=data.get("chat_history"),
            runs=data.get("runs"),
            summary=data.get("summary"),
        )

    def add_run(self, run: RunResponse, run_data: Dict[str, Any]):
        """Adds a RunResponse, together with some calculated data, to the runs list."""

        messages = run.messages
        for m in messages:
            if m.metrics is not None:
                m.metrics.timer = None

        if not self.runs:
            self.runs = []

        self.runs.append({"run": run.to_dict(), "run_data": run_data})

        log_debug("Added RunResponse to Agent Session")

    def get_messages_from_last_n_runs(
        self,
        session_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        last_n: Optional[int] = None,
        skip_role: Optional[str] = None,
        skip_status: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Returns the messages from the last_n runs, excluding previously tagged history messages.
        Args:
            session_id: The session id to get the messages from.
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
        session_runs = self.runs
        for run_response in session_runs[::-1]:
            if run_response and run_response.messages:
                for message in run_response.messages:
                    if message.tool_calls:
                        for tool_call in message.tool_calls:
                            tool_calls.append(tool_call)
                            if num_calls and len(tool_calls) >= num_calls:
                                return tool_calls
        return tool_calls

    def get_messages_for_session(
        self,
        session_id: str,
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

    # Session Summary functions
    def create_session_summary(
        self, session_id: str, user_id: Optional[str] = None, summary_manager: Optional[SessionSummarizer] = None
    ) -> Optional[SessionSummary]:
        """Creates a summary of the session"""
        from datetime import datetime

        if not summary_manager:
            raise ValueError("Summarizer not initialized")

        if user_id is None:
            user_id = "default"

        summary_response = summary_manager.run(conversation=self.get_messages_for_session(session_id=session_id))
        if summary_response is None:
            return None
        session_summary = SessionSummary(
            summary=summary_response.summary, topics=summary_response.topics, last_updated=datetime.now()
        )
        self.summary = session_summary  # type: ignore

        return session_summary

    async def acreate_session_summary(
        self, session_id: str, summary_manager: Optional[SessionSummarizer] = None
    ) -> Optional[SessionSummary]:
        """Creates a summary of the session"""
        from datetime import datetime

        if not summary_manager:
            raise ValueError("Summarizer not initialized")

        summary_response = await summary_manager.arun(conversation=self.get_messages_for_session(session_id=session_id))
        if summary_response is None:
            return None
        session_summary = SessionSummary(
            summary=summary_response.summary, topics=summary_response.topics, last_updated=datetime.now()
        )
        self.summary = session_summary  # type: ignore

        return session_summary

    def get_session_summary(self) -> Optional[SessionSummary]:
        """Get the session summary for the session"""

        if self.summary is None:
            return None
        return self.summary
