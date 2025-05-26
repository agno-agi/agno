import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Literal, Optional, Union

from agno.storage.base import Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import logger


class JsonStorage(Storage):
    def __init__(self, dir_path: Union[str, Path], mode: Optional[Literal["agent", "team", "workflow"]] = "agent"):
        super().__init__(mode)
        self.dir_path = Path(dir_path)
        self.dir_path.mkdir(parents=True, exist_ok=True)

    def serialize(self, data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, indent=4)

    def deserialize(self, data: str) -> dict:
        return json.loads(data)

    def create(self) -> None:
        """Create the storage if it doesn't exist."""
        if not self.dir_path.exists():
            self.dir_path.mkdir(parents=True, exist_ok=True)

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """Read an AgentSession from storage."""
        try:
            with open(self.dir_path / f"{session_id}.json", "r", encoding="utf-8") as f:
                data = self.deserialize(f.read())
                if user_id and data["user_id"] != user_id:
                    return None
                if self.mode == "agent":
                    return AgentSession.from_dict(data)
                elif self.mode == "team":
                    return TeamSession.from_dict(data)
                elif self.mode == "workflow":
                    return WorkflowSession.from_dict(data)
        except FileNotFoundError:
            return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """Get all session IDs, optionally filtered by user_id and/or entity_id."""
        session_ids = []
        for file in self.dir_path.glob("*.json"):
            with open(file, "r", encoding="utf-8") as f:
                data = self.deserialize(f.read())
                if user_id or entity_id:
                    if user_id and entity_id:
                        if self.mode == "agent" and data["agent_id"] == entity_id and data["user_id"] == user_id:
                            session_ids.append(data["session_id"])
                        elif self.mode == "team" and data["team_id"] == entity_id and data["user_id"] == user_id:
                            session_ids.append(data["session_id"])
                        elif (
                            self.mode == "workflow" and data["workflow_id"] == entity_id and data["user_id"] == user_id
                        ):
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
                else:
                    # No filters applied, add all session_ids
                    session_ids.append(data["session_id"])
        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """Get all sessions, optionally filtered by user_id and/or entity_id."""
        sessions: List[Session] = []
        for file in self.dir_path.glob("*.json"):
            with open(file, "r", encoding="utf-8") as f:
                data = self.deserialize(f.read())
                if user_id or entity_id:
                    _session: Optional[Session] = None

                    if user_id and entity_id:
                        if self.mode == "agent" and data["agent_id"] == entity_id and data["user_id"] == user_id:
                            _session = AgentSession.from_dict(data)
                        elif self.mode == "team" and data["team_id"] == entity_id and data["user_id"] == user_id:
                            _session = TeamSession.from_dict(data)
                        elif (
                            self.mode == "workflow" and data["workflow_id"] == entity_id and data["user_id"] == user_id
                        ):
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
            num_history_sessions: Number of most recent sessions to return
            user_id: Filter by user ID
            entity_id: Filter by entity ID (agent_id, team_id, or workflow_id)

        Returns:
            List[Session]: List of most recent sessions
        """
        sessions: List[Session] = []
        # List of (created_at, data) tuples for sorting
        session_data: List[tuple[int, dict]] = []

        # First pass: collect and filter sessions
        for file in self.dir_path.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = self.deserialize(f.read())

                    if user_id and data["user_id"] != user_id:
                        continue

                    if entity_id:
                        if self.mode == "agent" and data["agent_id"] != entity_id:
                            continue
                        elif self.mode == "team" and data["team_id"] != entity_id:
                            continue
                        elif self.mode == "workflow" and data["workflow_id"] != entity_id:
                            continue

                    # Store with created_at for sorting
                    created_at = data.get("created_at", 0)
                    session_data.append((created_at, data))

            except Exception as e:
                logger.error(f"Error reading session file {file}: {e}")
                continue

        # Sort by created_at descending and take only num_history_sessions
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

            if session is not None:
                sessions.append(session)

        return sessions

    def upsert(self, session: Session) -> Optional[Session]:
        """Insert or update a Session in storage."""
        try:
            data = asdict(session)
            data["updated_at"] = int(time.time())
            if "created_at" not in data:
                data["created_at"] = data["updated_at"]

            with open(self.dir_path / f"{session.session_id}.json", "w", encoding="utf-8") as f:
                f.write(self.serialize(data))
            return session
        except Exception as e:
            logger.error(f"Error upserting session: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None):
        """Delete a session from storage."""
        if session_id is None:
            return
        try:
            (self.dir_path / f"{session_id}.json").unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """Drop all sessions from storage."""
        for file in self.dir_path.glob("*.json"):
            file.unlink()

    def upgrade_schema(self) -> None:
        """Upgrade the schema of the storage."""
        pass
