from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.run.agent import RunOutput, RunStatus
from agno.run.team import TeamRunOutput
from agno.session.summary import SessionSummary
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb


@dataclass
class TeamSession:
    """Team Session that is stored in the database

    Supports both legacy JSONB storage (runs stored in session) and
    normalized storage (v2.5+, runs stored in separate tables).

    When use_normalized_storage=True, runs are loaded lazily from the
    database and messages are queried directly from the messages table.
    """

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
    # List of all runs in the session (legacy storage or cached from normalized)
    runs: Optional[list[Union[TeamRunOutput, RunOutput]]] = None
    # Summary of the session
    summary: Optional[SessionSummary] = None

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
            "team_id": self.team_id,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "team_data": self.team_data,
            "session_data": self.session_data,
            "metadata": self.metadata,
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
    ) -> Optional[TeamSession]:
        """Create a TeamSession from a dictionary.

        Args:
            data: Dictionary containing session data.
            db: Optional database reference for lazy loading runs.
            use_normalized_storage: If True, runs will be loaded from
                                   normalized tables instead of JSONB.
        """
        if data is None or data.get("session_id") is None:
            log_warning("TeamSession is missing session_id")
            return None

        summary = data.get("summary")
        if summary is not None and isinstance(summary, dict):
            summary = SessionSummary.from_dict(summary)

        runs = data.get("runs")
        serialized_runs: List[Union[TeamRunOutput, RunOutput]] = []

        # Only deserialize runs if not using normalized storage and runs exist
        if runs is not None and not use_normalized_storage:
            if isinstance(runs, list) and len(runs) > 0 and isinstance(runs[0], dict):
                for run in runs:
                    if "agent_id" in run:
                        serialized_runs.append(RunOutput.from_dict(run))
                    elif "team_id" in run:
                        serialized_runs.append(TeamRunOutput.from_dict(run))

        session = cls(
            session_id=data.get("session_id"),  # type: ignore
            team_id=data.get("team_id"),
            user_id=data.get("user_id"),
            workflow_id=data.get("workflow_id"),
            team_data=data.get("team_data"),
            session_data=data.get("session_data"),
            metadata=data.get("metadata"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            runs=serialized_runs if serialized_runs else None,
            summary=summary,
            use_normalized_storage=use_normalized_storage,
        )

        if db:
            session._db = db

        return session

    def get_run(self, run_id: str) -> Optional[Union[TeamRunOutput, RunOutput]]:
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

    def upsert_run(self, run_response: Union[TeamRunOutput, RunOutput], persist_to_db: bool = False):
        """Adds a RunOutput, together with some calculated data, to the runs list.

        Args:
            run_response: The RunOutput or TeamRunOutput to add or update.
            persist_to_db: If True and using normalized storage, persist the run
                          to the database immediately.
        """
        messages = run_response.messages

        # Make message duration None
        for m in messages or []:
            if m.metrics is not None:
                m.metrics.duration = None

        if not self.runs:
            self.runs = []

        for i, existing_run in enumerate(self.runs or []):
            if existing_run.run_id == run_response.run_id:
                self.runs[i] = run_response
                break
        else:
            self.runs.append(run_response)

        # Persist to normalized storage if enabled
        if persist_to_db and self.use_normalized_storage and self._db is not None:
            try:
                if hasattr(self._db, "upsert_run"):
                    run_dict = run_response.to_dict()
                    self._db.upsert_run(
                        run_id=run_response.run_id,  # type: ignore
                        session_id=self.session_id,
                        run_data=run_dict,
                    )

                    # Also persist messages
                    if hasattr(self._db, "upsert_messages") and run_response.messages:
                        message_dicts = [m.to_dict() for m in run_response.messages if not m.from_history]
                        if message_dicts:
                            self._db.upsert_messages(run_id=run_response.run_id, messages=message_dicts)  # type: ignore

                    log_debug("Persisted run to normalized storage")
            except Exception as e:
                log_warning(f"Failed to persist run to normalized storage: {e}")

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
                                  Note: In normalized storage (v2.5+), history messages are never
                                  stored, so this flag only affects legacy storage.
            skip_member_messages: Skip messages created by members of the team.

        Returns:
            A list of Messages belonging to the session.
        """
        # Try to use normalized storage for efficient message retrieval
        # Note: For teams, we still need to filter by team/member, so we use the runs approach
        # but load from normalized storage if needed
        if self.use_normalized_storage and not self._runs_loaded:
            self._load_runs_from_db()

        return self._get_messages_from_runs(
            team_id=team_id,
            member_ids=member_ids,
            last_n_runs=last_n_runs,
            limit=limit,
            skip_roles=skip_roles,
            skip_statuses=skip_statuses,
            skip_history_messages=skip_history_messages,
            skip_member_messages=skip_member_messages,
        )

    def _get_messages_from_runs(
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
        """Get messages by iterating through runs.

        Used for both legacy and normalized storage.
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
            session_runs = [run for run in session_runs if hasattr(run, "agent_id") and run.agent_id in member_ids]  # type: ignore

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
        # Load runs from normalized storage if needed
        if self.use_normalized_storage and not self._runs_loaded:
            self._load_runs_from_db()

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
        # Load runs from normalized storage if needed
        if self.use_normalized_storage and not self._runs_loaded:
            self._load_runs_from_db()

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
