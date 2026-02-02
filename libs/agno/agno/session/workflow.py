from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.utils.log import log_debug, logger


@dataclass
class WorkflowSession:
    """Workflow Session for pipeline-based workflows"""

    # Session UUID - this is the workflow_session_id that gets set on agents/teams
    session_id: str
    # ID of the user interacting with this workflow
    user_id: Optional[str] = None

    # ID of the workflow that this session is associated with
    workflow_id: Optional[str] = None
    # Workflow name
    workflow_name: Optional[str] = None

    # Workflow runs - stores WorkflowRunOutput objects in memory
    runs: Optional[List[WorkflowRunOutput]] = None

    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Workflow configuration and metadata
    workflow_data: Optional[Dict[str, Any]] = None
    # Metadata stored with this workflow session
    metadata: Optional[Dict[str, Any]] = None

    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage, serializing runs to dicts"""

        runs_data = None
        if self.runs:
            runs_data = []
            for run in self.runs:
                try:
                    runs_data.append(run.to_dict())
                except Exception as e:
                    raise ValueError(f"Serialization failed: {str(e)}")

        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "runs": runs_data,
            "session_data": self.session_data,
            "workflow_data": self.workflow_data,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[WorkflowSession]:
        """Create WorkflowSession from dictionary, deserializing runs from dicts"""
        if data is None or data.get("session_id") is None:
            logger.warning("WorkflowSession is missing session_id")
            return None

        # Deserialize runs from dictionaries back to WorkflowRunOutput objects
        runs_data = data.get("runs")
        runs: Optional[List[WorkflowRunOutput]] = None

        if runs_data is not None:
            runs = []
            for run_item in runs_data:
                if isinstance(run_item, WorkflowRunOutput):
                    # Already a WorkflowRunOutput object (from deserialize_session_json_fields)
                    runs.append(run_item)
                elif isinstance(run_item, dict):
                    # Still a dictionary, needs to be converted
                    runs.append(WorkflowRunOutput.from_dict(run_item))
                else:
                    logger.warning(f"Unexpected run item type: {type(run_item)}")

        return cls(
            session_id=data.get("session_id"),  # type: ignore
            user_id=data.get("user_id"),
            workflow_id=data.get("workflow_id"),
            workflow_name=data.get("workflow_name"),
            runs=runs,
            session_data=data.get("session_data"),
            workflow_data=data.get("workflow_data"),
            metadata=data.get("metadata"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def __post_init__(self):
        if self.runs is None:
            self.runs = []

        # Ensure session_data, workflow_data, and metadata are dictionaries, not None
        if self.session_data is None:
            self.session_data = {}
        if self.workflow_data is None:
            self.workflow_data = {}
        if self.metadata is None:
            self.metadata = {}

        # Set timestamps if they're not already set
        current_time = int(time.time())
        if self.created_at is None:
            self.created_at = current_time
        if self.updated_at is None:
            self.updated_at = current_time

    def get_run(self, run_id: str) -> Optional[WorkflowRunOutput]:
        for run in self.runs or []:
            if run.run_id == run_id:
                return run
        return None

    def upsert_run(self, run: WorkflowRunOutput) -> None:
        """Add or update a workflow run (upsert behavior)"""
        if self.runs is None:
            self.runs = []

        # Find existing run and update it, or append new one
        for i, existing_run in enumerate(self.runs):
            if existing_run.run_id == run.run_id:
                self.runs[i] = run
                break
        else:
            self.runs.append(run)

    def get_workflow_history(self, num_runs: Optional[int] = None) -> List[Tuple[str, str]]:
        """Get workflow history as structured data (input, response pairs)

        Args:
            num_runs: Number of recent runs to include. If None, returns all available history.
        """
        if not self.runs:
            return []

        # Get completed runs only (exclude current/pending run)
        completed_runs = [run for run in self.runs if run.status == RunStatus.completed]

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
                input_str = str(run.input) if not isinstance(run.input, str) else run.input

            # Get response
            response_str = ""
            if run.content:
                response_str = str(run.content) if not isinstance(run.content, str) else run.content

            history_data.append((input_str, response_str))

        return history_data

    def get_workflow_history_context(self, num_runs: Optional[int] = None) -> Optional[str]:
        """Get formatted workflow history context for steps

        Args:
            num_runs: Number of recent runs to include. If None, returns all available history.
        """
        history_data = self.get_workflow_history(num_runs)

        if not history_data:
            return None

        # Format as workflow context using the structured data
        context_parts = ["<workflow_history_context>"]

        for i, (input_str, response_str) in enumerate(history_data, 1):
            context_parts.append(f"[Workflow Run-{i}]")

            if input_str:
                context_parts.append(f"User input: {input_str}")
            if response_str:
                context_parts.append(f"Workflow output: {response_str}")

            context_parts.append("")  # Empty line between runs

        context_parts.append("</workflow_history_context>")
        context_parts.append("")  # Empty line before current input

        return "\n".join(context_parts)

    def get_messages_from_agent_runs(
        self,
        runs: List[RunOutput],
        last_n_runs: Optional[int] = None,
        limit: Optional[int] = None,
        skip_roles: Optional[List[str]] = None,
        skip_statuses: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Return the messages belonging to the given agent runs that fit the given criteria.

        Args:
            runs: The list of agent runs to get the messages from.
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.
            limit: Number of messages to include. If None, all messages will be included.
            skip_roles: Roles to skip.
            skip_statuses: Statuses to skip.
            skip_history_messages: Whether to skip history messages.

        Returns:
            A list of messages from the given agent runs.
        """

        def _should_skip_message(
            message: Message, skip_roles: Optional[List[str]] = None, skip_history_messages: bool = True
        ) -> bool:
            """Logic to determine if a message should be skipped"""
            # Skip messages that were tagged as history in previous runs
            if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                return True

            # Skip messages with specified role
            if skip_roles and message.role in skip_roles:
                return True

            return False

        # Filter by status
        if skip_statuses:
            runs = [run for run in runs if hasattr(run, "status") and run.status not in skip_statuses]  # type: ignore

        messages_from_history = []
        system_message = None

        # Limit the number of messages returned if limit is set
        if limit is not None:
            for run_response in runs:
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

        # If limit is not set, return all messages
        else:
            runs_to_process = runs[-last_n_runs:] if last_n_runs is not None else runs
            for run_response in runs_to_process:
                if not run_response or not run_response.messages:
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

    def get_messages_from_team_runs(
        self,
        team_id: str,
        runs: List[TeamRunOutput],
        last_n_runs: Optional[int] = None,
        limit: Optional[int] = None,
        skip_roles: Optional[List[str]] = None,
        skip_statuses: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
        skip_member_messages: bool = True,
    ) -> List[Message]:
        """Return the messages in the given team runs that fit the given criteria.

        Args:
            team_id: The ID of the contextual team.
            runs: The list of team runs to get the messages from.
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.
            limit: Number of messages to include. If None, all messages will be included.
            skip_roles: Roles to skip.
            skip_statuses: Statuses to skip.
            skip_history_messages: Whether to skip history messages.
            skip_member_messages: Whether to skip messages from members of the team.

        Returns:
            A list of messages from the given team runs.
        """

        def _should_skip_message(
            message: Message, skip_roles: Optional[List[str]] = None, skip_history_messages: bool = True
        ) -> bool:
            """Logic to determine if a message should be skipped"""
            # Skip messages that were tagged as history in previous runs
            if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                return True

            # Skip messages with specified role
            if skip_roles and message.role in skip_roles:
                return True

            return False

        # Filter for top-level runs (main team runs or agent runs when sharing session)
        if skip_member_messages:
            session_runs = [run for run in runs if run.team_id == team_id]

        # Filter runs by status
        if skip_statuses:
            session_runs = [run for run in session_runs if hasattr(run, "status") and run.status not in skip_statuses]

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

    def get_messages(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        last_n_runs: Optional[int] = None,
        limit: Optional[int] = None,
        skip_roles: Optional[List[str]] = None,
        skip_statuses: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
        skip_member_messages: bool = True,
    ) -> List[Message]:
        """Return the messages belonging to the session that fit the given criteria.

        Args:
            agent_id: The ID of the agent to get the messages for.
            team_id: The ID of the team to get the messages for.
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.
            limit: Number of messages to include. If None, all messages will be included.
            skip_roles: Roles to skip.
            skip_statuses: Statuses to skip.
            skip_history_messages: Whether to skip history messages.
            skip_member_messages: Whether to skip messages from members of the team.

        Returns:
            A list of messages from the session.
        """
        if agent_id and team_id:
            raise ValueError("agent_id and team_id cannot be used together")

        if not self.runs:
            return []

        if agent_id:
            agent_runs: List[RunOutput] = []
            for run in self.runs:
                if run.step_executor_runs:
                    for executor_run in run.step_executor_runs:
                        if isinstance(executor_run, RunOutput) and executor_run.agent_id == agent_id:
                            agent_runs.append(executor_run)
            return self.get_messages_from_agent_runs(
                runs=agent_runs,
                last_n_runs=last_n_runs,
                limit=limit,
                skip_roles=skip_roles,
                skip_statuses=skip_statuses,
                skip_history_messages=skip_history_messages,
            )

        elif team_id:
            team_runs: List[TeamRunOutput] = []
            for run in self.runs:
                if run.step_executor_runs:
                    for executor_run in run.step_executor_runs:
                        if isinstance(executor_run, TeamRunOutput) and executor_run.team_id == team_id:
                            team_runs.append(executor_run)
            return self.get_messages_from_team_runs(
                team_id=team_id,
                runs=team_runs,
                last_n_runs=last_n_runs,
                limit=limit,
                skip_roles=skip_roles,
                skip_statuses=skip_statuses,
                skip_history_messages=skip_history_messages,
                skip_member_messages=skip_member_messages,
            )

        else:
            raise ValueError("agent_id or team_id must be provided")

    def get_chat_history(self, last_n_runs: Optional[int] = None) -> List[WorkflowChatInteraction]:
        """Return a list of dictionaries containing the input and output for each run in the session.

        Args:
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.

        Returns:
            A list of WorkflowChatInteraction objects.
        """
        if not self.runs:
            return []

        runs = self.runs

        if last_n_runs is not None:
            runs = self.runs[-last_n_runs:]

        return [
            WorkflowChatInteraction(input=run.input, output=run.content) for run in runs if run.input and run.content
        ]


@dataclass
class WorkflowChatInteraction:
    input: Union[str, Dict[str, Any], List[Any], BaseModel]
    output: Any
