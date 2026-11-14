from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, Union

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import HISTORY_SKIP_STATUSES, RunStatus
from agno.run.team import TeamRunOutput
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
    runs: Optional[List[Union[RunOutput, TeamRunOutput]]] = None
    # Summary of the session
    summary: Optional["SessionSummary"] = None

    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def to_dict(self, include_runs: bool = True) -> Dict[str, Any]:
        # Exclude runs from asdict to avoid the deep serialization cost. Serialize
        # a shallow copy so we never mutate a live (possibly shared/cached) session
        # while another thread reads self.runs.
        session_copy = copy.copy(self)
        session_copy.runs = None
        session_dict = asdict(session_copy)

        if include_runs:
            session_dict["runs"] = [run.to_dict() for run in self.runs] if self.runs else None
        else:
            session_dict.pop("runs", None)
        session_dict["summary"] = self.summary.to_dict() if self.summary else None

        return session_dict

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[AgentSession]:
        if data is None or data.get("session_id") is None:
            log_warning("AgentSession is missing session_id")
            return None

        runs = data.get("runs")
        serialized_runs: List[Union[RunOutput, TeamRunOutput]] = []
        if runs and isinstance(runs[0], dict):
            for run in runs:
                if "agent_id" in run:
                    serialized_runs.append(RunOutput.from_dict(run))
                elif "team_id" in run:
                    serialized_runs.append(TeamRunOutput.from_dict(run))

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
            runs=serialized_runs,
            summary=summary,
        )

    def upsert_run(self, run: RunOutput):
        """Adds a RunOutput, together with some calculated data, to the runs list."""
        messages = run.messages
        for m in messages or []:
            if m.metrics is not None and hasattr(m.metrics, "timer"):
                m.metrics.timer = None

        if not self.runs:
            self.runs = []

        for i, existing_run in enumerate(self.runs or []):
            if existing_run.run_id == run.run_id:
                # queue_attempt is sticky: the generation stamp lives on the
                # stored row (written by the queue worker's fenced patch), and
                # a whole-run save from execution - which never knows its
                # attempt - must not erase it
                if getattr(run, "queue_attempt", None) is None:
                    run.queue_attempt = getattr(existing_run, "queue_attempt", None)
                self.runs[i] = run
                break
        else:
            self.runs.append(run)

        log_debug("Added RunOutput to Agent Session")

    def get_run(self, run_id: str) -> Optional[Union[RunOutput, TeamRunOutput]]:
        """The run with this id, as the caller's own copy.

        History run objects are shared between session reads, and get_run's
        callers mutate what they fetch -- background continue flips status,
        HITL surfaces write answers into requirements and tools -- before
        persisting. Handing out the shared object would publish those
        mutations to every reader of the session before (or without) a store
        write, so each caller gets a run of its own.
        """
        from copy import deepcopy

        for run in self.runs or []:
            if run.run_id == run_id:
                return deepcopy(run)
        return None

    def get_messages(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        last_n_runs: Optional[int] = None,
        limit: Optional[int] = None,
        skip_roles: Optional[List[str]] = None,
        skip_statuses: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
        viewer_agent_id: Optional[str] = None,
    ) -> List[Message]:
        """Returns the messages belonging to the session that fit the given criteria.

        Args:
            agent_id: The id of the agent to get the messages from.
            team_id: The id of the team to get the messages from.
            last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
            limit: The number of messages to return, counting from the latest. Defaults to all messages.
            skip_roles: Skip messages with these roles.
            skip_statuses: Skip messages with these statuses.
            skip_history_messages: Skip messages that were tagged as history in previous runs.
            viewer_agent_id: Render a session shared between agents as this agent sees it: another
                agent's replies become user-role messages prefixed with that agent's name, its tool
                traffic is left out, and a user message that reached several agents appears once.

        Returns:
            A list of Messages belonging to the session.
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

        if not self.runs:
            return []

        if skip_statuses is None:
            skip_statuses = list(HISTORY_SKIP_STATUSES)

        runs = self.runs

        # Filter by agent_id and team_id
        if agent_id:
            runs = [run for run in runs if hasattr(run, "agent_id") and run.agent_id == agent_id]  # type: ignore
        if team_id:
            runs = [run for run in runs if hasattr(run, "team_id") and run.team_id == team_id]  # type: ignore

        # Skip any messages that might be part of members of teams (for session re-use)
        runs = [run for run in runs if run.parent_run_id is None]  # type: ignore

        # Filter by status
        runs = [run for run in runs if hasattr(run, "status") and run.status not in skip_statuses]  # type: ignore

        # Filter by last_n_runs before applying message limit
        if last_n_runs is not None:
            if last_n_runs <= 0:
                return []
            runs = runs[-last_n_runs:]

        run_messages: List[Tuple[Any, List[Message]]] = [(run, run.messages or []) for run in runs if run]
        if viewer_agent_id is not None:
            run_messages = self._shared_session_view(run_messages, viewer_agent_id)

        messages_from_history = []
        system_message = None

        # Limit the number of messages returned if limit is set
        if limit is not None:
            for _run_response, run_msgs in run_messages:
                for message in run_msgs:
                    if _should_skip_message(message, skip_roles, skip_history_messages):
                        continue

                    if message.role == "system":
                        # Only add the system message once
                        if system_message is None:
                            system_message = message
                    else:
                        messages_from_history.append(message)

            if system_message:
                if limit <= 1:
                    messages_from_history = [system_message]
                else:
                    messages_from_history = [system_message] + messages_from_history[
                        -(limit - 1) :
                    ]  # Grab one less message then add the system message
            else:
                if limit <= 0:
                    messages_from_history = []
                else:
                    messages_from_history = messages_from_history[-limit:]

            # Remove tool result messages that don't have an associated assistant message with tool calls
            while len(messages_from_history) > 0 and messages_from_history[0].role == "tool":
                messages_from_history.pop(0)

        # If limit is not set, return all messages
        else:
            for _run_response, run_msgs in run_messages:
                for message in run_msgs:
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

    @staticmethod
    def _shared_session_view(
        run_messages: List[Tuple[Any, List[Message]]], viewer_agent_id: str
    ) -> List[Tuple[Any, List[Message]]]:
        """Render the runs of a session shared between agents as ``viewer_agent_id`` sees them.

        The viewer's own runs are left as they are. Another agent's run keeps its user messages
        and its replies: a reply becomes a user-role message prefixed with the author's name, so
        the viewer never mistakes it for its own words, and tool and system traffic is left out.
        A user message run through several agents keeps one Message id across those runs, so it
        appears once, in the first run that carried it.
        """
        seen_user_message_ids: Set[str] = set()
        view: List[Tuple[Any, List[Message]]] = []
        for run, messages in run_messages:
            is_own_run = getattr(run, "agent_id", None) == viewer_agent_id
            author = getattr(run, "agent_name", None) or getattr(run, "agent_id", None) or "agent"
            kept: List[Message] = []
            for message in messages:
                if message.role == "user":
                    # History copies keep the id of the message they replay and are dropped later,
                    # so they must not claim the id ahead of the run's own input.
                    if not message.from_history and message.id is not None:
                        if message.id in seen_user_message_ids:
                            continue
                        seen_user_message_ids.add(message.id)
                elif not is_own_run:
                    if message.role != "assistant" or message.tool_calls or not message.content:
                        continue
                    # Same id as the stored reply, so compaction anchors and replay counts hold.
                    message = Message(
                        id=message.id,
                        role="user",
                        content=f"{author}: {message.get_content_string()}",
                        from_history=message.from_history,
                        created_at=message.created_at,
                    )
                kept.append(message)
            view.append((run, kept))
        return view

    def get_chat_history(self, last_n_runs: Optional[int] = None) -> List[Message]:
        """Return the chat history (user and assistant messages) for the session.
        Use get_messages() for more filtering options.

        Args:
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.

        Returns:
            A list of user and assistant Messages belonging to the session.
        """
        return self.get_messages(skip_roles=["system", "tool"], skip_statuses=[], last_n_runs=last_n_runs)

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

    def get_session_summary(self) -> Optional[SessionSummary]:
        """Get the session summary for the session"""

        if self.summary is None:
            return None
        return self.summary
