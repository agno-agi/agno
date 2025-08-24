import time
from dataclasses import asdict
from typing import Dict, List, Literal, Optional

from agno.storage.base import Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.v2.workflow import WorkflowSession as WorkflowSessionV2
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import logger


class InMemoryStorage(Storage):
    def __init__(
        self,
        mode: Optional[Literal["agent", "team", "workflow", "workflow_v2"]] = "agent",
        storage_dict: Optional[Dict[str, Dict]] = None,
    ):
        super().__init__(mode)
        self.storage: Dict[str, Dict] = storage_dict if storage_dict is not None else {}

    def create(self) -> None:
        """Create the storage if it doesn't exist."""
        # No-op for in-memory storage
        pass

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """Read a Session from storage."""
        try:
            data = self.storage.get(session_id)
            if data is None:
                return None
            if user_id and data["user_id"] != user_id:
                return None
            if self.mode == "agent":
                return AgentSession.from_dict(data)
            elif self.mode == "team":
                return TeamSession.from_dict(data)
            elif self.mode == "workflow":
                return WorkflowSession.from_dict(data)
            elif self.mode == "workflow_v2":
                return WorkflowSessionV2.from_dict(data)

        except Exception as e:
            logger.error(f"Error reading session {session_id}: {e}")
            return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """Get all session IDs, optionally filtered by user_id and/or entity_id."""
        session_ids = []
        for _, data in self.storage.items():
            if user_id or entity_id:
                if user_id and entity_id:
                    if self.mode == "agent" and data["agent_id"] == entity_id and data["user_id"] == user_id:
                        session_ids.append(data["session_id"])
                    elif self.mode == "team" and data["team_id"] == entity_id and data["user_id"] == user_id:
                        session_ids.append(data["session_id"])
                    elif self.mode == "workflow" and data["workflow_id"] == entity_id and data["user_id"] == user_id:
                        session_ids.append(data["session_id"])

                elif user_id and data["user_id"] == user_id:
                    session_ids.append(data["session_id"])

                elif entity_id:
                    if self.mode == "agent" and data["agent_id"] == entity_id:
                        session_ids.append(data["session_id"])
                    elif self.mode == "team" and data["team_id"] == entity_id:
                        session_ids.append(data["session_id"])
                    elif self.mode == "workflow" and data["workflow_id"] == entity_id:
                        session_ids.append(data["session_id"])
                    elif self.mode == "workflow_v2" and data["workflow_id"] == entity_id:
                        session_ids.append(data["session_id"])

            else:
                # No filters applied, add all session_ids
                session_ids.append(data["session_id"])

        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """Get all sessions, optionally filtered by user_id and/or entity_id."""
        sessions: List[Session] = []
        for _, data in self.storage.items():
            if user_id or entity_id:
                _session: Optional[Session] = None

                if user_id and entity_id:
                    if self.mode == "agent" and data["agent_id"] == entity_id and data["user_id"] == user_id:
                        _session = AgentSession.from_dict(data)
                    elif self.mode == "team" and data["team_id"] == entity_id and data["user_id"] == user_id:
                        _session = TeamSession.from_dict(data)
                    elif self.mode == "workflow" and data["workflow_id"] == entity_id and data["user_id"] == user_id:
                        _session = WorkflowSession.from_dict(data)

                elif user_id and data["user_id"] == user_id:
                    if self.mode == "agent":
                        _session = AgentSession.from_dict(data)
                    elif self.mode == "team":
                        _session = TeamSession.from_dict(data)
                    elif self.mode == "workflow":
                        _session = WorkflowSession.from_dict(data)

                elif entity_id:
                    if self.mode == "agent" and data["agent_id"] == entity_id:
                        _session = AgentSession.from_dict(data)
                    elif self.mode == "team" and data["team_id"] == entity_id:
                        _session = TeamSession.from_dict(data)
                    elif self.mode == "workflow" and data["workflow_id"] == entity_id:
                        _session = WorkflowSession.from_dict(data)
                    elif self.mode == "workflow_v2" and data["workflow_id"] == entity_id:
                        _session = WorkflowSessionV2.from_dict(data)

                if _session:
                    sessions.append(_session)

            else:
                # No filters applied, add all sessions
                if self.mode == "agent":
                    _session = AgentSession.from_dict(data)
                elif self.mode == "team":
                    _session = TeamSession.from_dict(data)
                elif self.mode == "workflow":
                    _session = WorkflowSession.from_dict(data)
                elif self.mode == "workflow_v2":
                    _session = WorkflowSessionV2.from_dict(data)

                if _session:
                    sessions.append(_session)

        return sessions

    def get_recent_sessions(
        self,
        user_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: Optional[int] = 2,
    ) -> List[Session]:
        """Get the last N sessions, ordered by created_at descending.

        Args:
            limit: Number of most recent sessions to return
            user_id: Filter by user ID
            entity_id: Filter by entity ID (agent_id, team_id, or workflow_id)

        Returns:
            List[Session]: List of most recent sessions
        """
        sessions: List[Session] = []
        # List of (created_at, data) tuples for sorting
        session_data: List[tuple[int, dict]] = []

        # First pass: collect and filter sessions
        for session_id, data in self.storage.items():
            try:
                if user_id and data["user_id"] != user_id:
                    continue

                if entity_id:
                    if self.mode == "agent" and data["agent_id"] != entity_id:
                        continue
                    elif self.mode == "team" and data["team_id"] != entity_id:
                        continue
                    elif self.mode == "workflow" and data["workflow_id"] != entity_id:
                        continue
                    elif self.mode == "workflow_v2" and data["workflow_id"] != entity_id:
                        continue

                # Store with created_at for sorting
                created_at = data.get("created_at", 0)
                session_data.append((created_at, data))

            except Exception as e:
                logger.error(f"Error processing session {session_id}: {e}")
                continue

        # Sort by created_at descending and take only limit sessions
        session_data.sort(key=lambda x: x[0], reverse=True)
        if limit is not None:
            session_data = session_data[:limit]

        # Convert filtered and sorted data to Session objects
        for _, data in session_data:
            session: Optional[Session] = None
            if self.mode == "agent":
                session = AgentSession.from_dict(data)
            elif self.mode == "team":
                session = TeamSession.from_dict(data)
            elif self.mode == "workflow":
                session = WorkflowSession.from_dict(data)
            elif self.mode == "workflow_v2":
                session = WorkflowSessionV2.from_dict(data)
            if session is not None:
                sessions.append(session)

        return sessions

    def upsert(self, session: Session) -> Optional[Session]:
        """Insert or update a Session in storage."""
        try:
            if self.mode == "workflow_v2":
                data = session.to_dict()
            else:
                data = asdict(session)

            data["updated_at"] = int(time.time())
            if not data.get("created_at", None):
                data["created_at"] = data["updated_at"]

            self.storage[session.session_id] = data
            return session

        except Exception as e:
            logger.error(f"Error upserting session: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None):
        """Delete a session from storage."""
        if session_id is None:
            return

        try:
            self.storage.pop(session_id, None)

        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """Drop all sessions from storage."""
        self.storage.clear()

    def upgrade_schema(self) -> None:
        """Upgrade the schema of the storage."""
        pass
