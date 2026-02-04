from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Union

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.summary import SessionSummary
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb


@dataclass
class AgentSession:
    """Agent Session that is stored in the database

    Supports both legacy JSONB storage (runs stored in session) and
    normalized storage (v2.5+, runs stored in separate tables).

    When use_normalized_storage=True, runs are loaded lazily from the
    database and messages are queried directly from the messages table.
    """

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
    # List of all runs in the session (legacy storage or cached from normalized)
    runs: Optional[List[Union[RunOutput, TeamRunOutput]]] = None
    # Summary of the session
    summary: Optional["SessionSummary"] = None

    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    # v2.5+ Normalized storage support
    # When True, runs are stored in separate tables instead of JSONB
    use_normalized_storage: bool = field(default=False, repr=False)
    # Database reference for lazy loading (not serialized)
    _db: Optional["BaseDb"] = field(default=None, repr=False)
    # Flag to track if runs have been loaded from normalized storage
    _runs_loaded: bool = field(default=False, repr=False)

    def to_dict(self, include_runs: bool = True) -> Dict[str, Any]:
        """Convert session to dictionary for storage.

        Args:
            include_runs: If True (default), includes runs in the dict.
                         Set to False when using normalized storage to avoid
                         storing runs in the session JSONB.
        """
        session_dict = {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "team_id": self.team_id,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "session_data": self.session_data,
            "metadata": self.metadata,
            "agent_data": self.agent_data,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

        # Only include runs if not using normalized storage or explicitly requested
        if include_runs and not self.use_normalized_storage:
            session_dict["runs"] = [run.to_dict() for run in self.runs] if self.runs else None
        else:
            session_dict["runs"] = None

        session_dict["summary"] = self.summary.to_dict() if self.summary else None

        return session_dict

    def set_db(self, db: "BaseDb") -> None:
        """Set the database reference for lazy loading runs.

        Args:
            db: Database instance to use for loading runs.
        """
        self._db = db

    def enable_normalized_storage(self, db: Optional["BaseDb"] = None) -> None:
        """Enable normalized storage mode for this session.

        When enabled, runs are stored in separate tables instead of JSONB.

        Args:
            db: Optional database instance to use for lazy loading.
        """
        self.use_normalized_storage = True
        if db:
            self._db = db

    def _load_runs_from_db(self) -> None:
        """Load runs from the normalized storage tables."""
        if self._runs_loaded or self._db is None:
            return

        try:
            # Check if db has the normalized storage methods
            if not hasattr(self._db, "get_runs"):
                log_debug("Database does not support normalized storage, using legacy runs")
                self._runs_loaded = True
                return

            run_dicts = self._db.get_runs(session_id=self.session_id)
            if run_dicts:
                self.runs = []
                for run_dict in run_dicts:
                    # Load messages for this run
                    if hasattr(self._db, "get_messages"):
                        raw_messages = self._db.get_messages(run_id=run_dict.get("run_id"))
                        if raw_messages:
                            # Clean up message dicts for Message.from_dict
                            db_only_fields = ("message_id", "run_id", "session_id", "message_order")
                            cleaned_messages = []
                            for msg in raw_messages:
                                cleaned_msg = {
                                    k: v for k, v in msg.items()
                                    if v is not None and k not in db_only_fields
                                }
                                if "message_id" in msg and msg["message_id"]:
                                    cleaned_msg["id"] = msg["message_id"]
                                cleaned_messages.append(cleaned_msg)
                            run_dict["messages"] = cleaned_messages

                    if "agent_id" in run_dict:
                        self.runs.append(RunOutput.from_dict(run_dict))
                    elif "team_id" in run_dict:
                        self.runs.append(TeamRunOutput.from_dict(run_dict))

            self._runs_loaded = True
            log_debug(f"Loaded {len(self.runs or [])} runs from normalized storage")

        except Exception as e:
            log_warning(f"Failed to load runs from normalized storage: {e}")
            self._runs_loaded = True

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        db: Optional["BaseDb"] = None,
        use_normalized_storage: bool = False,
    ) -> Optional[AgentSession]:
        """Create an AgentSession from a dictionary.

        Args:
            data: Dictionary containing session data.
            db: Optional database reference for lazy loading runs.
            use_normalized_storage: If True, runs will be loaded from
                                   normalized tables instead of JSONB.
        """
        if data is None or data.get("session_id") is None:
            log_warning("AgentSession is missing session_id")
            return None

        runs = data.get("runs")
        serialized_runs: List[Union[RunOutput, TeamRunOutput]] = []

        # Only deserialize runs if not using normalized storage and runs exist
        if runs is not None and not use_normalized_storage:
            if isinstance(runs, list) and len(runs) > 0 and isinstance(runs[0], dict):
                for run in runs:
                    if "agent_id" in run:
                        serialized_runs.append(RunOutput.from_dict(run))
                    elif "team_id" in run:
                        serialized_runs.append(TeamRunOutput.from_dict(run))

        summary = data.get("summary")
        if summary is not None and isinstance(summary, dict):
            summary = SessionSummary.from_dict(summary)

        metadata = data.get("metadata")

        session = cls(
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
            runs=serialized_runs if serialized_runs else None,
            summary=summary,
            use_normalized_storage=use_normalized_storage,
        )

        if db:
            session._db = db

        return session

    def upsert_run(self, run: RunOutput, persist_to_db: bool = False):
        """Adds a RunOutput, together with some calculated data, to the runs list.

        Args:
            run: The RunOutput to add or update.
            persist_to_db: If True and using normalized storage, persist the run
                          to the database immediately.
        """
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

        # Persist to normalized storage if enabled
        if persist_to_db and self.use_normalized_storage and self._db is not None:
            try:
                if hasattr(self._db, "upsert_run"):
                    run_dict = run.to_dict()
                    self._db.upsert_run(
                        run_id=run.run_id,  # type: ignore
                        session_id=self.session_id,
                        run_data=run_dict,
                    )

                    # Also persist messages
                    if hasattr(self._db, "upsert_messages") and run.messages:
                        message_dicts = [m.to_dict() for m in run.messages if not m.from_history]
                        if message_dicts:
                            self._db.upsert_messages(run_id=run.run_id, messages=message_dicts)  # type: ignore

                    log_debug("Persisted run to normalized storage")
            except Exception as e:
                log_warning(f"Failed to persist run to normalized storage: {e}")

        log_debug("Added RunOutput to Agent Session")

    def get_run(self, run_id: str) -> Optional[Union[RunOutput, TeamRunOutput]]:
        """Get a run by ID.

        If using normalized storage and runs haven't been loaded, will attempt
        to load from the database.
        """
        # Try to load from normalized storage if not already loaded
        if self.use_normalized_storage and not self._runs_loaded:
            self._load_runs_from_db()

        for run in self.runs or []:
            if run.run_id == run_id:
                return run

        # If not found in cache and using normalized storage, try direct lookup
        if self.use_normalized_storage and self._db is not None and hasattr(self._db, "get_run"):
            run_dict = self._db.get_run(run_id)
            if run_dict:
                # Load messages for this run
                if hasattr(self._db, "get_messages"):
                    messages = self._db.get_messages(run_id=run_id)
                    if messages:
                        run_dict["messages"] = messages

                if "agent_id" in run_dict:
                    return RunOutput.from_dict(run_dict)
                elif "team_id" in run_dict:
                    return TeamRunOutput.from_dict(run_dict)

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
                                  Note: In normalized storage (v2.5+), history messages are never
                                  stored, so this flag only affects legacy storage.

        Returns:
            A list of Messages belonging to the session.
        """
        # Try to use normalized storage for efficient message retrieval
        if self.use_normalized_storage and self._db is not None and hasattr(self._db, "get_messages"):
            return self._get_messages_from_normalized_storage(
                last_n_runs=last_n_runs,
                limit=limit,
                skip_roles=skip_roles,
            )

        # Fall back to legacy behavior
        return self._get_messages_from_runs(
            agent_id=agent_id,
            team_id=team_id,
            last_n_runs=last_n_runs,
            limit=limit,
            skip_roles=skip_roles,
            skip_statuses=skip_statuses,
            skip_history_messages=skip_history_messages,
        )

    def _get_messages_from_normalized_storage(
        self,
        last_n_runs: Optional[int] = None,
        limit: Optional[int] = None,
        skip_roles: Optional[List[str]] = None,
    ) -> List[Message]:
        """Get messages directly from the normalized messages table.

        This is more efficient than loading all runs and iterating through them.
        """
        if self._db is None or not hasattr(self._db, "get_messages"):
            return []

        try:
            message_dicts = self._db.get_messages(
                session_id=self.session_id,
                last_n_runs=last_n_runs,
                limit=limit,
                skip_roles=skip_roles,
            )

            messages = []
            system_message = None

            for msg_dict in message_dicts:
                # Clean up the dict for Message.from_dict - remove None values
                # and database-specific fields that Message doesn't expect
                db_only_fields = ("message_id", "run_id", "session_id", "message_order")
                cleaned_dict = {
                    k: v for k, v in msg_dict.items()
                    if v is not None and k not in db_only_fields
                }
                # Rename message_id to id if present
                if "message_id" in msg_dict and msg_dict["message_id"]:
                    cleaned_dict["id"] = msg_dict["message_id"]

                message = Message.from_dict(cleaned_dict)
                if message.role == "system":
                    if system_message is None:
                        system_message = message
                        messages.append(system_message)
                else:
                    messages.append(message)

            # Remove leading tool messages without associated assistant message
            while len(messages) > 0 and messages[0].role == "tool":
                messages.pop(0)

            log_debug(f"Got {len(messages)} messages from normalized storage")
            return messages

        except Exception as e:
            log_warning(f"Failed to get messages from normalized storage: {e}")
            return []

    def _get_messages_from_runs(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        last_n_runs: Optional[int] = None,
        limit: Optional[int] = None,
        skip_roles: Optional[List[str]] = None,
        skip_statuses: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Legacy method to get messages by iterating through runs.

        Used when normalized storage is not available or not enabled.
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

        # Load runs from normalized storage if needed
        if self.use_normalized_storage and not self._runs_loaded:
            self._load_runs_from_db()

        if not self.runs:
            return []

        if skip_statuses is None:
            skip_statuses = [RunStatus.paused, RunStatus.cancelled, RunStatus.error]

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

    def get_chat_history(self, last_n_runs: Optional[int] = None) -> List[Message]:
        """Return the chat history (user and assistant messages) for the session.
        Use get_messages() for more filtering options.

        Args:
            last_n_runs: Number of recent runs to include. If None, all runs will be considered.

        Returns:
            A list of user and assistant Messages belonging to the session.
        """
        return self.get_messages(skip_roles=["system", "tool"], last_n_runs=last_n_runs)

    def get_tool_calls(self, num_calls: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns a list of tool calls from the messages"""
        # Load runs from normalized storage if needed
        if self.use_normalized_storage and not self._runs_loaded:
            self._load_runs_from_db()

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
