from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.run.agent import RunOutput, RunStatus
from agno.run.team import TeamRunOutput
from agno.session.summary import SessionSummary
from agno.utils.log import log_debug, log_warning


@dataclass
class TeamSession:
    """Team Session that is stored in the database"""

    # Session UUID
    session_id: str

    # ID of the team that this session is associated with
    team_id: Optional[str] = None
    # ID of the user interacting with this team
    user_id: Optional[str] = None
    # ID of the workflow that this session is associated with
    workflow_id: Optional[str] = None

    # Team Data: agent_id, name and model
    team_data: Optional[Dict[str, Any]] = None
    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Metadata stored with this team
    metadata: Optional[Dict[str, Any]] = None
    # List of all runs in the session
    runs: Optional[list[Union[TeamRunOutput, RunOutput]]] = None
    # Summary of the session
    summary: Optional[SessionSummary] = None

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
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[TeamSession]:
        if data is None or data.get("session_id") is None:
            log_warning("TeamSession is missing session_id")
            return None

        summary = data.get("summary")
        if summary is not None and isinstance(summary, dict):
            data["summary"] = SessionSummary.from_dict(data["summary"])  # type: ignore

        runs = data.get("runs")
        serialized_runs: List[Union[TeamRunOutput, RunOutput]] = []
        if runs is not None and isinstance(runs[0], dict):
            for run in runs:
                if "agent_id" in run:
                    serialized_runs.append(RunOutput.from_dict(run))
                elif "team_id" in run:
                    serialized_runs.append(TeamRunOutput.from_dict(run))

        return cls(
            session_id=data.get("session_id"),  # type: ignore
            team_id=data.get("team_id"),
            user_id=data.get("user_id"),
            workflow_id=data.get("workflow_id"),
            team_data=data.get("team_data"),
            session_data=data.get("session_data"),
            metadata=data.get("metadata"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            runs=serialized_runs,
            summary=data.get("summary"),
        )

    def get_run(self, run_id: str) -> Optional[Union[TeamRunOutput, RunOutput]]:
        for run in self.runs or []:
            if run.run_id == run_id:
                return run
        return None

    def upsert_run(self, run_response: Union[TeamRunOutput, RunOutput]):
        """Adds a RunOutput, together with some calculated data, to the runs list."""
        messages = run_response.messages

        # Clear message timer before storage
        for m in messages or []:
            if m.metrics is not None and hasattr(m.metrics, "timer"):
                m.metrics.timer = None

        if not self.runs:
            self.runs = []

        for i, existing_run in enumerate(self.runs or []):
            if existing_run.run_id == run_response.run_id:
                self.runs[i] = run_response
                break
        else:
            self.runs.append(run_response)

        log_debug("Added RunOutput to Team Session")

    def get_messages(
        self,
        team_id: Optional[str] = None,
        member_ids: Optional[List[str]] = None,
        last_n_runs: Optional[int] = None,
        limit: Optional[int] = None,
        skip_roles: Optional[List[str]] = None,
        skip_statuses: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
        skip_member_messages: bool = True,
    ) -> List[Message]:
        """Returns the messages belonging to the session that fit the given criteria.

        Args:
            team_id: The id of the team to get the messages from.
            member_ids: The ids of the members to get the messages from.
            last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
            limit: The number of messages to return, counting from the latest. Defaults to all messages.
            skip_roles: Skip messages with these roles.
            skip_statuses: Skip messages with these statuses.
            skip_history_messages: Skip messages that were tagged as history in previous runs.
            skip_member_messages: Skip messages created by members of the team.

        Returns:
            A list of Messages belonging to the session.
        """

        def _should_skip_message(
            message: Message, skip_roles: Optional[List[str]] = None, skip_history_messages: bool = True
        ) -> bool:
            """Processes a message for history"""
            # Skip messages that were tagged as history in previous runs
            if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                return True

            # Skip messages with specified role
            if skip_roles and message.role in skip_roles:
                return True
            return False

        if member_ids is not None and skip_member_messages:
            log_debug("Member IDs to filter by were provided. The skip_member_messages flag will be ignored.")
            skip_member_messages = False

        if not self.runs:
            return []

        if skip_statuses is None:
            skip_statuses = [RunStatus.paused, RunStatus.cancelled, RunStatus.error]

        session_runs = self.runs

        # Filter by team_id and member_ids
        if team_id:
            session_runs = [run for run in session_runs if hasattr(run, "team_id") and run.team_id == team_id]  # type: ignore
        if member_ids:
            filtered_runs = []
            for run in session_runs:
                if hasattr(run, "agent_id") and run.agent_id in member_ids:  # type: ignore
                    filtered_runs.append(run)
                elif hasattr(run, "member_responses"):
                    for member_run in run.member_responses:
                        if hasattr(member_run, "agent_id") and member_run.agent_id in member_ids:  # type: ignore
                            filtered_runs.append(member_run)
            session_runs = filtered_runs

        if skip_member_messages:
            # Filter for the top-level runs (main team runs or agent runs when sharing session)
            session_runs = [run for run in session_runs if run.parent_run_id is None]  # type: ignore

        # Filter by status
        session_runs = [run for run in session_runs if hasattr(run, "status") and run.status not in skip_statuses]  # type: ignore

        messages_from_history = []
        system_message = None

        # Limit the number of messages returned if limit is set
        if limit is not None:
            for run_response in session_runs:
                if not run_response or not run_response.messages:
                    continue

                for message in run_response.messages or []:
                    if _should_skip_message(message, skip_roles, skip_history_messages):
                        continue

                    if message.role == "system":
                        # Only add the system message once
                        if system_message is None:
                            system_message = message
                    else:
                        messages_from_history.append(message)

            if system_message:
                messages_from_history = [system_message] + messages_from_history[
                    -(limit - 1) :
                ]  # Grab one less message then add the system message
            else:
                messages_from_history = messages_from_history[-limit:]

            # Remove tool result messages that don't have an associated assistant message with tool calls
            while len(messages_from_history) > 0 and messages_from_history[0].role == "tool":
                messages_from_history.pop(0)
        else:
            # Filter by last_n runs
            runs_to_process = session_runs[-last_n_runs:] if last_n_runs is not None else session_runs

            for run_response in runs_to_process:
                if not (run_response and run_response.messages):
                    continue

                for message in run_response.messages or []:
                    if _should_skip_message(message, skip_roles, skip_history_messages):
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

    def get_chat_history(self, last_n_runs: Optional[int] = None) -> List[Message]:
        """Return the chat history (user and assistant messages) for the session.
        Use get_messages() for more filtering options.

        Args:
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.

        Returns:
            A list of user and assistant Messages belonging to the session.
        """
        return self.get_messages(skip_roles=["system", "tool"], skip_member_messages=True, last_n_runs=last_n_runs)

    def get_tool_calls(self, num_calls: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns a list of tool calls from the messages"""

        tool_calls = []
        session_runs = self.runs
        if session_runs is None:
            return []

        for run_response in session_runs[::-1]:
            if run_response and run_response.messages:
                for message in run_response.messages or []:
                    if message.tool_calls:
                        for tool_call in message.tool_calls:
                            tool_calls.append(tool_call)
                            if num_calls and len(tool_calls) >= num_calls:
                                return tool_calls
        return tool_calls

    def get_team_history(self, num_runs: Optional[int] = None) -> List[Tuple[str, str]]:
        """Get team history as structured data (input, response pairs) -> This is the history of the team leader, not the members.

        Args:
            num_runs: Number of recent runs to include. If None, returns all available history.
        """
        if not self.runs:
            return []

        from agno.run.base import RunStatus

        # Get completed runs only (exclude current/pending run)
        completed_runs = [run for run in self.runs if run.status == RunStatus.completed and run.parent_run_id is None]

        if num_runs is not None and len(completed_runs) > num_runs:
            recent_runs = completed_runs[-num_runs:]
        else:
            recent_runs = completed_runs

        if not recent_runs:
            return []

        # Return structured data as list of (input, response) tuples
        history_data = []
        for run in recent_runs:
            # Get input
            input_str = ""
            if run.input:
                input_str = run.input.input_content_string()

            # Get response
            response_str = ""
            if run.content:
                response_str = (
                    run.content.model_dump_json(indent=2, exclude_none=True)
                    if isinstance(run.content, BaseModel)
                    else str(run.content)
                )

            history_data.append((input_str, response_str))

        return history_data

    def get_team_history_context(self, num_runs: Optional[int] = None) -> Optional[str]:
        """Get formatted team history context for steps

        Args:
            num_runs: Number of recent runs to include. If None, returns all available history.
        """
        history_data = self.get_team_history(num_runs)

        if not history_data:
            return None

        # Format as team history context using the structured data
        context_parts = ["<team_history_context>"]

        for i, (input_str, response_str) in enumerate(history_data, 1):
            context_parts.append(f"[run-{i}]")

            if input_str:
                context_parts.append(f"input: {input_str}")
            if response_str:
                context_parts.append(f"response: {response_str}")

            context_parts.append("")  # Empty line between runs

        context_parts.append("</team_history_context>")
        context_parts.append("")  # Empty line before current input

        return "\n".join(context_parts)

    def get_session_summary(self) -> Optional[SessionSummary]:
        """Get the session summary for the session"""

        if self.summary is None:
            return None

        return self.summary  # type: ignore
